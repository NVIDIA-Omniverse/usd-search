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

import json
import logging
import os
from contextlib import asynccontextmanager
from importlib.metadata import version
from time import time

# local / proprietary modules
import deepsearch_api
import deepsearch_api.tracing
import httpx
import orjson

# third party modules
import uvicorn
from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from asset_graph_service_client.exceptions import NotFoundException
from deepsearch_api import health
from deepsearch_api.cache import (
    RankingCache,
    RankingCacheSettings,
    RedisImageResolutionCache,
    RedisImageResolutionCacheSettings,
    RedisValidationCache,
    RedisValidationCacheSettings,
)
from deepsearch_api.exceptions import (
    AGSServiceConnectionError,
    AGSServiceUnavailable,
    AuthenticationError,
    NoneTokenProvided,
)
from deepsearch_api.llm_parse import (
    LLMParseExtractionError,
    LLMParseExtractor,
    LLMParseSettings,
)
from deepsearch_api.llm_parse.router import router as query_parsing_router
from deepsearch_api.routers_v2 import ags, authorization, search
from deepsearch_api.routers_v3 import download, images, search_v3
from deepsearch_api.routers_v3.download import DownloadSettings
from deepsearch_api.search_backend.embeddings import (
    EmbeddingType,
    USDSearchEmbeddingClient,
)
from deepsearch_api.search_backend.exceptions import (
    ImageCacheReadError,
    ImageProcessingError,
    ImageQueryNotFoundError,
    ScoringConfigQueryMismatchError,
)
from deepsearch_api.search_backend.main import SearchBackendClientV2, SearchSettings
from deepsearch_api.tracing import provider
from deepsearch_api.utils import AccessLogFilter, GRPCCommonFilter, get_api_description
from deepsearch_api.validation import (
    SearchResultValidator,
    ValidationSettings,
)
from fastapi import APIRouter, FastAPI, status
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from opensearchpy.exceptions import RequestError
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import PrometheusFastApiInstrumentator
from pydantic_settings import BaseSettings
from siglip2_triton_client import SigLIP2Config
from siglip2_triton_client.interface import TritonClientException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from search_utils.misc_utils import str2bool
from search_utils.storage_client import StorageClientAuthenticationError
from search_utils.url_mapping import configure_url_mapper, rewrite_response_text

SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    from base_logging import setup_logging as _setup_logging

    from search_utils.telemetry_utils import telemetry_logger

    _setup_logging()

    # bugfix for telemetry logging
    # TODO: need to switch telemetry logger from being initialized in the search_utils package
    # to being configured from logging config file
    telemetry_logger.propagate = str2bool(os.getenv("TELEMETRY_LOG_PROPAGATE", "True"))


setup_logging()


class MainServiceSettings(BaseSettings):
    prom_metric_namespace: str = "omnideepsearch"
    prom_metric_subsystem: str = "restapi"
    deepsearch_backend_asset_graph_service_url: str
    storage_require_auth: bool = True
    deepsearch_backend_admin_access_key: str | None = None
    "When set to True, the endpoints using the storage client will return `401 Unauthorized` if the access token is None."


def get_app_version() -> str:
    try:
        return version(deepsearch_api.__package__)
    except Exception:
        return "0.0.1-dev"


global_settings = MainServiceSettings()
search_backend_settings = SearchSettings()

