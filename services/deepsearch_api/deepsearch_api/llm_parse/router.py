# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""POST /v3/deepsearch/llm_parse/query — parse-only LLM query-parsing endpoint.

Returns the interpreted IR plus the mapped DeepSearchSearchRequestV2 params. The
frontend merges those params into its existing search request and runs the
normal search.

Both failure modes surface as clear errors rather than a silent degraded result
(mirroring the VLM-validation endpoint): when the feature is disabled the
endpoint returns ``503`` ("not enabled"); when the LLM extraction itself fails
it raises ``LLMParseExtractionError``, which the app-level handler turns into a
``503`` ("temporarily unavailable") instead of an ambiguous 500. The frontend
treats any non-OK response as a cue to fall back to plain semantic search on the
raw text, so the user-facing search never hard-breaks — but the client always
knows parsing did not happen and never mistakes the raw query for a parsed one.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from .extractor import LLMParseExtractor
from .fields import REGISTRY
from .mapper import COMMA_JOIN_PARAMS, map_ir
from .models import ParsedQuery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deepsearch", tags=["AI Search"])


class QueryParsingRequest(BaseModel):
    query: str = Field(min_length=1, description="Raw free-text search text from the search bar.")

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, v: str) -> str:
        # min_length only counts characters, so a whitespace-only query ("   ")
        # slips through while "" is rejected. Strip and reject blanks so both 422.
        stripped = v.strip()
        if not stripped:
            raise ValueError("query must contain non-whitespace characters")
        return stripped


class QueryParsingResponse(ParsedQuery):
    """Same shape as ParsedQuery; kept as a distinct schema name for
    /llm_parse/query back-compat."""


class FilterFieldInfo(BaseModel):
    """One discoverable filter the deployment supports (from search_fields.yaml)."""

    name: str = Field(description="IR field name, e.g. 'polygon_count'.")
    value_type: str = Field(description="string | number | boolean | date | array.")
    operators: List[str] = Field(description="Operators valid for this field.")
    description: str = Field(description="Human-readable description for the picker.")
    examples: List[str] = Field(default_factory=list, description="Worked input → field op value hints.")
    params: List[str] = Field(
        default_factory=list,
        description="DeepSearchSearchRequestV2 field key(s) this filter maps to.",
    )
    comma_join: bool = Field(
        default=False,
        description="True if this filter's request params accumulate as a comma-joined list "
        "(union on repeat) rather than being overwritten.",
    )
    kind: str = Field(
        default="",
        description="The map.kind builder behind this field (e.g. 'property_exists', 'bbox').",
    )
    property: Optional[str] = Field(
        default=None,
        description="Resolved USD property key (env override applied) for property-backed "
        "fields; null for fields not backed by a single property.",
    )


@router.post(
    "/llm_parse/query",
    response_model=QueryParsingResponse,
    summary="Parse a free-text query into structured search parameters",
    description=(
        "Uses an LLM with constrained (JSON-schema) decoding to turn free-text into a structured "
        "intermediate representation, then deterministically maps it onto search request fields. "
        "Returns a 503 if the feature is disabled on this server or the LLM call fails."
    ),
)
async def parse_query(request: Request, body: QueryParsingRequest = Body(...)) -> QueryParsingResponse:
    extractor: LLMParseExtractor = getattr(request.app, "llm_parse_extractor", None)
    if extractor is None:
        # Mirror the VLM-validation endpoint: a disabled feature is a clear 503,
        # not a silently-degraded 200 that the caller could mistake for a parse.
        raise HTTPException(status_code=503, detail="LLM query parsing is not enabled on this server")

    # A failure here raises LLMParseExtractionError, handled app-side as a clear
    # 503 instead of an ambiguous 500. The mapper is pure and defensive, so the
    # only failure mode that reaches the client is the LLM call itself.
    ir = await extractor.extract(body.query)
    search_params, applied, dropped = map_ir(ir)
    # Echo back only the filters the mapper actually applied: a filter the search
    # silently dropped (unsupported operator for the field, or a value the mapper
    # rejected) must never appear in interpreted_query, or the client would show
    # the user a constraint that was never enforced. The dropped ones (with a
    # reason) are reported separately so the UI can still tell the user about them.
    interpreted = ir.model_copy(update={"filters": applied})
    logger.info(
        "LLM query parsing interpreted query=%r -> applied=%d dropped=%d unmapped=%d",
        body.query,
        len(applied),
        len(dropped),
        len(ir.unmapped_constraints),
    )
    return QueryParsingResponse(
        interpreted_query=interpreted,
        search_params=search_params,
        dropped_filters=dropped,
        unmapped_constraints=ir.unmapped_constraints,
    )


@router.get(
    "/llm_parse/fields",
    response_model=List[FilterFieldInfo],
    summary="List the filters this deployment supports",
    description=(
        "Returns the configured filter field catalog (from search_fields.yaml): "
        "name, value type, valid operators, description, and examples. Lets the UI show users "
        "which filters are available and let them add filters without typing a query. Static "
        "metadata — works regardless of whether the LLM extractor is enabled."
    ),
)
async def list_filter_fields() -> List[FilterFieldInfo]:
    return [
        FilterFieldInfo(
            name=f.name,
            value_type=f.value_type,
            operators=[op.value for op in f.operators],
            description=" ".join(f.description.split()),
            examples=list(f.examples),
            params=list(f.param_keys),
            comma_join=any(k in COMMA_JOIN_PARAMS for k in f.param_keys),
            kind=f.kind,
            property=f.property,
        )
        for f in REGISTRY.values()
    ]
