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

"""Persistent (Redis) L2 cache for VLM validation verdicts.

Sits behind the in-process L1 LRU in ``SearchResultValidator``: verdicts survive
restarts and are shared across API replicas. Values are stored as small JSON
objects (not pickle) so they are human-inspectable and don't touch
``secure_pickle``'s approved-class allowlist.

The cache shares the default Redis DB (0) with the other services and is kept
separate purely by key prefix (``namespace``) — this is Redis-Cluster-safe,
since Cluster only has DB 0. Because that DB also backs the indexing pipeline's
Streams job queue, we must NOT rely on instance-level ``maxmemory``/``allkeys-lru``
eviction (it would drop pipeline data). Instead the cache enforces its own
bounded size with an app-level approximate-LRU cap scoped to its namespace: a
namespaced ZSET scored by last-access time, trimmed via ``ZPOPMIN`` on overflow.

Every Redis operation degrades gracefully: a ``RedisError`` (cache unreachable)
is logged and treated as a miss / no-op, so a cache outage never fails a
validation — it just falls through to the VLM call.
"""

import logging
import time
from typing import Optional

import orjson
from prometheus_client import Gauge
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Gauge of the verdict count in the persistent (Redis) cache. Lazily created once
# per process so the module can be imported repeatedly (tests) without a duplicate
# prometheus registration.
_CACHE_ENTRIES_GAUGE: Optional[Gauge] = None


def _cache_entries_gauge() -> Gauge:
    global _CACHE_ENTRIES_GAUGE
    if _CACHE_ENTRIES_GAUGE is None:
        _CACHE_ENTRIES_GAUGE = Gauge(
            "vlm_validation_cache_entries",
            "Approximate number of verdicts stored in the persistent (Redis L2) validation cache. "
            "Shared across replicas (one Redis) — every pod reports the same value, so aggregate "
            "with max(), not sum(). Only tracked when the LRU cap (max_entries) is enabled.",
        )
    return _CACHE_ENTRIES_GAUGE


class RedisValidationCacheSettings(BaseSettings):
    """Config for the persistent VLM-validation verdict cache.

    Connection reuses the repo-wide ``REDIS_URL`` (same instance the other
    services use); cache-specific knobs use the ``USDSEARCH_VISION_VALIDATION_CACHE_``
    prefix so they sit alongside the existing ``USDSEARCH_VISION_VALIDATION_``
    settings.
    """

    # Reads the bare ``REDIS_URL`` env var (a field-level alias overrides the
    # env_prefix in pydantic-settings). Empty/unset -> cache stays disabled.
    redis_url: Optional[str] = Field(default=None, alias="redis_url")
    enabled: bool = Field(
        default=True,
        description="Master switch. Even when True the cache only activates if redis_url is set.",
    )
    ttl_seconds: Optional[int] = Field(
        default=None,
        description="Per-entry TTL. Default None = no expiry (verdicts are deterministic for a "
        "fixed config; the config fingerprint in the key invalidates them on any change). "
        "Size is bounded by max_entries, not TTL.",
    )
    max_entries: int = Field(
        default=1_000_000,
        description="Approximate upper bound on cached verdicts (~2 GB at ~2 KB/entry). "
        "0 disables the cap (unbounded). Enforced app-side via a ZSET LRU index.",
    )
    namespace: str = Field(
        default="usdsearch:vlmval:v1",
        description="Key prefix for all cache keys + the LRU index. The trailing version "
        "segment lets the key scheme be bumped without a flush.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_validation_cache_", populate_by_name=True, protected_namespaces=()
    )

    @property
    def is_active(self) -> bool:
        """The cache should be wired only if enabled AND a connection URL is set."""
        return self.enabled and bool(self.redis_url)