tags_metadata = [
    {
        "name": "AI Search",
        "description": "Current version of the main AI search API.",
    },
    {
        "name": "Relevance verification",
        "description": "VLM-based validation of search results against the original query.",
    },
    {
        "name": "v2_asset_graph_search",
        "description": "Current version of the Asset Graph Search (AGS) API.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Public/internal asset-URL translation. Installed before anything can serve a
    # request, and deliberately NOT wrapped in a try/except: a half-applied mapping
    # would answer with silent 404s rather than errors, so a bad config must stop
    # the service here. A no-op unless USDSEARCH_URL_MAPPING_MODE is set.
    app.url_mapper = configure_url_mapper()

    app.usd_search_embedding_client = USDSearchEmbeddingClient(config=SigLIP2Config.from_env())

    # Process-wide search backend client. Built ONCE here (it owns an OpenSearch
    # connection pool) and shared across requests, instead of constructing — and
    # tearing down — a fresh pool per search. It carries no per-caller auth (the
    # per-request FilteredSearchClient wrapper holds that), so it is safe to share.
    # Construction is lazy (no socket), so this never fails even if OpenSearch is
    # down at startup; the index-mapping check is best-effort and retried lazily
    # on the first search (see SearchBackendClientV2.ensure_mappings_verified).
    app.search_backend_client = SearchBackendClientV2(
        search_backend_settings,
        embedding_clients={EmbeddingType.SIGLIP2_EMBEDDING: app.usd_search_embedding_client},
    )
    try:
        await app.search_backend_client.ensure_mappings_verified()
    except Exception as e:
        logger.warning("Search index mapping check deferred (OpenSearch unreachable at startup?): %s", e)

    # Download bundler tunables (DOWNLOAD_* env vars). Resolved here in the
    # lifespan rather than at module import so tests can build the app without
    # the import-time env read; the /download/asset handler reads app.download_settings.
    app.download_settings = DownloadSettings()

    # Thumbnail image loader — built ONCE here (it owns an OpenSearch connection
    # pool) and reused across /images requests, instead of constructing (and
    # leaking) a fresh client per request. See routers_v2.dependencies.image_loader.
    from deepsearch_api.routers_v2.dependencies import (
        build_ags_api_client,
        build_image_loader,
    )

    app.image_loader = build_image_loader(search_backend_settings)

    # Asset-graph client — built ONCE here (it owns an SSL context and an aiohttp
    # session) and shared; each request only gets a header-scoped view of it. See
    # routers_v2.dependencies.async_ags_client.
    app.ags_api_client = build_ags_api_client(global_settings.deepsearch_backend_asset_graph_service_url)

    # Optional persistent cache of the asset_url -> image_id[] resolution (Redis)
    # so a repeat thumbnail request skips the OpenSearch lookup. Probe once; if
    # unreachable, fall through to resolving via OpenSearch on every request.
    app.image_resolution_cache = None
    image_cache_settings = RedisImageResolutionCacheSettings()
    if image_cache_settings.is_active:
        try:
            candidate = RedisImageResolutionCache(image_cache_settings)
            if await candidate.is_ready():
                app.image_resolution_cache = candidate
                logger.info(
                    "Image resolution cache (Redis) enabled: namespace=%s ttl=%s",
                    image_cache_settings.namespace,
                    image_cache_settings.ttl_seconds,
                )
            else:
                await candidate.aclose()
                logger.warning("Image resolution cache configured but Redis unreachable; resolving via OpenSearch.")
        except Exception as e:
            logger.warning("Failed to initialize image resolution cache: %s. Resolving via OpenSearch.", e)
    else:
        logger.info(
            "Image resolution cache (Redis) disabled (enabled=%s, redis_url %s); resolving via OpenSearch.",
            image_cache_settings.enabled,
            "set" if image_cache_settings.redis_url else "unset",
        )

    # Optional cache of RRF-fused result orderings (Redis) so pages 2..N of a
    # multi-leg query skip re-running every leg. Purely a latency optimisation:
    # when absent or unreachable, each page recomputes the ranking from the
    # cursor, which is correct — just slower. Probe once, same as above.
    app.ranking_cache = None
    ranking_cache_settings = RankingCacheSettings()
    if ranking_cache_settings.is_active:
        try:
            candidate = RankingCache(ranking_cache_settings)
            if await candidate.is_ready():
                app.ranking_cache = candidate
                logger.info(
                    "Search ranking cache (Redis) enabled: namespace=%s ttl=%s max_entries=%s",
                    ranking_cache_settings.namespace,
                    ranking_cache_settings.ttl_seconds,
                    ranking_cache_settings.max_entries,
                )
            else:
                await candidate.aclose()
                logger.warning("Search ranking cache configured but Redis unreachable; paging will recompute.")
        except Exception as e:
            logger.warning("Failed to initialize search ranking cache: %s. Paging will recompute.", e)
    else:
        logger.info(
            "Search ranking cache (Redis) disabled (enabled=%s, redis_url %s); paging will recompute each page.",
            ranking_cache_settings.enabled,
            "set" if ranking_cache_settings.redis_url else "unset",
        )

    # Hand the cache to the shared backend client — it owns the fused-ranking
    # read/write on the pagination path.
    app.search_backend_client.ranking_cache = app.ranking_cache

    # Initialize VLM validator if enabled
    app.vlm_validation_cache = None
    validation_settings = ValidationSettings()
    if validation_settings.enabled:
        try:
            # Optional persistent L2 verdict cache (Redis). Probe reachability once;
            # if unreachable, fall back to L1-only rather than failing validation.
            redis_cache = None
            cache_settings = RedisValidationCacheSettings()
            if cache_settings.is_active:
                candidate = RedisValidationCache(cache_settings)
                if await candidate.is_ready():
                    redis_cache = candidate
                    app.vlm_validation_cache = candidate
                    logger.info(
                        "VLM validation verdict cache (Redis L2) enabled: namespace=%s ttl=%s max_entries=%s",
                        cache_settings.namespace,
                        cache_settings.ttl_seconds,
                        cache_settings.max_entries,
                    )
                else:
                    await candidate.aclose()
                    logger.warning(
                        "VLM validation verdict cache configured but Redis unreachable; using L1-only cache."
                    )
            else:
                logger.info(
                    "VLM validation verdict cache (Redis L2) disabled (enabled=%s, redis_url %s); "
                    "using L1-only cache.",
                    cache_settings.enabled,
                    "set" if cache_settings.redis_url else "unset",
                )
            app.vlm_validator = SearchResultValidator(validation_settings, redis_cache=redis_cache)
            logger.info(
                "VLM validator initialized with model: %s",
                validation_settings.model,
            )
            # For method=logprob, probe once at boot so an incompatible model logs a
            # single actionable line instead of failing on every per-result request.
            await app.vlm_validator.aprobe_logprob_capability()
        except Exception as e:
            logger.warning(
                "Failed to initialize VLM validator: %s. Validation feature will be disabled.",
                e,
            )
    # Initialize the LLM query parser if enabled. Set unconditionally (mirrors the
    # VLM validator above) so a boot-probe failure doesn't permanently disable it;
    # is_ready() re-probes per its own TTL, so the feature self-heals.
    app.llm_parse_extractor = None
    llm_parse_settings = LLMParseSettings()
    if llm_parse_settings.enabled:
        try:
            extractor = LLMParseExtractor(llm_parse_settings)
            app.llm_parse_extractor = extractor
            if await extractor.is_ready():
                logger.info("LLM query parsing ready with model: %s", llm_parse_settings.model)
            else:
                logger.warning(
                    "LLM query parsing model unreachable at boot (model=%s); requests will fast-503 "
                    "until a probe (every %.0fs) succeeds.",
                    llm_parse_settings.model,
                    llm_parse_settings.probe_ttl_seconds,
                )
        except Exception as e:
            logger.warning(
                "Failed to initialize LLM query parser: %s. /llm_parse/query will 503.",
                e,
            )
    yield
    # Shutdown: release the shared search backend OpenSearch connection pool.
    if getattr(app, "search_backend_client", None) is not None:
        try:
            await app.search_backend_client.close()
        except Exception as e:
            logger.warning("Failed to close search backend client: %s", e)
    # Release the Redis validation-cache connection pool if we opened one.
    if getattr(app, "vlm_validation_cache", None) is not None:
        await app.vlm_validation_cache.aclose()
    # Release the image resolution cache connection pool if we opened one.
    if getattr(app, "image_resolution_cache", None) is not None:
        await app.image_resolution_cache.aclose()
    # Release the ranking cache connection pool if we opened one.
    if getattr(app, "ranking_cache", None) is not None:
        await app.ranking_cache.aclose()
    # Release the shared image loader's OpenSearch client if it owns one.
    loader = getattr(app, "image_loader", None)
    loader_client = getattr(loader, "client", None)
    if loader_client is not None:
        try:
            await loader_client.close()
        except Exception as e:
            logger.warning("Failed to close image loader OpenSearch client: %s", e)
    # Release the shared asset-graph client's aiohttp session.
    ags_api_client = getattr(app, "ags_api_client", None)
    if ags_api_client is not None:
        try:
            await ags_api_client.close()
        except Exception as e:
            logger.warning("Failed to close asset-graph client: %s", e)


app = FastAPI(
    title="DeepSearch API",
    description=get_api_description(),
    version=get_app_version(),
    openapi_tags=tags_metadata,
    lifespan=lifespan,
    # Disabled so a trailing-slash request (e.g. /search/) returns a clean 404
    # instead of a 307 to the internal /v2/deepsearch/... path, which the gateway
    # does not expose (it 404s) and which leaks the internal route prefix.
    redirect_slashes=False,
)
v2_api_router = APIRouter(prefix="/v2")
v2_api_router.include_router(search.router)
v2_api_router.include_router(ags.router)
v2_api_router.include_router(authorization.router)
v3_api_router = APIRouter(prefix="/v3")
v3_api_router.include_router(search_v3.router)
v3_api_router.include_router(search_v3.vlm_router)
v3_api_router.include_router(query_parsing_router)
v3_api_router.include_router(images.router)
v3_api_router.include_router(download.router)
app.include_router(v2_api_router)
app.include_router(v3_api_router)
app.include_router(images.router)
app.include_router(download.router)
app.include_router(health.router)


@app.exception_handler(ScoringConfigQueryMismatchError)
async def scoring_config_query_mismatch_error(request: Request, exc: ScoringConfigQueryMismatchError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "Scoring config query mismatch.", "details": str(exc)},
    )


@app.exception_handler(ImageProcessingError)
async def image_processing_error(request: Request, exc: ImageProcessingError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "Image processing error.", "details": str(exc)},
    )


