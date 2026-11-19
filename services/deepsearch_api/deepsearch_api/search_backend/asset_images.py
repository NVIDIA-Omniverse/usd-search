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

"""Asset URL -> indexed image ids, shared by ``GET /images`` and image-URL search queries."""

from typing import TYPE_CHECKING, Optional

from opentelemetry import trace
from prometheus_client import Counter

from search_utils.url_mapping import to_public_url

if TYPE_CHECKING:
    from deepsearch_api.cache import RedisImageResolutionCache
    from deepsearch_api.search_backend.filtered import FilteredSearchClient

tracer = trace.get_tracer(__name__)

# Created lazily once per process so the module can be imported repeatedly (tests)
# without a duplicate registration.
_IMAGE_CACHE_EVENTS: Optional[Counter] = None


def image_cache_events() -> Counter:
    global _IMAGE_CACHE_EVENTS
    if _IMAGE_CACHE_EVENTS is None:
        _IMAGE_CACHE_EVENTS = Counter(
            "image_resolution_cache_events_total",
            "Image resolution cache (asset_url -> image_id[]) lookups by outcome (hit/miss).",
            ["outcome"],
        )
    return _IMAGE_CACHE_EVENTS


async def resolve_asset_image_ids(
    asset_url: str,
    search_backend_v2: "FilteredSearchClient",
    resolution_cache: Optional["RedisImageResolutionCache"],
) -> Optional[list[str]]:
    """Return the asset's ordered per-view image ids, or ``None`` when the asset is not indexed.

    Does no authorization: callers MUST have done the ACL check already.
    """
    index_name = search_backend_v2.search_client.index_name

    if resolution_cache is not None:
        cached = await resolution_cache.get(index_name, asset_url)
        if cached is not None:
            image_cache_events().labels(outcome="hit").inc()
            return cached
        image_cache_events().labels(outcome="miss").inc()

    # With URL mapping on, the asset may be indexed under its public URL rather than the internal form the request
    # was normalized to (a corpus crawled from https URLs on a deployment that maps s3:// <-> https://: every lookup
    # missed). Look it up under both, preferring the internal form; with mapping off this is the one exact term.
    public_url = to_public_url(asset_url)
    candidates = [asset_url] if public_url in (None, asset_url) else [asset_url, public_url]
    search_query = {
        "query": {"term": {"base_key": asset_url}} if len(candidates) == 1 else {"terms": {"base_key": candidates}},
        "_source": ["siglip2-embedding"] if len(candidates) == 1 else ["siglip2-embedding", "base_key"],
        "size": len(candidates),
    }
    with tracer.start_as_current_span("images.resolve_by_asset_url.search"):
        search_response = await search_backend_v2.search_client.client.search(index=index_name, body=search_query)

    hits = search_response.get("hits", {}).get("hits") or []
    if not hits:
        return None

    hit = next((h for h in hits if h.get("_source", {}).get("base_key") == asset_url), hits[0])
    siglip2_embeddings = hit.get("_source", {}).get("siglip2-embedding", [])
    image_ids = [emb.get("image") for emb in siglip2_embeddings]

    # Only cache a real resolution — a not-yet-rendered asset may gain thumbnails
    # later, so don't pin an empty list (and let the TTL bound staleness anyway).
    if resolution_cache is not None and image_ids:
        await resolution_cache.set(index_name, asset_url, image_ids)

    return image_ids
