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

"""Persistent (Redis) cache of RRF-fused result orderings, for pagination.

Multi-leg queries are fused in this process, so OpenSearch cannot page them:
without this, every page re-runs every leg (kNN included) and re-fuses the whole
window to slice out 32 documents. Storing the fused order under a ranking id
carried in the cursor lets pages 2..N skip the legs and fetch only what they need.

**A cache, not a session.** The cursor can recompute the ranking from scratch, so
a miss, an expiry or a Redis outage falls back to re-running the legs: Redis is
required for latency, never for correctness, and no "session expired" error ever
reaches a client. The price is that a recompute is a fresh snapshot, so a page
boundary may drift if the index moved — same as the stateless path.

Only the *order* is stored (ids + scores + each hit's top matched view, <= 10000
entries, ~2 MB worst case); bodies are re-fetched by id, so the cache cannot
serve stale `_source`. Shares DB 0 with the other deepsearch-api caches,
separated by key prefix, and bounds its own size via an app-level LRU rather
than Redis eviction, which would drop the indexing pipeline's Streams.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Set

import orjson
from opentelemetry import trace
from prometheus_client import Counter
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Spans live in this module rather than at the call sites so the Redis round-trips
# are attributed wherever the cache is used. `redis.asyncio` is not auto-instrumented
# (no RedisInstrumentor is wired in tracing.py), so without these the lookup and the
# write — both awaited on the request's critical path — are invisible time in a trace.
tracer = trace.get_tracer(__name__)

# Ceiling on detached writes in flight (see RankingCache.set_soon). Each pins its
# payload — up to ~2 MB at the largest window — so this bounds the memory a
# slow or unreachable Redis can tie up: ~64 MB worst case, against a 1 GiB pod.
MAX_PENDING_WRITES = 32
# How long shutdown waits for those writes before abandoning them.
PENDING_WRITE_DRAIN_SECONDS = 2.0

# Lazily created once per process so the module can be imported repeatedly
# (tests) without a duplicate prometheus registration.
_RANKING_CACHE_EVENTS: Optional[Counter] = None


def _ranking_cache_events() -> Counter:
    global _RANKING_CACHE_EVENTS
    if _RANKING_CACHE_EVENTS is None:
        _RANKING_CACHE_EVENTS = Counter(
            "search_ranking_cache_events_total",
            "RRF ranking cache outcomes. `hit` served a page without re-running the query legs; "
            "`miss` fell back to recomputing the fused ranking (correct, just slower); "
            "`write_dropped` shed a detached write because too many were already in flight, "
            "which costs the next page a recompute.",
            ["outcome"],
        )
    return _RANKING_CACHE_EVENTS


class RankingCacheSettings(BaseSettings):
    """Config for the paginated-ranking cache.

    Connection reuses the repo-wide ``REDIS_URL``; cache-specific knobs use the
    ``USDSEARCH_SEARCH_RANKING_CACHE_`` prefix.
    """

    # Reads the bare ``REDIS_URL`` env var (a field-level alias overrides the
    # env_prefix in pydantic-settings). Empty/unset -> cache stays disabled.
    redis_url: Optional[str] = Field(default=None, alias="redis_url")
    enabled: bool = Field(
        default=True,
        description="Master switch. Even when True the cache only activates if redis_url is set.",
    )
    ttl_seconds: int = Field(
        default=900,
        description="Per-ranking TTL (default 15 min). Unlike the verdict cache this MUST expire: a "
        "ranking is a snapshot of a mutating index, so an old one silently serves stale ordering. "
        "Expiry is safe — the cursor can always recompute.",
    )
    max_entries: int = Field(
        default=2_000,
        description="Approximate upper bound on cached rankings (~4 GB at the ~2 MB worst case, far "
        "less in practice since most windows are ~1000 docs). 0 disables the cap. Enforced app-side "
        "via a ZSET LRU index.",
    )
    namespace: str = Field(
        default="usdsearch:rrfpage:v1",
        description="Key prefix for all cache keys + the LRU index. The trailing version segment lets "
        "the key scheme be bumped without a flush.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_search_ranking_cache_", populate_by_name=True, protected_namespaces=()
    )

    @property
    def is_active(self) -> bool:
        """The cache should be wired only if enabled AND a connection URL is set."""
        return self.enabled and bool(self.redis_url)


class RankingCache:
    """Async store for fused result orderings, with an app-level LRU size cap.

    Keys:
      - value:  ``{namespace}:r:{ranking_id}`` -> JSON {"qf": ..., "order": [[doc_id, score], ...]}
      - index:  ``{namespace}:lru``            -> ZSET(member=ranking_id, score=last-access epoch)
    """

    def __init__(self, settings: RankingCacheSettings) -> None:
        if not settings.redis_url:
            raise ValueError("RankingCache requires a redis_url")
        self._settings = settings
        self._client: Redis = Redis.from_url(settings.redis_url)
        self._ns = settings.namespace
        self._lru_key = f"{self._ns}:lru"
        self._ttl = settings.ttl_seconds
        self._max_entries = settings.max_entries
        # In-flight background writes (see set_soon). Held in a strong set because
        # asyncio keeps only a weak reference to a running task: without this the
        # GC can collect a write mid-flight, which fails silently and rarely.
        self._pending_writes: Set["asyncio.Task[None]"] = set()
        logger.info(
            "RankingCache initialized: namespace=%s ttl=%s max_entries=%s",
            self._ns,
            self._ttl,
            self._max_entries,
        )

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    def _value_key(self, ranking_id: str) -> str:
        return f"{self._ns}:r:{ranking_id}"

    async def is_ready(self) -> bool:
        try:
            await self._client.ping()
            return True
        except RedisError as exc:
            logger.warning("Ranking cache (Redis) unavailable: %s", exc)
            return False

    def set_soon(self, ranking_id: str, query_fingerprint: str, order: List[Dict[str, Any]]) -> None:
        """Schedule ``set`` without blocking the caller.

        The write exists for a page that may never be requested, so making the
        current response wait on it buys nothing — and when Redis is on another
        node, that wait is a network round trip (SET+ZADD+ZCARD pipelined, plus
        ZPOPMIN+DELETE when the write evicts) on the critical path of every first
        page. Detaching it takes the ranking cache off the response path entirely
        while leaving the cache itself unchanged.

        The cursor is handed to the client before the write lands, so a very fast
        "Load more" can miss a ranking that is still being written. That is the
        cache's ordinary miss path — the page recomputes — and the window is one
        round trip against a human click.

        Shedding rather than queueing past ``MAX_PENDING_WRITES``: each pending
        write pins its payload (up to ~2 MB) in memory, and an unbounded spawn
        under load trades a latency problem for a memory one. A dropped write
        costs the next page a recompute, which is what a cache miss already costs.
        """
        if len(self._pending_writes) >= MAX_PENDING_WRITES:
            _ranking_cache_events().labels(outcome="write_dropped").inc()
            logger.warning(
                "Ranking cache has %d writes in flight; dropping this one (page will recompute).",
                len(self._pending_writes),
            )
            return

        # create_task copies the current context, so the write's span nests under
        # the request that scheduled it even though it outlives the response.
        task = asyncio.create_task(self.set(ranking_id, query_fingerprint, order))
        self._pending_writes.add(task)
        task.add_done_callback(self._pending_writes.discard)

    async def flush_pending(self, timeout: float = PENDING_WRITE_DRAIN_SECONDS) -> int:
        """Wait for detached writes to land. Returns how many were abandoned.

        Bounded, because the caller (shutdown) must not hang on an unreachable
        Redis. Also the seam tests use to make a detached write observable
        without sleeping on it.
        """
        if not self._pending_writes:
            return 0
        _, pending = await asyncio.wait(set(self._pending_writes), timeout=timeout)
        for task in pending:
            task.cancel()
        return len(pending)

    async def aclose(self) -> None:
        # Give detached writes a moment to land before the client goes away;
        # abandoning them silently would lose rankings a live cursor points at.
        abandoned = await self.flush_pending()
        if abandoned:
            logger.warning("Ranking cache abandoned %d in-flight write(s) at shutdown.", abandoned)
        try:
            await self._client.aclose()
        except RedisError:
            pass

    async def get(self, ranking_id: str, query_fingerprint: str) -> Optional[List[Dict[str, Any]]]:
        """Return the cached fused order, or None on miss.

        ``query_fingerprint`` is re-checked against the stored one. The ranking id
        is unguessable, but this closes the residual case of an id being reused
        across key-scheme changes — a mismatch is treated as a miss, never as an
        error, so the caller just recomputes.
        """
        vkey = self._value_key(ranking_id)
        with tracer.start_as_current_span("ranking_cache.get") as span:
            span.set_attribute("cache.namespace", self._ns)
            span.set_attribute("cache.ranking_id", ranking_id)
            try:
                raw = await self._client.get(vkey)
                if raw is None:
                    # Value gone (never set, or TTL-expired) — drop any dangling index entry.
                    await self._client.zrem(self._lru_key, ranking_id)
                    _ranking_cache_events().labels(outcome="miss").inc()
                    span.set_attribute("cache.outcome", "miss")
                    return None

                payload = orjson.loads(raw)
                if payload.get("qf") != query_fingerprint:
                    logger.warning("Ranking cache fingerprint mismatch for %s; recomputing.", ranking_id)
                    _ranking_cache_events().labels(outcome="miss").inc()
                    span.set_attribute("cache.outcome", "fingerprint_mismatch")
                    return None

                if self._max_entries:
                    await self._client.zadd(self._lru_key, {ranking_id: time.time()})
                _ranking_cache_events().labels(outcome="hit").inc()
                order = payload.get("order") or []
                span.set_attribute("cache.outcome", "hit")
                span.set_attribute("cache.order_length", len(order))
                return order
            except RedisError as exc:
                logger.warning("Ranking cache get failed (recomputing): %s", exc)
                _ranking_cache_events().labels(outcome="miss").inc()
                # The caller silently recomputes, so the span attribute is the only
                # in-trace signal that this page paid for a Redis failure.
                span.set_attribute("cache.outcome", "error")
                span.set_attribute("cache.error", type(exc).__name__)
                return None
            except (orjson.JSONDecodeError, ValueError, TypeError) as exc:
                logger.warning("Ranking cache holds unparseable value for %s: %s", vkey, exc)
                _ranking_cache_events().labels(outcome="miss").inc()
                span.set_attribute("cache.outcome", "unparseable")
                span.set_attribute("cache.error", type(exc).__name__)
                return None

    async def set(self, ranking_id: str, query_fingerprint: str, order: List[Dict[str, Any]]) -> None:
        """Store a fused order and enforce the size cap.

        Best-effort: a Redis error *or* an unserializable order is swallowed. A
        failed write only costs the next page a recompute — the cache is an
        optimisation, so nothing here may take a search down with it. That is not
        hypothetical: ``orjson`` refuses non-str dict keys, and the fused order
        carries per-leg rank maps whose keys come from leg names.
        """
        vkey = self._value_key(ranking_id)
        with tracer.start_as_current_span("ranking_cache.set") as span:
            span.set_attribute("cache.namespace", self._ns)
            span.set_attribute("cache.ranking_id", ranking_id)
            span.set_attribute("cache.order_length", len(order))
            try:
                payload = orjson.dumps({"qf": query_fingerprint, "order": order})
                span.set_attribute("cache.payload_bytes", len(payload))
                if self._max_entries <= 0:
                    await self._client.set(vkey, payload, ex=self._ttl)
                    span.set_attribute("cache.outcome", "stored")
                    return

                now = time.time()
                pipe = self._client.pipeline(transaction=True)
                pipe.set(vkey, payload, ex=self._ttl)
                pipe.zadd(self._lru_key, {ranking_id: now})
                pipe.zcard(self._lru_key)
                results = await pipe.execute()
                count = results[-1]
                # Index size as observed by this write, i.e. *before* the eviction
                # below. Above max_entries here is normal, not a leak.
                span.set_attribute("cache.entry_count", count)

                overflow = count - self._max_entries
                if overflow > 0:
                    await self._evict(overflow)
                span.set_attribute("cache.outcome", "stored")
            except RedisError as exc:
                logger.warning("Ranking cache set failed (ranking not cached): %s", exc)
                span.set_attribute("cache.outcome", "error")
                span.set_attribute("cache.error", type(exc).__name__)
            except TypeError as exc:
                # Serialization, not Redis. Logged louder because it means the order
                # we built has a shape this cache cannot store — a bug to fix, not a
                # transient outage — but still swallowed, since a search must not
                # fail over its own cache.
                logger.error("Ranking cache could not serialize the fused order (ranking not cached): %s", exc)
                span.set_attribute("cache.outcome", "unserializable")
                span.set_attribute("cache.error", type(exc).__name__)

    async def _evict(self, overflow: int) -> None:
        """Drop the ``overflow`` least-recently-used rankings (values + index members).

        Spanned separately from ``set`` (it nests under it) because eviction is the
        one unbounded part of a write: its cost scales with the overflow, not with
        the ranking being stored.
        """
        with tracer.start_as_current_span("ranking_cache.evict") as span:
            span.set_attribute("cache.namespace", self._ns)
            span.set_attribute("cache.evict_requested", overflow)
            try:
                evicted = await self._client.zpopmin(self._lru_key, overflow)
                if not evicted:
                    span.set_attribute("cache.evicted", 0)
                    return
                keys = [self._value_key(m.decode() if isinstance(m, bytes) else m) for m, _score in evicted]
                if keys:
                    await self._client.delete(*keys)
                span.set_attribute("cache.evicted", len(keys))
            except RedisError as exc:
                logger.warning("Ranking cache eviction failed: %s", exc)
                span.set_attribute("cache.error", type(exc).__name__)