@app.exception_handler(ImageQueryNotFoundError)
async def image_query_not_found_error(request: Request, exc: ImageQueryNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "Image query not found.", "details": rewrite_response_text(str(exc))},
    )


@app.exception_handler(ImageCacheReadError)
async def image_cache_read_error(request: Request, exc: ImageCacheReadError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"error": "Image cache temporarily unavailable.", "details": rewrite_response_text(str(exc))},
    )


@app.exception_handler(LLMParseExtractionError)
async def llm_parse_extraction_error(request: Request, exc: LLMParseExtractionError) -> JSONResponse:
    # The /llm_parse/query LLM call failed after retries. Surface a clear 503
    # instead of an ambiguous 500; the client (e.g. the Explorer) treats this as
    # a cue to fall back to plain semantic search on the raw text.
    return JSONResponse(
        status_code=503,
        content={
            "error": "LLM query parsing is temporarily unavailable.",
            "details": str(exc),
        },
    )


@app.exception_handler(ConnectionError)
async def connection_error_handler(request: Request, exc: ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "Error connecting upstream service.", "details": str(exc)},
    )


@app.exception_handler(AGSServiceUnavailable)
async def ags_service_unavailable(request: Request, exc: ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "AGS service unavailable.", "details": str(exc)},
    )


@app.exception_handler(AGSServiceConnectionError)
async def ags_service_connection_error(request: Request, exc: ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"error": "AGS service connection Error.", "details": str(exc)},
    )


