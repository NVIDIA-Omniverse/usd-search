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
import hashlib
import json
import logging
from contextlib import aclosing
from typing import Annotated, Optional

from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.routers_v2 import dependencies
from deepsearch_api.routers_v2.models import (
    BatchValidateItem,
    BatchValidateRequest,
    BatchValidateResponse,
    QueryRelevanceValidationResult,
    ValidateResultItem,
    ValidateResultRequest,
    ValidationQuery,
)
from deepsearch_api.search_backend.filtered import FilteredSearchClient
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.main import SearchBackendClientV2
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    SearchResponse,
    SearchResult,
)
from deepsearch_api.search_backend.pagination import PaginationError
from deepsearch_api.telemetry_decorator import telemetry_track_search
from deepsearch_api.utils import DurationLogger
from deepsearch_api.validation import SearchResultValidator, VLMValidationError
from deepsearch_api.validation.policy import apply_validation_mode
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.params import Depends
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from search_utils.storage_client import StorageClient
from search_utils.url_mapping import rewrite_response_document

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


def _vlm_error_http_exception(exc: VLMValidationError, model: Optional[str]) -> HTTPException:
    """Map a batch-level VLM validation failure to a structured HTTP 503.

    Status stays 503 so the Explorer's reactive batch-teardown path still fires;
    the JSON detail carries the machine-readable ``error_type`` + the provider's
    ``message`` + ``retryable`` so the client can show the actual reason and, for a
    non-retryable configuration error (e.g. the model doesn't support logprobs),
    resolve still-pending hits to a terminal state instead of spinning forever.
    """
    return HTTPException(
        status_code=503,
        detail={
            "error_type": exc.error_type,
            "message": str(exc),
            "model": model,
            "retryable": exc.retryable,
        },
    )


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


