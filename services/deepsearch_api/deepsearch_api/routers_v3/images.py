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

import base64
import logging
from typing import Annotated, Optional

from deepsearch_api._constants import IMAGE_MAGIC_TO_MIME
from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.cache import RedisImageResolutionCache
from deepsearch_api.routers_v2 import dependencies
from deepsearch_api.routers_v2.models import AssetUrl
from deepsearch_api.routers_v2.service import check_acl
from deepsearch_api.search_backend.filtered import FilteredSearchClient
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.main import (  # noqa: F401  (patched by tests via this module path)
    SearchBackendClientV2,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from prometheus_client import Counter
from starlette.requests import Request

from search_utils.storage_client import RemoteFileUri, StorageClient
from search_utils.url_mapping import to_public_url

router = APIRouter(
    tags=["Images"],
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# asset_url -> image_id[] resolution cache outcome, labelled "hit" / "miss". Only
# counted when a resolution cache is configured. Lazily created once per process
# so the module can be imported repeatedly (tests) without a duplicate registration.
_IMAGE_CACHE_EVENTS: Optional[Counter] = None


def _image_cache_events() -> Counter:
    global _IMAGE_CACHE_EVENTS
    if _IMAGE_CACHE_EVENTS is None:
        _IMAGE_CACHE_EVENTS = Counter(
            "image_resolution_cache_events_total",
            "Image resolution cache (asset_url -> image_id[]) lookups by outcome (hit/miss).",
            ["outcome"],
        )
    return _IMAGE_CACHE_EVENTS


async def load_image_by_key(image_key: str, image_loader: BaseImageLoader) -> str:
    """Direct cache lookup — no OpenSearch hop, no ACL check."""
    with tracer.start_as_current_span("images.load_image_by_key", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("image_key", image_key)
        image_data_base64 = await image_loader.load_image(image_key)

    if image_data_base64 is None:
        raise HTTPException(status_code=404, detail=f"Image data not found for image_key '{image_key}'")
    return image_data_base64


async def _resolve_image_ids(
    asset_url: str,
    search_backend_v2: FilteredSearchClient,
    resolution_cache: Optional[RedisImageResolutionCache],
) -> list[str]:
    """Return the asset's ordered per-view image ids (``base_key -> [image_id, ...]``).

    Served from the Redis resolution cache when available; on a miss it runs the
    OpenSearch ``search`` and populates the cache. Raises 404 when the asset is
    not indexed. Callers MUST have already performed the ACL check — this hop is
    cached and does no authorization.
    """
    index_name = search_backend_v2.search_client.index_name

    if resolution_cache is not None:
        cached = await resolution_cache.get(index_name, asset_url)
        if cached is not None:
            _image_cache_events().labels(outcome="hit").inc()
            return cached
        _image_cache_events().labels(outcome="miss").inc()

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
        raise HTTPException(status_code=404, detail=f"Asset with URL '{asset_url}' not found")

    hit = next((h for h in hits if h.get("_source", {}).get("base_key") == asset_url), hits[0])
    siglip2_embeddings = hit.get("_source", {}).get("siglip2-embedding", [])
    image_ids = [emb.get("image") for emb in siglip2_embeddings]

    # Only cache a real resolution — a not-yet-rendered asset may gain thumbnails
    # later, so don't pin an empty list (and let the TTL bound staleness anyway).
    if resolution_cache is not None and image_ids:
        await resolution_cache.set(index_name, asset_url, image_ids)

    return image_ids


async def resolve_image_by_asset_url(
    asset_url: str,
    storage_client: StorageClient,
    search_backend_v2: FilteredSearchClient,
    storage_require_auth: bool,
    image_loader: BaseImageLoader,
    img_offset: int = 0,
    resolution_cache: Optional[RedisImageResolutionCache] = None,
) -> str:
    """ACL-check the asset, resolve its image_id (Redis-cached), then load bytes from cache."""
    with tracer.start_as_current_span("images.resolve_by_asset_url", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("asset_url", asset_url)
        span.set_attribute("img_offset", img_offset)

        if storage_require_auth:
            logger.debug("Checking access for asset URL: %s", asset_url)
            remote_file_uris: list[RemoteFileUri] = [asset_url]
            with tracer.start_as_current_span("images.resolve_by_asset_url.check_acl"):
                accessible_urls = await check_acl(remote_file_uris, storage_client)
            if not accessible_urls:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            logger.debug("Access control disabled")

        image_ids = await _resolve_image_ids(asset_url, search_backend_v2, resolution_cache)

        if not image_ids:
            raise HTTPException(status_code=404, detail=f"No images found for asset '{asset_url}'")
        if len(image_ids) <= img_offset:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Image offset {img_offset} not available for asset '{asset_url}' "
                    f"(only {len(image_ids)} images available)"
                ),
            )

        image_id = image_ids[img_offset]
        if not image_id:
            raise HTTPException(
                status_code=404,
                detail=f"No images found at offset {img_offset} for asset '{asset_url}'",
            )

        logger.debug("Loading image with ID: %s", image_id)
        with tracer.start_as_current_span("images.resolve_by_asset_url.load_image") as load_image_span:
            load_image_span.set_attribute("image_id", image_id)
            image_data_base64 = await image_loader.load_image(image_id)

        if image_data_base64 is None:
            raise HTTPException(status_code=404, detail=f"Image data not found for asset '{asset_url}'")
        return image_data_base64


@router.get(
    "/images",
    summary="Fetch asset thumbnail image — use after search to visually inspect results",
    description="Fetch image binary data for a specific asset. This is the primary way to get thumbnails for visual "
    "inspection of search results. After running a search query, call this endpoint for each result's "
    "source.url (or source.base_key) to get its thumbnail. Use img_offset=0,1,2... to get multiple "
    "views/angles of the same asset when available.",
    response_class=Response,
    responses={
        200: {
            "description": "Successfully retrieved image binary data",
            "content": {
                "image/jpeg": {
                    "schema": {"type": "string", "format": "binary"},
                    "example": "Binary JPEG image data",
                },
                "image/png": {
                    "schema": {"type": "string", "format": "binary"},
                    "example": "Binary PNG image data",
                },
                "image/gif": {
                    "schema": {"type": "string", "format": "binary"},
                    "example": "Binary GIF image data",
                },
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"},
                    "example": "Binary image data",
                },
            },
        },
        400: {
            "description": "Bad Request",
            "content": {
                "application/json": {
                    "examples": {
                        "missing_params": {
                            "summary": "Missing required parameters",
                            "value": {"detail": "Either asset_url or image_key must be provided"},
                        },
                        "conflicting_params": {
                            "summary": "Conflicting parameters",
                            "value": {"detail": "Only one of asset_url or image_key should be provided"},
                        },
                        "invalid_offset": {
                            "summary": "Invalid offset parameter",
                            "value": {"detail": "img_offset can only be used with asset_url, not with image_key"},
                        },
                    }
                }
            },
        },
        403: {
            "description": "Access Denied",
            "content": {"application/json": {"example": {"detail": "Access denied"}}},
        },
        404: {
            "description": "Image Not Found",
            "content": {
                "application/json": {
                    "examples": {
                        "asset_not_found": {
                            "summary": "Asset not found",
                            "value": {"detail": "Asset with URL 's3://sample-bucket/asset.usd' not found"},
                        },
                        "offset_out_of_range": {
                            "summary": "Image offset out of range",
                            "value": {
                                "detail": "Image offset 5 not available for asset 's3://sample-bucket/asset.usd' (only 3 images available)"
                            },
                        },
                        "no_images": {
                            "summary": "No images available",
                            "value": {"detail": "No images found for asset 's3://sample-bucket/asset.usd'"},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error",
            "content": {"application/json": {"example": {"detail": "Failed to process image data"}}},
        },
    },
)
async def get_image(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    request: Request,
    # Also the auth gate for the image_key path (401 on a bad API key or missing
    # Nucleus credentials), so it stays a declared dependency on both paths.
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    asset_url: Annotated[
        Optional[AssetUrl],
        Query(
            description="The complete URL of the asset to fetch image data for. Must be a valid asset URL that the user has access to.",
        ),
    ] = None,
    image_key: Annotated[
        Optional[str],
        Query(
            description="Direct image key/ID to fetch from OpenSearch. Use this for direct image retrieval when you already know the image identifier.",
        ),
    ] = None,
    img_offset: Annotated[
        int,
        Query(
            description="Zero-based index specifying which image to fetch from the asset's siglip2-embeddings. Only valid when using asset_url.",
            example=0,
            ge=0,
        ),
    ] = 0,
) -> Response:
    """
    Retrieve image binary data for DeepSearch assets.

    Use this endpoint after a search to visually inspect results. Even results that matched
    only via text search (no vector embedding match) may have thumbnails available — always
    try fetching by asset_url.

    This endpoint allows you to fetch image data in two ways:

    **Method 1: By Asset URL** (Recommended for post-search inspection)
    - Provide an `asset_url` (use the `source.url` or `source.base_key` from search results)
    - Use `img_offset=0,1,2...` to get different views/angles of the same asset
    - A 404 with "Image offset N not available" tells you how many views exist
    - Includes automatic access control validation

    **Method 2: By Direct Image Key**
    - Provide an `image_key` for direct image retrieval from the image store
    - Useful when you have image IDs from `metadata.explanations[].matched_vectors[].image`
    - Cannot be combined with `img_offset`

    ## Authentication
    This endpoint supports multiple authentication methods:
    - **Bearer Token**: Include `Authorization: Bearer <token>` header
    - **Basic Auth**: Use standard HTTP Basic Authentication
    - **API Key**: Include API key in the appropriate header

    ## Access Control
    - When using `asset_url`, the system verifies user access to the underlying asset
    - Only images from accessible assets are returned
    - Access is determined by the configured storage authentication policies

    ## Response Format
    - Returns raw binary image data with appropriate Content-Type header
    - Supports JPEG, PNG, and GIF formats
    - Content-Type is automatically detected from image data

    ## Error Handling
    - **400**: Invalid parameters (missing required fields, conflicting parameters)
    - **403**: Access denied to the requested asset
    - **404**: Asset or image not found, or invalid offset
    - **500**: Internal processing error (e.g., corrupted image data)
    """

    if not asset_url and not image_key:
        raise HTTPException(status_code=400, detail="Either asset_url or image_key must be provided")
    if asset_url and image_key:
        raise HTTPException(
            status_code=400,
            detail="Only one of asset_url or image_key should be provided",
        )
    if image_key and img_offset > 0:
        raise HTTPException(
            status_code=400,
            detail="img_offset can only be used with asset_url, not with image_key",
        )

    if image_key:
        image_data_base64 = await load_image_by_key(image_key=image_key, image_loader=image_loader)
    else:
        # Only the asset_url path needs the search backend, so it is resolved here
        # rather than as a dependency every thumbnail request would pay for. The
        # shared asset-graph client is passed because None would fall back to
        # ApiClient.get_default(), a separate session that is never closed; this
        # path never calls the asset graph itself.
        search_client = request.app.search_backend_client
        await search_client.ensure_mappings_verified()
        search_backend_v2 = FilteredSearchClient(
            search_client=search_client,
            ags_client=await dependencies.shared_ags_client(request.app),
            storage_client=storage_client,
            validate_access=request.app.global_settings.storage_require_auth,
        )
        image_data_base64 = await resolve_image_by_asset_url(
            asset_url=asset_url,
            img_offset=img_offset,
            storage_client=storage_client,
            search_backend_v2=search_backend_v2,
            storage_require_auth=request.app.global_settings.storage_require_auth,
            image_loader=image_loader,
            resolution_cache=getattr(request.app, "image_resolution_cache", None),
        )

    # Decode base64 image data to binary
    try:
        image_data_binary = base64.b64decode(image_data_base64)
    except Exception as e:
        logger.error(f"Failed to decode base64 image data: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process image data")

    # Determine content type from the image's magic bytes (defaulting to JPEG).
    content_type = next(
        (mime for magic, mime in IMAGE_MAGIC_TO_MIME.items() if image_data_binary.startswith(magic)),
        "image/jpeg",
    )

    # identifier = image_key if image_key else asset_url
    # logger.info(f"Successfully loaded image for {identifier}, content_type: {content_type}")
    #
    # Thumbnails are content-addressed (image id is a sha256 of the bytes) and
    # therefore immutable, so let the caller's browser cache them and stop
    # re-fetching on every render/scroll. "private" (not "public") because the
    # asset_url path is access-controlled per user — only the end user's own
    # browser may cache, never a shared proxy/CDN. This overrides the global
    # no-store security header (see security_headers_middleware).
    return Response(
        content=image_data_binary,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400, immutable"},
    )