@app.exception_handler(NotFoundException)
async def ags_service_url_not_found_error(request: Request, exc: ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": "Provided scene URL is not found in the Asset Graph Search index.",
            "details": rewrite_response_text(str(exc)),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_with_public_urls(request: Request, exc: StarletteHTTPException) -> Response:
    """Default HTTP error handling, with asset URLs in the public form.

    A 404 for an asset should quote the URL the caller actually sent, not its
    internal translation — otherwise the deployment leaks the internal address in
    exactly the responses a client is most likely to log or display. A no-op
    unless URL mapping is configured.
    """
    if isinstance(exc.detail, str):
        exc = StarletteHTTPException(
            status_code=exc.status_code,
            detail=rewrite_response_text(exc.detail),
            headers=exc.headers,
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(httpx.ConnectError)
async def httpx_connection_error(request: Request, exc: ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={
            "error": "HTTPX connection error service unavailable.",
            "details": str(exc),
        },
    )


@app.exception_handler(NoneTokenProvided)
async def none_token_provided_error_handler(request: Request, exc: NoneTokenProvided) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "No token provided"},
    )


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "Authentication error", "details": str(exc)},
    )


@app.exception_handler(StorageClientAuthenticationError)
async def storage_client_connection_error_handler(
    request: Request, exc: StorageClientAuthenticationError
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "Authentication error", "reason": exc.reason},
    )