class RedisValidationCache:
    """Async JSON verdict cache over Redis with an app-level LRU size cap.

    Keys:
      - value:  ``{namespace}:v:{digest}``  -> JSON verdict
      - index:  ``{namespace}:lru``         -> ZSET(member=digest, score=last-access epoch)
    """

    def __init__(self, settings: RedisValidationCacheSettings) -> None:
        if not settings.redis_url:
            raise ValueError("RedisValidationCache requires a redis_url")
        self._settings = settings
        # Connect via REDIS_URL as-is (shared default DB 0); the namespace prefix
        # isolates this cache's keyspace. Encode a DB in REDIS_URL if ever needed.
        self._client: Redis = Redis.from_url(settings.redis_url)
        self._ns = settings.namespace
        self._lru_key = f"{self._ns}:lru"
        self._ttl = settings.ttl_seconds
        self._max_entries = settings.max_entries
        logger.info(
            "RedisValidationCache initialized: namespace=%s ttl=%s max_entries=%s",
            self._ns,
            self._ttl,
            self._max_entries,
        )

    def _value_key(self, digest: str) -> str:
        return f"{self._ns}:v:{digest}"

    async def is_ready(self) -> bool:
        try:
            await self._client.ping()
            return True
        except RedisError as exc:
            logger.warning("Validation verdict cache (Redis) unavailable: %s", exc)
            return False

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except RedisError:
            pass

    async def get(self, digest: str) -> Optional[dict]:
        """Return the cached verdict dict for ``digest``, or None on miss/error.

        On a hit, refreshes the entry's LRU score. A stale index member (value
        expired via TTL but member lingers) is cleaned up and reported as a miss.
        """
        vkey = self._value_key(digest)
        try:
            raw = await self._client.get(vkey)
            if raw is None:
                # Value gone (never set, or TTL-expired) — drop any dangling index entry.
                await self._client.zrem(self._lru_key, digest)
                return None
            if self._max_entries:
                await self._client.zadd(self._lru_key, {digest: time.time()})
            return orjson.loads(raw)
        except RedisError as exc:
            logger.warning("Validation cache get failed (treating as miss): %s", exc)
            return None
        except (orjson.JSONDecodeError, ValueError, TypeError) as exc:
            # Corrupt/non-JSON payload — treat as a miss rather than fail the request.
            logger.warning("Validation cache holds unparseable value for %s: %s", vkey, exc)
            return None

    async def set(self, digest: str, value: dict) -> None:
        """Store ``value`` (a small JSON-able verdict dict) and enforce the size cap.

        Best-effort: any Redis error is swallowed so a cache-write failure never
        propagates into the validation response.
        """
        vkey = self._value_key(digest)
        try:
            payload = orjson.dumps(value)  # compact bytes; redis-py stores bytes directly
            if self._max_entries <= 0:
                # Unbounded: just store (with optional TTL), no LRU index bookkeeping.
                await self._client.set(vkey, payload, ex=self._ttl)
                return

            now = time.time()
            pipe = self._client.pipeline(transaction=True)
            pipe.set(vkey, payload, ex=self._ttl)
            pipe.zadd(self._lru_key, {digest: now})
            pipe.zcard(self._lru_key)
            results = await pipe.execute()
            count = results[-1]

            overflow = count - self._max_entries
            if overflow > 0:
                await self._evict(overflow)
            # Update the size gauge from the ZCARD we already have (no extra call);
            # after eviction the set is capped at max_entries.
            _cache_entries_gauge().set(min(count, self._max_entries))
        except RedisError as exc:
            logger.warning("Validation cache set failed (verdict not cached): %s", exc)

    async def _evict(self, overflow: int) -> None:
        """Drop the ``overflow`` least-recently-used entries (values + index members)."""
        try:
            evicted = await self._client.zpopmin(self._lru_key, overflow)
            if not evicted:
                return
            # zpopmin returns [(member, score), ...]; members may be bytes.
            keys = [self._value_key(m.decode() if isinstance(m, bytes) else m) for m, _score in evicted]
            if keys:
                await self._client.delete(*keys)
        except RedisError as exc:
            logger.warning("Validation cache eviction failed: %s", exc)
