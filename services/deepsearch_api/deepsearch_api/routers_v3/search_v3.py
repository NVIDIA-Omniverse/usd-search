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

import asyncio
import logging
from typing import Annotated, Optional

from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.routers_v2 import dependencies
from deepsearch_api.routers_v2.models import (
    QueryRelevanceValidationResult,
    ValidateResultRequest,
)
from deepsearch_api.search_backend.embeddings import EmbeddingType
from deepsearch_api.search_backend.filtered import FilteredSearchClient
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.main import SearchBackendClientV2
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    SearchResponse,
    SearchResult,
)
from deepsearch_api.telemetry_decorator import telemetry_track_search
from deepsearch_api.utils import DurationLogger
from deepsearch_api.validation import SearchResultValidator, VLMServiceUnavailable
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.params import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from search_utils.storage_client import StorageClient

from .images import resolve_image_by_asset_url

search_prefix = "deepsearch"
router = APIRouter(
    prefix=f"/{search_prefix}",
    tags=["AI Search"],
)
# Separate router so vlm_validate endpoints get only the "Relevance verification"
# tag — FastAPI appends router-level tags to operation-level tags, so adding
# tags=[...] on the @router.post(...) below would not replace "AI Search".
vlm_router = APIRouter(
    prefix=f"/{search_prefix}",
    tags=["Relevance verification"],
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _active_vlm_model_identifier(
    vlm_validator: Optional[SearchResultValidator],
) -> Optional[str]:
    """Return a stable identifier for the currently-configured validation model,
    or None when validation is disabled. The identifier is intentionally opaque to
    clients — they just include it in their cache key. Bumping the model env var
    (``USDSEARCH_VISION_VALIDATION_MODEL``) changes the string and forces re-validation.
    """
    if vlm_validator is None:
        return None
    return vlm_validator.settings.model


async def validate_result(
    token_auth: HTTPAuthorizationCredentials,
    basic_auth: HTTPBasicCredentials,
    api_key_auth: str,
    request: Request,
    storage_client: StorageClient,
    hit: SearchResult,
    search_backend_v2: SearchBackendClientV2,
    image_loader: BaseImageLoader,
    vlm_validator: SearchResultValidator,
    query_text: Optional[str],
    query_image: Optional[str],
) -> Optional[QueryRelevanceValidationResult]:
    """Validate a single search result.

    Args:
        token_auth: HTTPAuthorizationCredentials - for token authentication
        basic_auth: HTTPBasicCredentials - for basic authentication
        api_key_auth: str - for API key authentication
        request: Request - for the current request
        storage_client: StorageClient - for the storage client
        hit: SearchResult - for the search result to validate
        search_backend_v2: SearchBackendClientV2 - for the search backend client
        image_loader: BaseImageLoader - for the image loader to use for getting the image
        vlm_validator: SearchResultValidator - for the VLM validator to use for validation
        query_text: Optional[str] - for the query text (combined from all text inputs)
        query_image: Optional[str] - for the query image (from image similarity search)
    """
    logger.info(f"Validating result for hit {hit.source.get('base_key', hit.id)}")
    # Extract all image keys from matched vectors (up to 8)
    image_ids = []
    if hit.metadata and hit.metadata.explanations:
        for exp in hit.metadata.explanations:
            for mv in exp.matched_vectors or []:
                if mv.image and mv.image not in image_ids:
                    image_ids.append(mv.image)
    image_ids = image_ids[:8]

    async def _load_and_validate() -> Optional[QueryRelevanceValidationResult]:
        with tracer.start_as_current_span("routers_v3.validate_result", kind=SpanKind.INTERNAL) as span:
            span.set_attribute("hit.source.base_key", hit.source.get("base_key"))
            span.set_attribute("image_count", len(image_ids))

            try:
                if image_ids:
                    # Fast path: batch load images by key
                    images_dict = await image_loader.load_images(image_ids)
                    loaded_images = [img for key in image_ids if (img := images_dict.get(key)) is not None]
                else:
                    # Fallback: load single image by asset URL
                    image_base64 = await resolve_image_by_asset_url(
                        asset_url=hit.source.get("base_key"),
                        storage_client=storage_client,
                        search_backend_v2=search_backend_v2,
                        storage_require_auth=request.app.global_settings.storage_require_auth,
                        image_loader=image_loader,
                    )
                    loaded_images = [image_base64] if image_base64 else []

                if not loaded_images:
                    logger.warning(f"No images found for hit {hit.source.get('base_key', hit.id)}")
                    return None

                logger.info(f"Got {len(loaded_images)} image(s) for hit {hit.source.get('base_key')}")
            except HTTPException as e:
                logger.error(f"Failed to get image: {e} for hit {hit.source.get('base_key', hit.id)}")
                return None

            return (await vlm_validator.validate_results(query_text, query_image, [loaded_images]))[0]

    # Memoize by (model, query, image identity): duplicate assets in one page
    # (deduplicate_by_hash=false) coalesce into a single load+VLM call, and
    # re-runs of the same query reuse the cached verdict entirely. When the hit
    # exposes no image keys, the asset URL is the identity for the fallback path.
    cache_key = vlm_validator.make_cache_key(
        query_text, query_image, image_ids or [str(hit.source.get("base_key", hit.id))]
    )
    return await vlm_validator.validate_once(cache_key, _load_and_validate)


@vlm_router.post(
    "/vlm_validate/search_result",
    response_model=QueryRelevanceValidationResult,
    summary="Validate a single search result with VLM",
    description="Validates a single asset image against a query using a Vision Language Model. "
    "Returns match status, confidence, similarity score, and reasoning.",
)
async def validate_result_endpoint(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    vlm_validator: Annotated[Optional[SearchResultValidator], Depends(dependencies.vlm_validator)],
    request: Request,
    body: ValidateResultRequest = Body(...),
) -> QueryRelevanceValidationResult:
    if not vlm_validator:
        raise HTTPException(status_code=503, detail="VLM validation is not enabled on this server")

    with tracer.start_as_current_span("routers_v3.validate_result_endpoint", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("asset_url", body.asset_url or "None")
        span.set_attribute("image_keys_count", len(body.image_keys) if body.image_keys else 0)

        if body.image_keys:
            # Fast path: batch load images directly from cache by keys
            images_dict = await image_loader.load_images(body.image_keys)
            loaded_images = [img for key in body.image_keys if (img := images_dict.get(key)) is not None]
            if not loaded_images:
                raise HTTPException(status_code=404, detail="No images found for provided keys")
        else:
            # Slow path: need search backend to resolve asset_url to image key
            role = await dependencies.api_key_auth_role(api_key_auth, request)
            storage_client_gen = dependencies.storage_client(token_auth, basic_auth, role, request)
            storage_client_inst = await anext(storage_client_gen)
            try:
                async with SearchBackendClientV2(
                    request.app.search_backend_settings,
                    embedding_clients={EmbeddingType.SIGLIP2_EMBEDDING: request.app.usd_search_embedding_client},
                ) as search_backend:
                    filtered_client = FilteredSearchClient(
                        search_client=search_backend,
                        ags_client=None,
                        storage_client=storage_client_inst,
                        validate_access=request.app.global_settings.storage_require_auth,
                    )
                    image_base64 = await resolve_image_by_asset_url(
                        asset_url=body.asset_url,
                        storage_client=storage_client_inst,
                        search_backend_v2=filtered_client,
                        storage_require_auth=request.app.global_settings.storage_require_auth,
                        image_loader=image_loader,
                    )
                    loaded_images = [image_base64] if image_base64 else []
            finally:
                await storage_client_gen.aclose()

        if not loaded_images:
            raise HTTPException(status_code=404, detail="No images could be loaded for validation")

        try:
            results = await vlm_validator.validate_results(body.query_text, body.query_image, [loaded_images])
        except VLMServiceUnavailable as e:
            # Provider is unreachable (network/DNS/TLS/connection refused).
            # 503 is the contract: Explorer's reactive 503 handler tears down
            # the batch and surfaces the "VLM unavailable" banner, instead of
            # hammering through dozens of failing per-hit 504s.
            raise HTTPException(status_code=503, detail=f"VLM service unavailable: {e}") from e
        result = results[0]

        if result is None:
            raise HTTPException(status_code=504, detail="VLM validation timed out for this result")

        return QueryRelevanceValidationResult(
            is_match=result.is_match,
            confidence=result.confidence,
            similarity_score=result.similarity_score,
            reasoning=result.reasoning,
            model=_active_vlm_model_identifier(vlm_validator),
        )


@router.post(
    "/search",
    response_model_exclude_none=True,
    summary="Hybrid AI Search — find 3D assets using text, vector, image similarity, and filters",
    responses={
        200: {
            "description": "Search results",
            # "content": {"application/json": {"example": [SearchResult.Config.schema_extra["examples"][0]]}},
        }
    },
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/DeepSearchSearchRequestV2",
                    },
                    "examples": {
                        "minimal_hybrid_search": {
                            "summary": "Minimal hybrid search (recommended starting point)",
                            "value": DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][0],
                        },
                        "image_similarity_search": {
                            "summary": "Image similarity search (find visually similar assets)",
                            "value": DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][1],
                        },
                        "size_constrained_search": {
                            "summary": "Size-constrained search (bounding box filters)",
                            "value": DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][2],
                        },
                        "property_filtered_search": {
                            "summary": "Property-filtered search (semantic labels)",
                            "value": DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][3],
                        },
                        "advanced_scoring_search": {
                            "summary": "Advanced hybrid search with custom scoring",
                            "value": DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][4],
                        },
                    },
                }
            }
        }
    },
)
@telemetry_track_search()
async def search_post(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    req: DeepSearchSearchRequestV2,
    search_backend_v2: Annotated[
        SearchBackendClientV2,
        Body(
            examples=[
                DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][0],
                DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][1],
                DeepSearchSearchRequestV2.Config.json_schema_extra["examples"][2],
            ]
        ),
        Depends(dependencies.search_backend_client_v2),
    ],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    request: Request,
    vlm_validator: Annotated[Optional[SearchResultValidator], Depends(dependencies.vlm_validator)] = None,
) -> SearchResponse:
    """Search for 3D assets using combined text + vector + filter search with Reciprocal Rank Fusion scoring.

    This is the **recommended endpoint** for AI agents and programmatic access. It combines:
    - **Hybrid Text Search**: Keyword matching across asset names, paths, USD properties, and AI-generated metadata
    - **Vector Similarity Search**: Semantic matching using SigLIP2 vision-language embeddings (1536 dims)
    - **Reciprocal Rank Fusion (RRF)**: Merges text and vector results into a single high-quality ranking
    - **Extensive Filtering**: File metadata, dates, USD properties, bounding box dimensions, tags
    - **VLM Validation**: Optional server-side validation of results using a Vision Language Model

    **Quick Start for AI Agents:**
    1. Set `hybrid_text_query` to a short description (2-5 words)
    2. Add a `vector_queries` entry with `field_name="siglip2-embedding.embedding"`, `query_type="text"`, same query text
    3. Set `file_extension_include="usd*"` for USD assets
    4. Set `return_images=true` for visual inspection
    5. Use `limit=20-50` for exploration
    """
    # Force return_images when validate_results=True (images are needed for validation)
    if req.validate_results:
        req.return_images = True

    # make sure return_inner_hits is True if return_embeddings or return_images is True
    if req.return_embeddings or req.return_images:
        req.return_inner_hits = True

    results = await search_backend_v2.search(req)

    # Perform VLM validation if requested
    if req.validate_results and vlm_validator and results.hits:
        query_text = (
            req.hybrid_text_query
            or req.description
            or next(
                (vq.query for vq in (req.vector_queries or []) if vq.query_type == "text" and vq.query),
                None,
            )
        )
        query_image = (
            req.image_similarity_search[0]
            if req.image_similarity_search
            else next(
                (vq.query for vq in (req.vector_queries or []) if vq.query_type == "image" and vq.query),
                None,
            )
        )

        if query_text or query_image:

            with DurationLogger(f"results validation ({len(results.hits)})", logger, "INFO"):
                with tracer.start_as_current_span("routers_v3.search_post.validate_results") as span:
                    span.set_attribute("query_text", query_text if query_text is not None else "None")
                    span.set_attribute(
                        "query_image",
                        query_image if query_image is not None else "None",
                    )
                    span.set_attribute("hits_count", len(results.hits))
                    span.set_attribute("vlm_model", vlm_validator.settings.model)
                    validation_results = await asyncio.gather(
                        *[
                            validate_result(
                                token_auth,
                                basic_auth,
                                api_key_auth,
                                request,
                                storage_client,
                                hit,
                                search_backend_v2,
                                image_loader,
                                vlm_validator,
                                query_text,
                                query_image,
                            )
                            for hit in results.hits
                        ]
                    )
            for hit, val_result in zip(results.hits, validation_results):
                if val_result is not None:
                    hit.query_relevance = QueryRelevanceValidationResult(
                        is_match=val_result.is_match,
                        confidence=val_result.confidence,
                        similarity_score=val_result.similarity_score,
                        reasoning=val_result.reasoning,
                    )

    return results
