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

"""Version-range filtering over string-valued USD properties (``filter_by_properties_version``).

Versions are indexed as plain keyword strings (``"3.0.0"``), which OpenSearch can
only compare lexically. Instead, the property's distinct stored values are fetched
with one terms aggregation, compared here with version ordering, and the matching
ones become an exact-value filter — so existing indexes need no reindex.

The distinct values are cached per process for a short TTL, so only the first
query per property per window pays for the aggregation. Staleness is bounded by
that TTL: a newly indexed version starts matching once the entry expires.
"""

import asyncio
import operator
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from packaging.version import InvalidVersion, Version
from prometheus_client import Counter

_OPERATORS: Dict[str, Callable[[Version, Version], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "=": operator.eq,
}
# Two-character operators first, so ">=" is not read as ">" followed by "=2.0".
# Whitespace is stripped from the groups afterwards, not matched with ``\s*``: overlapping
# ``\s*`` and ``[^<>=]`` quantifiers backtrack cubically on input without an operator (ReDoS).
_CONDITION = re.compile(r"([^<>=]+)(>=|<=|>|<|=)([^<>=]+)")

_EVENTS: Optional[Counter] = None


def _events() -> Counter:
    # Created lazily so repeated imports (tests) do not register the metric twice.
    global _EVENTS
    if _EVENTS is None:
        _EVENTS = Counter(
            "search_property_values_cache_events_total",
            "Distinct-value lookups for filter_by_properties_version. `hit` was served from the cache, "
            "`miss` ran a terms aggregation, `coalesced` waited on a lookup already in flight.",
            ["outcome"],
        )
    return _EVENTS


@dataclass(frozen=True)
class VersionCondition:
    op: str
    version: Version

    def matches(self, version: Version) -> bool:
        return _OPERATORS[self.op](version, self.version)


@dataclass(frozen=True)
class PropertyValues:
    """Distinct stored values of one property; ``truncated`` if there were more than the lookup returns."""

    values: Tuple[str, ...]
    truncated: bool = False


def parse_version(value: str) -> Optional[Version]:
    """Parse a version, ignoring build metadata (``+...``) as SemVer precedence does; ``None`` if invalid."""
    try:
        return Version(Version(value.strip()).public)
    except InvalidVersion:
        return None


def parse_version_filters(filter_str: str) -> Dict[str, List[VersionCondition]]:
    """Parse ``key>=2.0.0,key<3`` into conditions grouped by property. Raises ``ValueError``."""
    conditions: Dict[str, List[VersionCondition]] = {}
    for token in filter_str.split(","):
        match = _CONDITION.fullmatch(token)
        name, op, raw_version = (group.strip() for group in match.groups()) if match else ("", "", "")
        if not name or not raw_version:
            raise ValueError(
                f"'{token}' is not a version condition. Expected <property><op><version>, "
                "e.g. 'profile_version>=2.0.0'. Supported operators: >, >=, <, <=, ="
            )
        version = parse_version(raw_version)
        if version is None:
            raise ValueError(f"'{raw_version}' is not a valid version for property '{name}'")
        conditions.setdefault(name, []).append(VersionCondition(op, version))
    return conditions


def matching_values(values: Iterable[str], conditions: List[VersionCondition]) -> List[str]:
    """Stored values satisfying every condition. Values that are not versions never match."""
    matched = []
    for value in values:
        version = parse_version(value)
        if version is not None and all(condition.matches(version) for condition in conditions):
            matched.append(value)
    return sorted(matched)


class PropertyValuesCache:
    """Per-process TTL + LRU cache of property values, with at most one lookup in flight per property.

    Failed lookups are not cached. ``ttl_seconds=0`` disables caching but still
    coalesces concurrent lookups.
    """

    def __init__(self, ttl_seconds: float, max_entries: int = 256, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: "OrderedDict[str, Tuple[float, PropertyValues]]" = OrderedDict()
        self._inflight: Dict[str, "asyncio.Task[PropertyValues]"] = {}

    async def get(self, key: str, load: Callable[[], Awaitable[PropertyValues]]) -> PropertyValues:
        entry = self._entries.get(key)
        if entry is not None and self._clock() < entry[0]:
            self._entries.move_to_end(key)
            _events().labels(outcome="hit").inc()
            return entry[1]

        task = self._inflight.get(key)
        if task is None:
            _events().labels(outcome="miss").inc()
            task = asyncio.create_task(self._load(key, load))
            self._inflight[key] = task
            task.add_done_callback(lambda done: self._finish(key, done))
        else:
            _events().labels(outcome="coalesced").inc()
        # Shielded: one caller disconnecting must not cancel the lookup others are awaiting.
        return await asyncio.shield(task)

    async def _load(self, key: str, load: Callable[[], Awaitable[PropertyValues]]) -> PropertyValues:
        result = await load()
        if self._ttl > 0:
            self._entries[key] = (self._clock() + self._ttl, result)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return result

    def _finish(self, key: str, task: "asyncio.Task[PropertyValues]") -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
        # Mark a failure as retrieved even if every awaiting caller was cancelled.
        if not task.cancelled():
            task.exception()
