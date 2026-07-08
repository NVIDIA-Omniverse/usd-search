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

"""Optional corpus-property grounding for the LLM query parser.

The generic ``usd_property`` IR field is a free-form ``key=value`` escape hatch.
Without help the LLM guesses property keys, and the mapper deliberately drops
value-less guesses (see ``fields._build_property_keyvalue``) — so real, indexed
properties stay unreachable from natural language. This module renders a
compact, token-bounded block listing the property keys (and, for enumerable
ones, their common values) that **actually exist** in a deployment's corpus, so
the extractor can ground ``usd_property`` filters on reality.

The input is the ``usd_property_catalog.yaml`` produced by the
``/usd-property-catalog`` skill from ``GET /search/stats/usd_properties``. The
deployment opts in by setting ``USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH``
(see ``LLMParseSettings.property_catalog_filepath``).

Everything here is defensive: an unset / missing / unreadable / malformed
catalog yields ``""`` so grounding silently no-ops and never breaks the
extractor.
"""

from __future__ import annotations

import logging
from typing import List

import yaml

logger = logging.getLogger(__name__)

_HEADER = (
    "The following USD property keys exist in THIS deployment's corpus. When a "
    "constraint maps to the generic `usd_property` field, use one of these EXACT "
    "keys (and, where listed, one of these exact values) — never invent a key or "
    "value that is not shown here:"
)


def build_property_grounding(
    filepath: str,
    max_keys: int = 60,
    max_values_per_key: int = 8,
    value_cardinality_cap: int = 20,
) -> str:
    """Render the property-catalog YAML at ``filepath`` into a grounding block.

    Returns the full block (header + bullet lines) or ``""`` when grounding is
    disabled (no filepath) or the catalog is missing / unreadable / malformed /
    empty. ``max_keys`` caps the number of properties listed (taken in the
    catalog's order, which is ``asset_count`` desc); values are only shown for
    properties whose ``cardinality`` is at most ``value_cardinality_cap`` (i.e.
    genuinely enumerable), and then at most ``max_values_per_key`` of them.
    """
    if not filepath:
        return ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("property grounding disabled: could not read %s (%s)", filepath, exc)
        return ""

    props = (doc or {}).get("properties") if isinstance(doc, dict) else None
    if not isinstance(props, list) or not props:
        logger.warning("property grounding disabled: %s has no 'properties' list", filepath)
        return ""

    lines: List[str] = []
    for p in props:
        if not isinstance(p, dict):
            continue
        key = p.get("key")
        if not key:
            continue
        ptype = p.get("type", "string")
        cardinality = p.get("cardinality")
        top_values = p.get("top_values") or []
        if ptype == "number":
            lines.append(f"- {key} (number)")
        elif isinstance(cardinality, int) and cardinality <= value_cardinality_cap and top_values:
            vals = [str(v.get("value")) for v in top_values[:max_values_per_key] if isinstance(v, dict)]
            vals = [v for v in vals if v]
            lines.append(f"- {key} = " + " | ".join(vals) if vals else f"- {key}")
        else:
            lines.append(f"- {key} (free-form text)")
        if len(lines) >= max_keys:
            break

    if not lines:
        return ""
    return _HEADER + "\n" + "\n".join(lines)
