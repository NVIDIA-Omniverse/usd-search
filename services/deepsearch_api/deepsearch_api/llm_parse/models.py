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

"""The structured intermediate representation (IR) the LLM fills in.

``SearchIR`` is the JSON-schema-constrained output. ``field`` and ``operator``
are enums so the model cannot emit unknown values; ``extra="forbid"`` makes the
emitted JSON schema set ``additionalProperties: false``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from .fields import IRFieldName, Operator


class IRFilter(BaseModel):
    """A single structured filter: which field, which operator, what value."""

    model_config = ConfigDict(extra="forbid")

    field: IRFieldName = Field(description="The field to filter on (one of the allowed enum values).")
    operator: Operator = Field(description="Comparison operator. Must be valid for the chosen field.")
    value: Union[str, float, bool, List[str]] = Field(
        description="The value to compare against. Use a list only for `in` operators."
    )


class UnmappedConstraint(BaseModel):
    """A constraint the user clearly expressed that maps to no catalog field.

    The escape hatch that keeps the parse honest: a clause like "Isaac version
    between 5 and 6" is neither a descriptive noun (so it does not belong in
    ``semantic_query``) nor a known filter (so it cannot become an ``IRFilter``).
    Routing it here makes the drop explicit — the client can tell the user the
    constraint was understood but not enforced — instead of it silently vanishing
    or polluting the semantic query."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The verbatim fragment of the user's query expressing this constraint.")
    note: str = Field(description="Plain-English explanation of what was understood and why no catalog field fits.")


class SearchIR(BaseModel):
    """Structured interpretation of a free-text search query."""

    model_config = ConfigDict(extra="forbid")

    semantic_query: str = Field(
        description=(
            "Descriptive nouns/phrase for semantic + keyword search (e.g. 'warehouse'). "
            "Put ONLY descriptive nouns/adjectives here — not structured constraints. "
            "May be empty if the query is purely a filter."
        )
    )
    filters: List[IRFilter] = Field(
        default_factory=list,
        description="Structured filters extracted from the query. Empty if the query maps to no known filter.",
    )
    unmapped_constraints: List[UnmappedConstraint] = Field(
        default_factory=list,
        description=(
            "Constraints the user clearly expressed that match NO catalog field. "
            "Never drop such a clause and never put it in semantic_query — record it here "
            "so the client can report it as understood-but-not-enforced."
        ),
    )
    limit: Optional[int] = Field(
        default=None,
        ge=1,
        le=10000,
        description="Maximum number of results, only if the user explicitly asked for a count.",
    )


class DroppedFilterReason(str, Enum):
    """Why the mapper could not apply an extracted filter."""

    UNKNOWN_FIELD = "unknown_field"  # field not in this deployment's catalog
    UNSUPPORTED_OPERATOR = "unsupported_operator"  # operator not valid for that field
    INVALID_VALUE = "invalid_value"  # value rejected/unmappable (malformed, wrong shape)


class DroppedFilter(BaseModel):
    """A filter the LLM extracted that the mapper could not apply, with the
    reason. Lets the client tell the user a constraint was understood but not
    enforced (and why), instead of silently ignoring it."""

    filter: IRFilter = Field(description="The extracted filter that was not applied.")
    reason: DroppedFilterReason = Field(description="Machine-readable reason the filter was dropped.")
    message: str = Field(description="Human-readable explanation suitable for surfacing in the UI.")


class ParsedQuery(BaseModel):
    """Outcome of a server-side LLM query parse, echoed to the client."""

    interpreted_query: SearchIR = Field(description="Structured interpretation of the query.")
    search_params: Dict[str, Any] = Field(
        description="Mapped DeepSearchSearchRequestV2 fields that were merged into the search request."
    )
    dropped_filters: List[DroppedFilter] = Field(
        default_factory=list,
        description=(
            "Filters that were extracted but could not be applied (unsupported operator, "
            "unknown field, or invalid value). Empty when every extracted filter was applied; "
            "its length is the dropped count. interpreted_query reflects only applied filters."
        ),
    )
    unmapped_constraints: List[UnmappedConstraint] = Field(
        default_factory=list,
        description=(
            "Constraints the user expressed that match no catalog field, so they could not "
            "become a filter and were not searched on. Surfaced (verbatim, with a note) so the "
            "client can tell the user the constraint was understood but not enforced. Mirrors "
            "interpreted_query.unmapped_constraints."
        ),
    )
