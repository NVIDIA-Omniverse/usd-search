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

"""Persistent (Redis) cache for the ``asset_url -> image_id[]`` resolution.

Serving a thumbnail via ``GET /images?asset_url=...`` costs an OpenSearch
``search`` (resolve the asset's ``base_key`` to its ordered list of per-view
image ids) plus an OpenSearch ``get`` (fetch the image bytes). This cache
memoizes the first hop — the ``base_key -> [image_id, ...]`` mapping — so a
repeated thumbnail request for the same asset skips the ``search`` entirely and
goes straight to the byte ``get``.

Unlike the VLM validation verdict cache (``redis_cache.py``, deterministic ⇒ no
expiry, size bounded by an LRU cap), the resolution can go stale: re-indexing an
asset can change its thumbnails while keeping the same ``base_key``. So this
cache is TTL-bounded — entries expire after ``ttl_seconds`` and the mapping is
re-resolved from OpenSearch. Size is therefore bounded by the number of distinct
assets requested within one TTL window; each entry is tiny (a short list of
sha256 hex ids). The ACL check in the endpoint still runs on every request, so
caching never lets an unauthorized caller reach an asset's images.

Every Redis operation degrades gracefully: a ``RedisError`` (cache unreachable)
is logged and treated as a miss / no-op, so a cache outage never fails an image
request — it just falls through to the OpenSearch lookup.
"""

import hashlib
import logging
from typing import List, Optional

import orjson
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class RedisImageResolutionCacheSettings(BaseSettings):
    """Config for the persistent ``asset_url -> image_id[]`` resolution cache.

    Connection reuses the repo-wide ``REDIS_URL`` (same instance the other
    services use); cache-specific knobs use the
    ``USDSEARCH_IMAGE_RESOLUTION_CACHE_`` prefix.
    """

    # Reads the bare ``REDIS_URL`` env var (a field-level alias overrides the
    # env_prefix in pydantic-settings). Empty/unset -> cache stays disabled.
    redis_url: Optional[str] = Field(default=None, alias="redis_url")
    enabled: bool = Field(
        default=True,
        description="Master switch. Even when True the cache only activates if redis_url is set.",
    )
    ttl_seconds: int = Field(
        default=3600,
        description="Per-entry TTL. Bounds staleness (a re-indexed asset's thumbnails are picked up "
        "within this window) and bounds cache size (entries expire). Must be > 0.",
    )
    namespace: str = Field(
        default="usdsearch:imgresolve:v1",
        description="Key prefix for all cache keys. The trailing version segment lets the key scheme "
        "be bumped without a flush; keys are also namespaced by the OpenSearch index.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_image_resolution_cache_", populate_by_name=True, protected_namespaces=()
    )

    @property
    def is_active(self) -> bool:
        """The cache should be wired only if enabled AND a connection URL is set."""
        return self.enabled and bool(self.redis_url)


class RedisImageResolutionCache:
    """Async TTL cache of ``asset_url -> [image_id, ...]`` over Redis.

    Key: ``{namespace}:{sha256(index_name \\x00 asset_url)}`` -> JSON array of image ids.
    Keyed by (index, asset) so a corpus re-indexed under a new index name never
    collides with stale entries.
    """

    def __init__(self, settings: RedisImageResolutionCacheSettings) -> None:
        if not settings.redis_url:
            raise ValueError("RedisImageResolutionCache requires a redis_url")
        if settings.ttl_seconds <= 0:
            raise ValueError("RedisImageResolutionCache requires ttl_seconds > 0")
        self._settings = settings
        # Connect via REDIS_URL as-is (shared default DB 0); the namespace prefix
        # isolates this cache's keyspace. Encode a DB in REDIS_URL if ever needed.
        self._client: Redis = Redis.from_url(settings.redis_url)
        self._ns = settings.namespace
        self._ttl = settings.ttl_seconds
        logger.info(
            "RedisImageResolutionCache initialized: namespace=%s ttl=%s",
            self._ns,
            self._ttl,
        )

    def _key(self, index_name: str, asset_url: str) -> str:
        # NUL separator keeps (index, asset) pairs unambiguous; sha256 bounds the
        # key length independent of asset-URL length. Not a security hash.
        digest = hashlib.sha256(f"{index_name}\x00{asset_url}".encode()).hexdigest()
        return f"{self._ns}:{digest}"

    async def is_ready(self) -> bool:
        try:
            await self._client.ping()
            return True
        except RedisError as exc:
            logger.warning("Image resolution cache (Redis) unavailable: %s", exc)
            return False

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except RedisError:
            pass

    async def get(self, index_name: str, asset_url: str) -> Optional[List[str]]:
        """Return the cached ordered image-id list for an asset, or None on miss/error."""
        key = self._key(index_name, asset_url)
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            value = orjson.loads(raw)
            if not isinstance(value, list):
                logger.warning("Image resolution cache holds non-list value for %s; ignoring", key)
                return None
            return value
        except RedisError as exc:
            logger.warning("Image resolution cache get failed (treating as miss): %s", exc)
            return None
        except (orjson.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Image resolution cache holds unparseable value for %s: %s", key, exc)
            return None

    async def set(self, index_name: str, asset_url: str, image_ids: List[str]) -> None:
        """Cache the ordered image-id list for an asset with the configured TTL.

        Best-effort: any Redis error is swallowed so a cache-write failure never
        propagates into the image response.
        """
        key = self._key(index_name, asset_url)
        try:
            await self._client.set(key, orjson.dumps(image_ids), ex=self._ttl)
        except RedisError as exc:
            logger.warning("Image resolution cache set failed (not cached): %s", exc)
