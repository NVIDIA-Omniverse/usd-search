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

"""Deterministic, pure mapper: ``SearchIR`` -> DeepSearchSearchRequestV2 params.

No LLM here. Filters referencing unknown fields, illegal operators, or values a
mapper rejects are reported as ``dropped_filters`` (defense-in-depth on top of
the schema enums) so a partially-misunderstood query still produces a valid
search. The IR's ``unmapped_constraints`` (constraints matching no catalog field)
never reach this mapper — they carry no field/operator to map and are surfaced
straight to the client, so they never produce search params.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from .fields import REGISTRY
from .models import DroppedFilter, DroppedFilterReason, IRFilter, SearchIR

logger = logging.getLogger(__name__)

# Params whose values accumulate (comma-joined) when produced more than once.
# These mirror the comma-OR/AND semantics documented on the request model.
COMMA_JOIN_PARAMS = {
    "file_extension_include",
    "file_extension_exclude",
    "file_name",
    "filter_by_properties",
    "filter_by_properties_include_any",
    "exclude_filter_by_properties",
    "filter_by_properties_numeric",
    "filter_by_tags",
}


def _merge(params: Dict[str, Any], fragment: Dict[str, str]) -> None:
    for key, value in fragment.items():
        if key in params and key in COMMA_JOIN_PARAMS:
            params[key] = f"{params[key]},{value}"
        else:
            params[key] = value


def _operator_value(operator: Any) -> str:
    return operator.value if hasattr(operator, "value") else str(operator)


def map_ir(ir: SearchIR) -> Tuple[Dict[str, Any], List[IRFilter], List[DroppedFilter]]:
    """Translate a validated IR into request params, applied filters, and drops.

    Returns ``(params, applied_filters, dropped_filters)``. ``applied_filters``
    holds only the filters that actually contributed to ``params``;
    ``dropped_filters`` holds the rest, each tagged with why it could not be
    applied (unknown field, unsupported operator, or invalid value).

    Callers that echo the interpreted query back to the client should report
    ``applied_filters`` (not ``ir.filters``) so the response never advertises a
    filter the search silently dropped, and may surface ``dropped_filters`` so
    the user learns a constraint was understood but not enforced.
    """
    params: Dict[str, Any] = {}
    applied: List[IRFilter] = []
    dropped: List[DroppedFilter] = []

    def _drop(flt: IRFilter, reason: DroppedFilterReason, message: str) -> None:
        logger.debug("Dropping IR filter (%s): %s", reason.value, message)
        dropped.append(DroppedFilter(filter=flt, reason=reason, message=message))

    if ir.semantic_query and ir.semantic_query.strip():
        params["hybrid_text_query"] = ir.semantic_query.strip()

    for flt in ir.filters:
        field_name = flt.field.value if hasattr(flt.field, "value") else str(flt.field)
        op = _operator_value(flt.operator)
        field_def = REGISTRY.get(field_name)
        if field_def is None:
            _drop(flt, DroppedFilterReason.UNKNOWN_FIELD, f"Field '{field_name}' is not available on this deployment.")
            continue
        if flt.operator not in field_def.operators:
            _drop(
                flt,
                DroppedFilterReason.UNSUPPORTED_OPERATOR,
                f"Field '{field_name}' does not support the '{op}' operator.",
            )
            continue
        try:
            fragment = field_def.to_params(flt.operator, flt.value)
        except (ValueError, TypeError) as exc:
            _drop(
                flt,
                DroppedFilterReason.INVALID_VALUE,
                f"Value {flt.value!r} could not be applied to '{field_name}': {exc}",
            )
            continue
        if fragment:
            _merge(params, fragment)
            applied.append(flt)
        else:
            _drop(
                flt,
                DroppedFilterReason.INVALID_VALUE,
                f"Value {flt.value!r} is not a valid '{field_name}' filter and was ignored.",
            )

    if ir.limit:
        params["limit"] = ir.limit

    return params, applied, dropped


def ir_to_request_params(ir: SearchIR) -> Dict[str, Any]:
    """Translate a validated IR into a dict of DeepSearchSearchRequestV2 fields."""
    params, _, _ = map_ir(ir)
    return params
