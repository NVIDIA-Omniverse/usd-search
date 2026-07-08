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

"""Single source of truth for LLM query parsing — loaded from YAML.

``REGISTRY`` defines every IR field the LLM may emit (value type, operators,
grounding text) and the deterministic ``to_params`` mapping onto real
``DeepSearchSearchRequestV2`` fields. The field set is **configuration**, not
code: it is read from ``search_fields.yaml`` (override path via
``USDSEARCH_LLM_PARSING_FIELDS_FILEPATH``), so a deployment can add/remove fields
or re-point USD property keys without touching this module, the prompt, the IR
schema, or the frontend.

Each YAML field's ``map.kind`` selects one of the builders below; the
``IRFieldName`` enum is generated from the loaded registry so the schema, the
prompt catalog, and the mapper can never drift apart.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union

import yaml

ValueType = Union[str, float, bool, List[str]]


class Operator(str, Enum):
    """Comparison operators an IR filter may use. The set is the union across
    all fields; each field constrains which subset is valid (see ``IRField``)."""

    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"
    IN = "in"
    EXISTS = "exists"


_OPERATOR_BY_NAME = {op.value: op for op in Operator}

_NUMERIC_OP = {Operator.GT: ">", Operator.GTE: ">=", Operator.LT: "<", Operator.LTE: "<=", Operator.EQ: "="}

# `filter_by_properties` / `filter_by_tags` are exact key=value / value matches:
# a comparison operator smuggled into the value (e.g. "version>=6.0") can never
# match, so we drop the fragment rather than emit a guaranteed-empty filter.
# Numeric comparisons have a dedicated path (filter_by_properties_numeric).
_COMPARISON_IN_VALUE = re.compile(r"[<>]")


# --- mapping primitives -----------------------------------------------------
# Each builder returns a ``to_params(operator, value) -> {request_param: value}``
# closure. The mapper merges fragments; comma-joinable params (see
# mapper.COMMA_JOIN_PARAMS) are concatenated when produced more than once.


def _norm_extension(value: str) -> str:
    return value.strip().lstrip(".")


def _as_list(value: ValueType) -> List[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    return [p for p in str(value).split(",")]


def _is_true(value: ValueType) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1", "enabled", "on"}


def _numeric_fragment(prop: str, operator: Operator, value: ValueType) -> Dict[str, str]:
    sym = _NUMERIC_OP.get(operator)
    if sym is None:
        return {}
    try:
        num = float(value)
    except (TypeError, ValueError):
        return {}
    num_str = str(int(num)) if num == int(num) else repr(num)
    return {"filter_by_properties_numeric": f"{prop}{sym}{num_str}"}


def _build_file_extension(_map) -> Callable:
    def fn(operator, value):
        exts = [_norm_extension(v) for v in _as_list(value) if _norm_extension(v)]
        return {"file_extension_include": ",".join(exts)} if exts else {}

    return fn


def _build_name(_map) -> Callable:
    def fn(operator, value):
        v = str(value).strip()
        if not v:
            return {}
        return {"file_name": f"*{v}*" if operator == Operator.CONTAINS else v}

    return fn


def _build_path(_map) -> Callable:
    def fn(operator, value):
        v = str(value).strip()
        if not v:
            return {}
        return {"search_path": f"*{v}*" if operator == Operator.CONTAINS else v}

    return fn


def _build_date_range(m) -> Callable:
    after_param, before_param = m["after_param"], m["before_param"]

    def fn(operator, value):
        v = str(value).strip()
        # The request model requires ISO YYYY-MM-DD (or YYYYMMDD). Drop anything
        # else so a malformed value (e.g. "2024") is ignored, not a 422.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}", v):
            return {}
        return {after_param: v} if operator in (Operator.GT, Operator.GTE) else {before_param: v}

    return fn


def _build_size_range(_map) -> Callable:
    def fn(operator, value):
        # integer + unit, e.g. "5MB"; the request model enforces ^\d+[KMGT]B$.
        v = str(value).strip().upper().replace(" ", "")
        # Drop malformed sizes (e.g. "10" with no unit) so they're ignored, not a 422.
        if not re.fullmatch(r"\d+[KMGT]B", v):
            return {}
        return {"file_size_greater_than": v} if operator in (Operator.GT, Operator.GTE) else {"file_size_less_than": v}

    return fn


def _build_passthrough(m) -> Callable:
    param = m["param"]

    def fn(operator, value):
        v = str(value).strip()
        return {param: v} if v else {}

    return fn


def _build_tag(_map) -> Callable:
    def fn(operator, value):
        v = str(value).strip()
        if not v or _COMPARISON_IN_VALUE.search(v):
            return {}
        # A bare free-text tag is usually a value/label, so match via the `=value` form.
        return {"filter_by_tags": v if "=" in v else f"={v}"}

    return fn


def _build_property_keyvalue(_map) -> Callable:
    def fn(operator, value):
        v = str(value).strip()
        # Require a real key=value with a NON-EMPTY value. The generic usd_property
        # field is free-form, so a value-less "key=" (or a bare token with no "=")
        # is almost always the LLM guessing a property key it isn't sure of.
        # Emitted as a hard existence filter it silently matches nothing — and on
        # corpora that don't carry that exact property it nukes the whole result
        # set to empty. Drop it so the query degrades to a plain semantic search
        # instead. Genuine existence filters go through dedicated catalog fields
        # (kind=property_exists), which use a resolved, real property key. Also drop
        # values carrying a comparison operator (those route through numeric fields).
        key, sep, val = v.partition("=")
        if not sep or not key.strip() or not val.strip() or _COMPARISON_IN_VALUE.search(v):
            return {}
        return {"filter_by_properties": v}

    return fn


def _build_property_exists(m) -> Callable:
    prop = _resolve_property(m)

    def fn(operator, value):
        if operator == Operator.EXISTS or _is_true(value):
            return {"filter_by_properties": f"{prop}="}
        return {"exclude_filter_by_properties": f"{prop}="}

    return fn


def _build_property_match(m) -> Callable:
    prop = _resolve_property(m)

    def fn(operator, value):
        v = str(value).strip()
        if not v:
            return {}
        frag = f"{prop}=~*{v}*" if operator == Operator.CONTAINS else f"{prop}={v}"
        return {"filter_by_properties": frag}

    return fn


def _build_property_numeric(m) -> Callable:
    prop = _resolve_property(m)

    def fn(operator, value):
        return _numeric_fragment(prop, operator, value)

    return fn


def _build_bbox(_map) -> Callable:
    def fn(operator, value):
        try:
            v = float(value)
        except (TypeError, ValueError):
            return {}
        if v <= 0:
            return {}
        if operator in (Operator.LT, Operator.LTE):
            return {"max_bbox_x": v, "max_bbox_y": v, "max_bbox_z": v}
        if operator in (Operator.GT, Operator.GTE):
            return {"min_bbox_x": v, "min_bbox_y": v, "min_bbox_z": v}
        return {}

    return fn


def _resolve_property(m: dict) -> str:
    """USD property key for a property_* field: env override (if set) else YAML."""
    prop = m.get("property")
    env = m.get("property_env")
    if env:
        prop = os.getenv(env, prop)
    if not prop:
        raise ValueError(f"property_* field is missing a 'property' key: {m}")
    return prop


_KIND_BUILDERS: Dict[str, Callable[[dict], Callable]] = {
    "file_extension": _build_file_extension,
    "name": _build_name,
    "path": _build_path,
    "date_range": _build_date_range,
    "size_range": _build_size_range,
    "passthrough": _build_passthrough,
    "tag": _build_tag,
    "property_keyvalue": _build_property_keyvalue,
    "property_exists": _build_property_exists,
    "property_match": _build_property_match,
    "property_numeric": _build_property_numeric,
    "bbox": _build_bbox,
}


# Request param key(s) each kind can emit — mirrors the builders above so the
# catalog (GET /llm_parse/fields) can advertise which DeepSearchSearchRequestV2
# fields a filter controls (and their merge semantics) without the client keeping
# a hardcoded copy. Keep in lockstep with _KIND_BUILDERS.
_KIND_PARAM_KEYS: Dict[str, Callable[[dict], List[str]]] = {
    "file_extension": lambda m: ["file_extension_include"],
    "name": lambda m: ["file_name"],
    "path": lambda m: ["search_path"],
    "date_range": lambda m: [m["after_param"], m["before_param"]],
    "size_range": lambda m: ["file_size_greater_than", "file_size_less_than"],
    "passthrough": lambda m: [m["param"]],
    "tag": lambda m: ["filter_by_tags"],
    "property_keyvalue": lambda m: ["filter_by_properties"],
    "property_exists": lambda m: ["filter_by_properties", "exclude_filter_by_properties"],
    "property_match": lambda m: ["filter_by_properties"],
    "property_numeric": lambda m: ["filter_by_properties_numeric"],
    "bbox": lambda m: ["min_bbox_x", "min_bbox_y", "min_bbox_z", "max_bbox_x", "max_bbox_y", "max_bbox_z"],
}


@dataclass(frozen=True)
class IRField:
    """One field the LLM may reference in a filter, plus how to map it."""

    name: str
    value_type: str  # "string" | "number" | "boolean" | "date" | "array"
    operators: Tuple[Operator, ...]
    description: str
    to_params: Callable[[Operator, ValueType], Dict[str, str]]
    param_keys: Tuple[str, ...] = ()
    examples: Tuple[str, ...] = ()
    enum_values: Optional[Tuple[str, ...]] = None
    # The map.kind builder behind this field, and (for property-backed kinds)
    # the resolved USD property key (env override applied) — exposed so the
    # Explorer rail can build the exact filter token the deployment uses.
    kind: str = ""
    property: Optional[str] = None


# Kinds backed by a single USD property key (have a resolvable map.property).
# Other kinds (bbox, size_range, date_range, property_keyvalue, …) legitimately
# carry no property and must expose ``property=None``.
_PROPERTY_KINDS = frozenset({"property_exists", "property_match", "property_numeric"})


def _build_field(spec: dict) -> IRField:
    m = spec["map"]
    kind = m["kind"]
    if kind not in _KIND_BUILDERS:
        raise ValueError(f"Unknown map kind '{kind}' for field '{spec['name']}'. Known: {sorted(_KIND_BUILDERS)}")
    operators = tuple(_OPERATOR_BY_NAME[o] for o in spec["operators"])
    return IRField(
        name=spec["name"],
        value_type=spec["type"],
        operators=operators,
        description=spec["description"],
        to_params=_KIND_BUILDERS[kind](m),
        param_keys=tuple(_KIND_PARAM_KEYS[kind](m)),
        examples=tuple(spec.get("examples", ())),
        kind=kind,
        property=(_resolve_property(m) if kind in _PROPERTY_KINDS else None),
    )


def _read_fields_yaml(filepath: str) -> List[dict]:
    with open(filepath, "r") as f:
        return yaml.safe_load(f)["fields"]


def load_field_registry(filepath: str) -> List[IRField]:
    """Load the ordered IR-field registry from a ``search_fields.yaml`` file."""
    return [_build_field(spec) for spec in _read_fields_yaml(filepath)]


# The field set is configuration: read from YAML at import (the IRFieldName enum
# below is needed at module load by models.py). Override the path via env.
FIELDS_FILEPATH = os.getenv(
    "USDSEARCH_LLM_PARSING_FIELDS_FILEPATH",
    os.path.join(os.path.dirname(os.path.realpath(__file__)), "search_fields.yaml"),
)

_SPECS: List[dict] = _read_fields_yaml(FIELDS_FILEPATH)
_REGISTRY_LIST: List[IRField] = [_build_field(spec) for spec in _SPECS]

REGISTRY: Dict[str, IRField] = {f.name: f for f in _REGISTRY_LIST}

# Resolved USD property keys per property-backed field (env override applied),
# derived from the loaded YAML — exposed for convenience / test pinning.
RESOLVED_PROPERTIES: Dict[str, str] = {
    s["name"]: _resolve_property(s["map"])
    for s in _SPECS
    if isinstance(s.get("map"), dict) and ("property" in s["map"] or "property_env" in s["map"])
}
POLYGON_COUNT_PROPERTY = RESOLVED_PROPERTIES.get("polygon_count", "")

# Generated from the registry — the LLM physically cannot emit an unknown field.
IRFieldName = Enum("IRFieldName", {name: name for name in REGISTRY}, type=str)


def build_field_catalog() -> str:
    """Render the registry as a grounding block for the extractor's system prompt."""
    lines: List[str] = []
    for f in _REGISTRY_LIST:
        ops = ", ".join(op.value for op in f.operators)
        line = f"- {f.name} ({f.value_type}; operators: {ops}): {f.description}"
        if f.examples:
            line += "\n    e.g. " + "; ".join(f.examples)
        lines.append(line)
    return "\n".join(lines)