@app.exception_handler(TritonClientException)
async def embedding_service_error_handler(request: Request, exc: TritonClientException) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={"error": "Embedding service unavailable", "details": str(exc)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Override the default 422 handler to strip the echoed ``input`` field from every
    error detail, preventing reflected-input / XSS findings in security scans."""
    sanitized_errors = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": sanitized_errors},
    )


@app.exception_handler(RequestError)
async def opensearch_request_exception(request: Request, exc: RequestError) -> JSONResponse:
    """Catches and responds to OpenSearch exception. There are two reasons for this exception:
    * something is wrong with the search backend
    * query is not constructed properly and there are parsing errors.

    If the former is the case - some generic message is returned with a 500 error code.
    If the latter is the case - more information about the parsing error is returned.
    """
    logger.error("OpenSearch request error: %s", exc.error, exc_info=exc)
    if "search_phase_execution_exception" in exc.error:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "Search query error", "details": str(exc)},
        )
    try:
        json_error = orjson.loads(exc.error)
    except orjson.JSONDecodeError:
        return JSONResponse(status_code=500, content={"error": "Search backend error"})
    if json_error["error"]["root_cause"][0]["type"] == "parse_exception":
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": json_error["error"]["root_cause"][0]["type"],
                "details": json_error["error"]["root_cause"][0]["reason"],
            },
        )
    return JSONResponse(status_code=500, content={"error": "Search backend error", "details": str(exc)})


# global settings
app.global_settings = global_settings
app.search_backend_settings = search_backend_settings


# instrument the app with the prometheus metrics
instrumentator = PrometheusFastApiInstrumentator().instrument(
    app,
    metric_namespace=global_settings.prom_metric_namespace,
    metric_subsystem=global_settings.prom_metric_subsystem,
    latency_lowr_buckets=(
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1,
        1.5,
        2,
        2.5,
        3,
        3.5,
        4,
        4.5,
        5,
        7.5,
        10,
        30,
        60,
    ),
)

instrumentator.expose(app)


@app.on_event("startup")
async def configure_uvicorn_logging() -> None:
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(AccessLogFilter())
    grpc_common_logger = logging.getLogger("grpc._common")
    grpc_common_logger.addFilter(GRPCCommonFilter())


@app.on_event("startup")
async def init_prometheus_metrics() -> None:
    instrumentator.expose(app, tags=["internal_metrics"], include_in_schema=False)


request_duration_logger = logging.getLogger("deepsearch_api.request_duration_logger")


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Default to no-store for API responses, but let a route opt out by setting
    # its own Cache-Control (e.g. /images serves immutable, content-addressed
    # thumbnails that are safe for the caller's browser to cache).
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def response_duration_logging_middleware(request: Request, call_next):
    start_time = time()
    response = await call_next(request)
    process_time = time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    excluded_paths = ["readyz", "livez", "health", "metrics"]
    if any(path in request.url.path for path in excluded_paths):
        return response
    request_duration_logger.info("Request duration:\t%ss", process_time)
    return response


@app.middleware("http")
async def add_request_id_to_span(request: Request, call_next):
    request_id = correlation_id.get()
    trace.get_current_span().set_attribute("http.request_id", request_id)
    return await call_next(request)


requests_logger = logging.getLogger("deepsearch_api.requests_logger")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    log_requests = os.getenv("LOG_REQUESTS", "false").lower() == "true"

    excluded_paths = set(["readyz", "livez", "health", "metrics"])
    is_internal_request = any(path in request.url.path for path in excluded_paths)

    if log_requests and not is_internal_request:
        log_content = {
            "url": str(request.url),
            "method": request.method,
            "query_params": dict(request.query_params),
            "request_id": correlation_id.get(),
        }
        log_headers = os.getenv("LOG_HEADERS", "false").lower() == "true"
        if log_headers:
            log_content["headers"] = dict(request.headers)

        body = await request.body()
        log_content["body"] = body.decode("utf-8") if body else None

        requests_logger.info(json.dumps(log_content))

    response = await call_next(request)
    return response


app.add_middleware(
    CorrelationIdMiddleware,
)

# Local filesystem path rewriting (no-op unless LOCAL_FS_MODE=true).
from search_utils.local_fs_middleware import LocalFSPathMiddleware  # noqa: E402

app.add_middleware(LocalFSPathMiddleware)

FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

if __name__ == "__main__":
    uvicorn.run(app)
