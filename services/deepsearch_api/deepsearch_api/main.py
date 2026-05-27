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
from typing import Any, Dict

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
from deepsearch_api.exceptions import (
    AGSServiceConnectionError,
    AGSServiceUnavailable,
    AuthenticationError,
    NoneTokenProvided,
)
from deepsearch_api.routers_v2 import ags, authorization, search
from deepsearch_api.routers_v3 import images, search_v3
from deepsearch_api.search_backend.embeddings import USDSearchEmbeddingClient
from deepsearch_api.search_backend.exceptions import (
    ImageProcessingError,
    ScoringConfigQueryMismatchError,
)
from deepsearch_api.search_backend.main import SearchSettings
from deepsearch_api.tracing import provider
from deepsearch_api.utils import AccessLogFilter, GRPCCommonFilter, get_api_description
from deepsearch_api.validation import SearchResultValidator, ValidationSettings
from fastapi import APIRouter, FastAPI, status
from fastapi.exceptions import RequestValidationError
from opensearchpy.exceptions import RequestError
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import PrometheusFastApiInstrumentator
from pydantic_settings import BaseSettings
from siglip2_triton_client.interface import TritonClientException
from starlette.requests import Request
from starlette.responses import JSONResponse
from vision_endpoint.clip_triton_client import SigLIP2Config

from search_utils.misc_utils import str2bool
from search_utils.storage_client import StorageClientAuthenticationError

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
    siglip2_config = SigLIP2Config(triton_server_url=os.getenv("TRITON_SERVER_URL", "0.0.0.0:8001"))
    app.usd_search_embedding_client = USDSearchEmbeddingClient(config=siglip2_config)
    # Initialize VLM validator if enabled
    validation_settings = ValidationSettings()
    if validation_settings.enabled:
        try:
            app.vlm_validator = SearchResultValidator(validation_settings)
            logger.info(
                "VLM validator initialized with service: %s",
                validation_settings.vlm_service,
            )
        except Exception as e:
            logger.warning(
                "Failed to initialize VLM validator: %s. Validation feature will be disabled.",
                e,
            )
    yield


app = FastAPI(
    title="DeepSearch API",
    description=get_api_description(),
    version=get_app_version(),
    openapi_tags=tags_metadata,
    lifespan=lifespan,
)
v2_api_router = APIRouter(prefix="/v2")
v2_api_router.include_router(search.router)
v2_api_router.include_router(ags.router)
v2_api_router.include_router(authorization.router)
v3_api_router = APIRouter(prefix="/v3")
v3_api_router.include_router(search_v3.router)
v3_api_router.include_router(search_v3.vlm_router)
v3_api_router.include_router(images.router)
app.include_router(v2_api_router)
app.include_router(v3_api_router)
app.include_router(images.router)
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
            "details": str(exc),
        },
    )


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
from search_utils.local_fs_middleware import LocalFSPathMiddleware

app.add_middleware(LocalFSPathMiddleware)

FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

if __name__ == "__main__":
    uvicorn.run(app)
