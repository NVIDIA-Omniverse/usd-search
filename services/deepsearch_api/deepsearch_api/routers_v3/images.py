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
from deepsearch_api.routers_v2 import dependencies
from deepsearch_api.routers_v2.service import check_acl
from deepsearch_api.search_backend.filtered import FilteredSearchClient
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.main import SearchBackendClientV2
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from starlette.requests import Request

from search_utils.storage_client import RemoteFileUri, StorageClient

router = APIRouter(
    tags=["Images"],
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def load_image_by_key(image_key: str, image_loader: BaseImageLoader) -> str:
    """Direct cache lookup — no OpenSearch hop, no ACL check."""
    with tracer.start_as_current_span("images.load_image_by_key", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("image_key", image_key)
        image_data_base64 = await image_loader.load_image(image_key)

    if image_data_base64 is None:
        raise HTTPException(status_code=404, detail=f"Image data not found for image_key '{image_key}'")
    return image_data_base64


async def resolve_image_by_asset_url(
    asset_url: str,
    storage_client: StorageClient,
    search_backend_v2: FilteredSearchClient,
    storage_require_auth: bool,
    image_loader: BaseImageLoader,
    img_offset: int = 0,
) -> str:
    """ACL-check the asset, look up its image_id in OpenSearch, then load from cache."""
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

        search_query = {
            "query": {"term": {"base_key": asset_url}},
            "_source": ["siglip2-embedding"],
            "size": 1,
        }
        with tracer.start_as_current_span("images.resolve_by_asset_url.search"):
            search_response = await search_backend_v2.search_client.client.search(
                index=search_backend_v2.search_client.index_name, body=search_query
            )

        if not search_response.get("hits", {}).get("hits"):
            raise HTTPException(status_code=404, detail=f"Asset with URL '{asset_url}' not found")

        hit = search_response["hits"]["hits"][0]
        siglip2_embeddings = hit.get("_source", {}).get("siglip2-embedding", [])

        if not siglip2_embeddings:
            raise HTTPException(status_code=404, detail=f"No images found for asset '{asset_url}'")
        if len(siglip2_embeddings) <= img_offset:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Image offset {img_offset} not available for asset '{asset_url}' "
                    f"(only {len(siglip2_embeddings)} images available)"
                ),
            )

        image_id = siglip2_embeddings[img_offset].get("image")
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
    search_backend_v2: Annotated[FilteredSearchClient, Depends(dependencies.search_backend_client_v2)],
    request: Request,
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    asset_url: Annotated[
        Optional[str],
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
        image_data_base64 = await resolve_image_by_asset_url(
            asset_url=asset_url,
            img_offset=img_offset,
            storage_client=storage_client,
            search_backend_v2=search_backend_v2,
            storage_require_auth=request.app.global_settings.storage_require_auth,
            image_loader=image_loader,
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
    return Response(content=image_data_binary, media_type=content_type)