def _first_query_text(*candidates: object) -> Optional[str]:
    """The first candidate that carries text, stripped; ``None`` when all are blank.

    A whitespace-only query has no validation signal (the validator drops it too),
    so it must not switch validation on and load a thumbnail per hit before the
    validator would short-circuit. Stripping here also means the validator, its
    verdict cache key and the VLM all see the same query text."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _query_image_digest(query_image: str) -> str:
    """Short stable identifier of a query image for tracing: correlates identical
    images across traces without exporting the (possibly whole base64) payload."""
    return hashlib.sha256(query_image.encode()).hexdigest()[:16]


def _select_validation_image_keys(body: ValidateResultItem, max_images: int) -> list[str]:
    """Dedupe the requested views and enforce the deployment view budget.

    Rejecting (rather than silently truncating) keeps the contract honest:
    a caller who sends more views than the deployment allows gets a 400
    naming the knob to raise, instead of a verdict quietly based on fewer
    views than they asked for.
    """
    image_keys = body.image_keys or ([body.image_key] if body.image_key else [])
    selected: list[str] = []
    for image_key in image_keys:
        if image_key not in selected:
            selected.append(image_key)
    if len(selected) > max_images:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(selected)} unique image_keys provided but this deployment "
                f"allows at most {max_images} view(s) per validation; raise "
                "USDSEARCH_VISION_VALIDATION_MAX_IMAGES_PER_VALIDATION "
                "(helm: validation.max_images_per_validation) to accept more."
            ),
        )
    return selected


def _select_validation_images(images: list[str], max_images: int) -> list[str]:
    """Dedupe client-supplied raw images and enforce the deployment view budget.

    Mirrors :func:`_select_validation_image_keys` for the raw-image path: reject
    (rather than silently truncate) when the caller sends more views than the
    deployment allows, so the verdict is always based on exactly the views asked
    for.
    """
    selected: list[str] = []
    for image in images:
        if image not in selected:
            selected.append(image)
    if len(selected) > max_images:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(selected)} unique images provided but this deployment "
                f"allows at most {max_images} view(s) per validation; raise "
                "USDSEARCH_VISION_VALIDATION_MAX_IMAGES_PER_VALIDATION "
                "(helm: validation.max_images_per_validation) to accept more."
            ),
        )
    return selected


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
    # Matched vectors are score-ordered, so this keeps the highest-ranked unique
    # views while applying the budget before any image payload is loaded.
    image_ids = []
    if hit.metadata and hit.metadata.explanations:
        for exp in hit.metadata.explanations:
            for mv in exp.matched_vectors or []:
                if mv.image and mv.image not in image_ids:
                    image_ids.append(mv.image)
    image_ids = image_ids[: vlm_validator.settings.max_images_per_validation]

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
                        resolution_cache=getattr(request.app, "image_resolution_cache", None),
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


class _AssetImages:
    """Thumbnails by asset URL (the slow path) on ONE storage client and search client, opened on first use."""

    def __init__(self, request: Request, token_auth, basic_auth, api_key_auth, image_loader: BaseImageLoader):
        self._request = request
        self._auth = (token_auth, basic_auth, api_key_auth)
        self._image_loader = image_loader
        self._lock = asyncio.Lock()
        self._storage_gen = None
        self._storage: Optional[StorageClient] = None
        self._search: Optional[FilteredSearchClient] = None

    async def _clients(self) -> tuple[StorageClient, FilteredSearchClient]:
        async with self._lock:
            if self._storage is None:
                token_auth, basic_auth, api_key_auth = self._auth
                role = await dependencies.api_key_auth_role(api_key_auth, self._request)
                self._storage_gen = dependencies.storage_client(token_auth, basic_auth, role, self._request)
                self._storage = await anext(self._storage_gen)
            if self._search is None:
                # Reuse the process-wide search client (don't open/close a pool here).
                search_backend = self._request.app.search_backend_client
                await search_backend.ensure_mappings_verified()
                self._search = FilteredSearchClient(
                    search_client=search_backend,
                    ags_client=None,
                    storage_client=self._storage,
                    validate_access=self._request.app.global_settings.storage_require_auth,
                )
            return self._storage, self._search

    async def load(self, asset_url) -> Optional[str]:
        storage, search = await self._clients()
        # The asset_url -> image id lookup goes through GET /images' Redis cache (when configured): the
        # tiles of the page being judged have usually just filled it.
        return await resolve_image_by_asset_url(
            asset_url=asset_url,
            storage_client=storage,
            search_backend_v2=search,
            storage_require_auth=self._request.app.global_settings.storage_require_auth,
            image_loader=self._image_loader,
            resolution_cache=getattr(self._request.app, "image_resolution_cache", None),
        )

    async def aclose(self) -> None:
        if self._storage_gen is not None:
            await self._storage_gen.aclose()


async def _validate_item(
    item: ValidateResultItem,
    query: ValidationQuery,
    image_loader: BaseImageLoader,
    vlm_validator: SearchResultValidator,
    asset_images: _AssetImages,
) -> QueryRelevanceValidationResult:
    """One verdict through the shared verdict cache, loading the images only on a miss.

    Raises HTTPException (400 view budget, 404 no image, 504 no verdict) or VLMValidationError."""
    max_images = vlm_validator.settings.max_images_per_validation
    # image_key/image_keys/images are mutually exclusive (the request model), so at most one of these
    # contributes views; the view budget is checked before anything loads.
    image_keys = _select_validation_image_keys(item, max_images)
    raw_images = _select_validation_images(item.images, max_images) if item.images else []
    span = trace.get_current_span()
    span.set_attribute("image_keys_count", len(image_keys))
    span.set_attribute("raw_images_count", len(item.images or []))

    # Identity: the validated views (a raw image by a bounded digest, not its payload), or the asset URL on the
    # slow path, plus the facts the prompt carries — the same entries the inline search path reuses.
    if raw_images:
        identity = [hashlib.sha1(img.encode(), usedforsecurity=False).hexdigest() for img in raw_images]
    else:
        identity = image_keys or [str(item.asset_url)]
    asset_facts = item.asset_facts()
    facts_text = vlm_validator.asset_facts_text(query.query_text, query.query_image, asset_facts)
    cache_key = vlm_validator.make_cache_key(query.query_text, query.query_image, identity, facts_text=facts_text)

    async def _load() -> list[str]:
        if raw_images:
            # Raw-image path: validate client-supplied images as-is, no index lookup.
            return raw_images
        if image_keys:
            images = await image_loader.load_images(image_keys)
            loaded = [img for key in image_keys if (img := images.get(key)) is not None]
            if not loaded:
                raise HTTPException(status_code=404, detail="No images found for provided keys")
            return loaded
        image = await asset_images.load(item.asset_url)
        return [image] if image else []

    async def _supplier() -> Optional[QueryRelevanceValidationResult]:
        loaded = await _load()
        if not loaded:
            raise HTTPException(status_code=404, detail="No images could be loaded for validation")
        verdicts = await vlm_validator.validate_results(
            query.query_text, query.query_image, [loaded], asset_facts=[asset_facts]
        )
        return verdicts[0]

    result = await vlm_validator.validate_once(cache_key, _supplier)
    if result is None:
        raise HTTPException(status_code=504, detail="VLM validation timed out for this result")
    return QueryRelevanceValidationResult(
        is_match=result.is_match,
        confidence=result.confidence,
        similarity_score=result.similarity_score,
        reasoning=result.reasoning,
        model=_active_vlm_model_identifier(vlm_validator),
    )


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
        asset_images = _AssetImages(request, token_auth, basic_auth, api_key_auth, image_loader)
        try:
            return await _validate_item(body, body, image_loader, vlm_validator, asset_images)
        except VLMValidationError as e:
            # Provider unreachable (transient) or the request was rejected as
            # unsupported/malformed (permanent config error, e.g. logprobs not
            # supported). Both surface as a structured 503 so the Explorer tears
            # down the batch and shows the reason; `retryable` in the body tells
            # it whether pending hits may recover or should go terminal.
            raise _vlm_error_http_exception(e, _active_vlm_model_identifier(vlm_validator)) from e
        finally:
            await asset_images.aclose()


# At most this many results of one batch are judged at once (max_concurrent still caps provider calls per process).
BATCH_CONCURRENCY = 16
# A blank line after this long without a result keeps proxies from closing a quiet stream.
BATCH_HEARTBEAT_S = 10.0


# OpenAPI schema of one streamed NDJSON line (blank heartbeat lines aside). BatchValidateResult is registered
# in components through BatchValidateResponse, the stream=false model.
BATCH_STREAM_LINE_SCHEMA = {
    "oneOf": [
        {"$ref": "#/components/schemas/BatchValidateResult"},
        {
            "type": "object",
            "title": "BatchValidateFatal",
            "required": ["fatal", "error_type", "retryable"],
            "properties": {
                "fatal": {"type": "string"},
                "error_type": {"type": "string"},
                "retryable": {"type": "boolean"},
                "model": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
        },
        {
            "type": "object",
            "title": "BatchValidateDone",
            "required": ["done"],
            "properties": {
                "done": {
                    "type": "object",
                    "required": ["completed", "errored"],
                    "properties": {"completed": {"type": "integer"}, "errored": {"type": "integer"}},
                }
            },
        },
    ]
}


def _ndjson(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":")) + "\n"


@vlm_router.post(
    "/vlm_validate/search_result_batch",
    response_model=None,
    responses={
        200: {
            "model": BatchValidateResponse,
            "description": "stream=false: one JSON body; stream=true (default): NDJSON, one object per line",
            "content": {"application/x-ndjson": {"schema": BATCH_STREAM_LINE_SCHEMA}},
        }
    },
    summary="Validate a page of search results with VLM",
    description="Judges up to 100 results against one query in ONE request; each item takes the single-result "
    "route's asset fields and gets its verdict and cache. `stream` (default true) answers NDJSON as each result "
    'lands: `{"id", "verdict"}` or `{"id", "error"}` per result, a blank heartbeat line, `{"fatal", "error_type", '
    '"retryable"}` when the model is unreachable or refuses the request (the stream ends there), and `{"done": '
    '{"completed", "errored"}}` last; a stream without `done` was cut. `stream: false` answers one JSON body once '
    "every result is judged (a fatal error is the single route's 503).",
)
async def validate_result_batch_endpoint(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    vlm_validator: Annotated[Optional[SearchResultValidator], Depends(dependencies.vlm_validator)],
    request: Request,
    body: BatchValidateRequest = Body(...),
):
    if not vlm_validator:
        raise HTTPException(status_code=503, detail="VLM validation is not enabled on this server")
    model = _active_vlm_model_identifier(vlm_validator)
    asset_images = _AssetImages(request, token_auth, basic_auth, api_key_auth, image_loader)
    queue: asyncio.Queue = asyncio.Queue()
    batch_sem = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def _worker(item: BatchValidateItem) -> None:
        async with batch_sem:
            try:
                result = await _validate_item(item, body, image_loader, vlm_validator, asset_images)
            except VLMValidationError as exc:
                await queue.put(("fatal", exc))  # no result of this batch can be judged
                return
            except HTTPException as exc:
                await queue.put(("error", {"id": item.id, "error": str(exc.detail)}))
                return
            except Exception as exc:  # noqa: BLE001 — one result must not end the batch
                logger.warning("batch validation of %s failed (%s: %s)", item.id, type(exc).__name__, exc)
                await queue.put(("error", {"id": item.id, "error": f"validation failed: {type(exc).__name__}"}))
                return
            await queue.put(("verdict", {"id": item.id, "verdict": result.model_dump()}))

    async def _results():
        """(kind, payload) per result as it lands, ("heartbeat", None) while quiet; ends after a fatal."""
        # The workers start here, not in the endpoint: a client gone before the body is read starts nothing.
        tasks = [asyncio.create_task(_worker(item)) for item in body.items]
        try:
            remaining = len(tasks)
            while remaining:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=BATCH_HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield "heartbeat", None
                    continue
                yield kind, payload
                if kind == "fatal":
                    return
                remaining -= 1
        finally:
            for task in tasks:
                task.cancel()
            await asset_images.aclose()

    if not body.stream:
        lines = []
        async with aclosing(_results()) as results:
            async for kind, payload in results:
                if kind == "fatal":
                    raise _vlm_error_http_exception(payload, model)
                if kind != "heartbeat":
                    lines.append(payload)
        completed = sum(1 for line in lines if "verdict" in line)
        response = BatchValidateResponse(results=lines, completed=completed, errored=len(lines) - completed)
        return JSONResponse(content=response.model_dump(exclude_none=True))

    async def _stream():
        completed = errored = 0
        async with aclosing(_results()) as results:
            async for kind, payload in results:
                if kind == "heartbeat":
                    yield "\n"
                    continue
                if kind == "fatal":
                    fatal = {"fatal": str(payload), "error_type": payload.error_type, "retryable": payload.retryable}
                    yield _ndjson({**fatal, "model": model})
                    return
                if kind == "verdict":
                    completed += 1
                else:
                    errored += 1
                yield _ndjson(payload)
        yield _ndjson({"done": {"completed": completed, "errored": errored}})

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


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

    **Pagination:** pass `offset`, or better, the previous response's `next_cursor`
    back as `cursor` — it pins the ranking so pages do not overlap or skip. The
    response carries `next_cursor`, `has_more`, `paginable_total` (the page-count
    basis — not `corpus_total`) and a `pagination` diagnostic block whose
    `depth_limit_reason` distinguishes "no more results" from "cannot page further
    for this query shape". Depth depends on the shape: filter-only queries are
    unbounded, a text query is capped by the deployment's `pagination_max_offset`,
    and a multi-leg query is capped by the RRF fusion window. `validate_results=true`
    is single-page and cannot be combined with `offset`/`cursor`.
    """
    # Force return_images when validate_results=True (images are needed for validation)
    if req.validate_results:
        req.return_images = True

    # make sure return_inner_hits is True if return_embeddings or return_images is True
    if req.return_embeddings or req.return_images:
        req.return_inner_hits = True

    try:
        results = await search_backend_v2.search(req)
    except PaginationError as e:
        # Every PaginationError is caller-correctable: a corrupt/expired cursor, a
        # cursor from a different query, an offset past the depth cap, or paging
        # combined with validate_results.
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Perform VLM validation if requested
    if req.validate_results and vlm_validator and results.hits:
        query_text = _first_query_text(
            req.hybrid_text_query,
            req.description,
            *(vq.query for vq in (req.vector_queries or []) if vq.query_type == "text"),
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
                    # The query is request data and query_image can be a whole base64
                    # image: the span records its shape (presence, length, digest),
                    # never the payload, so traces neither leak user input nor exceed
                    # attribute-size limits on this hot path.
                    span.set_attribute("has_query_text", query_text is not None)
                    span.set_attribute("has_query_image", query_image is not None)
                    if query_text is not None:
                        span.set_attribute("query_text_length", len(query_text))
                    if query_image is not None:
                        span.set_attribute("query_image_length", len(query_image))
                        span.set_attribute("query_image_digest", _query_image_digest(query_image))
                    span.set_attribute("hits_count", len(results.hits))
                    span.set_attribute("vlm_model", vlm_validator.settings.model)
                    try:
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
                    except VLMValidationError as e:
                        # A provider-down or configuration error applies to the whole
                        # batch (same config + endpoint). Surface it as a structured
                        # 503 instead of a bare 500 — the caller learns validation did
                        # not run and why. Retrieval already succeeded; the client can
                        # re-request without validation to get unvalidated results.
                        raise _vlm_error_http_exception(e, _active_vlm_model_identifier(vlm_validator)) from e
            for hit, val_result in zip(results.hits, validation_results):
                if val_result is not None:
                    hit.query_relevance = QueryRelevanceValidationResult(
                        is_match=val_result.is_match,
                        confidence=val_result.confidence,
                        similarity_score=val_result.similarity_score,
                        reasoning=val_result.reasoning,
                    )

            results.hits = apply_validation_mode(results.hits, vlm_validator.settings.mode)

    # Last step before serialization: translate `source.base_key` / `source.url`
    # and the AGS prim URLs to the deployment's public form. Everything above —
    # validation, image resolution, the pagination cursor — worked on the internal
    # form, which is what those lookups are keyed by. No-op unless configured.
    return rewrite_response_document(results)
