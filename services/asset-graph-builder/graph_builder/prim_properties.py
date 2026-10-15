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

"""Small, USD-runtime-independent helpers for the prim graph produced by usd_deps.

Kept free of ``omni``/``pxr`` imports so the pure dict manipulation can be unit
tested without a Kit runtime.
"""

import math
from typing import Dict, List, MutableMapping, Tuple

# Fields the Asset Graph Service requires on every prim (see PrimCreateModel in
# asset_graph_service.db.models). A prim that stage.Traverse() actually visited
# always carries these; a bare entry auto-vivified by merge_prim_properties does
# not.
REQUIRED_PRIM_FIELDS = ("usd_path", "prim_type", "bbox_max", "bbox_min", "bbox_midpoint")

# Largest finite 32-bit float; used as a +/- "infinity" sentinel for bounding boxes
# that cannot be represented as real finite coordinates. Matches the OpenSearch float
# ceiling the AGS plugin clamps to.
GF_FLT_MAX = 3.4028234663852886e38


def sanitize_bbox(
    bbox_max: List[float],
    bbox_min: List[float],
    bbox_midpoint: List[float],
    is_empty: bool,
) -> Tuple[List[float], List[float], List[float]]:
    """Return usable (max, min, midpoint) bbox coordinate lists, or +/- FLT_MAX sentinels.

    A bounding box is unusable when its range is empty (incomplete prims) *or* when any
    coordinate is non-finite. Some prims (e.g. Volumes with unbounded field extents) yield
    a non-empty range whose coordinates are inf/NaN; the graph is later serialized with
    orjson, which encodes those as JSON ``null``. The Asset Graph Service then rejects the
    write with a 422 (``float_type`` "Input should be a valid number") on
    ``bbox_max``/``bbox_min``/``bbox_midpoint``, so both cases fall back to the same
    sentinels here.

    Kept ``pxr``-free (takes plain coordinate lists plus a pre-computed emptiness flag) so
    it can be unit tested without a Kit runtime.
    """
    if is_empty or not all(math.isfinite(v) for v in (*bbox_max, *bbox_min, *bbox_midpoint)):
        return (
            [GF_FLT_MAX, GF_FLT_MAX, GF_FLT_MAX],
            [-GF_FLT_MAX, -GF_FLT_MAX, -GF_FLT_MAX],
            [0.0, 0.0, 0.0],
        )
    return bbox_max, bbox_min, bbox_midpoint


def merge_prim_properties(
    prims: MutableMapping[str, dict],
    prim_path: str,
    new_properties: Dict[str, str],
) -> None:
    """Merge ``new_properties`` into ``prims[prim_path]["properties"]``.

    ``prims`` is typically a ``defaultdict(dict)`` keyed by prim path. A prim
    that ``stage.Traverse()`` visited always carries a ``"properties"`` dict, but
    the stage's default prim may not have been visited at all (e.g. it is an
    ``over``, inactive, or abstract). Accessing such a path auto-vivifies an
    empty dict with no ``"properties"`` key, so a plain ``["properties"]`` access
    would raise ``KeyError``. ``setdefault`` keeps the merge robust in either
    case.
    """
    prims[prim_path].setdefault("properties", {}).update(new_properties)


def drop_incomplete_prims(prims: MutableMapping[str, dict]) -> List[str]:
    """Remove, in place, any prim entry missing a field the Asset Graph Service requires.

    ``stage.Traverse()`` skips ``over``/inactive/abstract prims, so a default (or
    other) prim that was never visited can still surface as a bare
    ``{"properties": {...}}`` entry (see ``merge_prim_properties``). Posting such
    an entry makes AGS reject the whole graph with a 422. These belong to the
    main asset that references/payloads this layer, so dropping them here is
    safe.

    The check is on key *presence*, not value: a traversed non-geometry prim
    (Scope, Material, physics joint, ...) legitimately has sentinel bbox values
    but still carries every key, so it is never dropped — only the never-traversed
    stub is. Returns the dropped prim paths so the caller can log them.
    """
    dropped = [path for path, data in prims.items() if any(field not in data for field in REQUIRED_PRIM_FIELDS)]
    for path in dropped:
        del prims[path]
    return dropped
