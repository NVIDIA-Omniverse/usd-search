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

# standard modules
import logging
import os
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import AsyncIterator

# third party modules
import redis
from fastapi import APIRouter, FastAPI
from prometheus_fastapi_instrumentator import PrometheusFastApiInstrumentator
from pydantic_settings import BaseSettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from storage.src.services.config import NGSearchStorageSearchBackendConfig

# local / proprietary modules
from .api.backend import router as backend_router
from .api.clients import get_active_plugins, get_cache_client, get_storage_client
from .api.exceptions import (
    AssetNotFoundError,
    EmptyPluginList,
    InvalidURL,
    NGSearchStorageConnectionError,
)
from .api.health import router as health_router
from .api.indexing import router as indexing_router
from .api.plugin_info import router as plugin_router
from .api.processing import router as processing_router
from .api.utils import AccessLogFilter
from .config import INFOEndpointServiceConfig

SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=SENTRY_DSN)

logging.getLogger("uvicorn.access").addFilter(AccessLogFilter())


class MainServiceSettings(BaseSettings):
    prom_metric_namespace: str = "omnideepsearch"
    prom_metric_subsystem: str = "indexing_status"


main_service_settings = MainServiceSettings()


def get_app_version() -> str:
    try:
        return version("deepsearch")
    except PackageNotFoundError:
        return "0.0.1-dev"


def get_api_description() -> str:
    with open(f"{Path(__file__).parent}/README.md", "r", encoding="utf-8") as file:
        return file.read()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the storage client connection context that will be available throughout the lifespan of the app

    Args:
        app (FastAPI): app

    Returns:
        AsyncIterator[None]: result
    """
    # get clients
    app.active_plugins = get_active_plugins()
    app.cache_client = await get_cache_client()
    app.storage_client = get_storage_client()
    app.service_config = INFOEndpointServiceConfig()
    app.search_backend_config = NGSearchStorageSearchBackendConfig()
    instrumentator.expose(app, tags=["internal_metrics"], include_in_schema=False)

    async with app.storage_client.connection_context_with_tagging(return_self=True):
        yield


app = FastAPI(
    title="Indexing Endpoint",
    lifespan=lifespan,
    description=get_api_description(),
    version=get_app_version(),
)

info_router = APIRouter(prefix="/info")
info_router.include_router(indexing_router)
info_router.include_router(backend_router)
info_router.include_router(plugin_router)

app.include_router(info_router)
app.include_router(health_router)
app.include_router(processing_router)

# Local filesystem path rewriting (no-op unless LOCAL_FS_MODE=true).
from search_utils.local_fs_middleware import LocalFSPathMiddleware

app.add_middleware(LocalFSPathMiddleware)


@app.exception_handler(redis.exceptions.ConnectionError)
async def thumbnail_missing_exception(request: Request, exc: redis.exceptions.ConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": "Redis Cache unavailable", "details": str(exc)},
    )


@app.exception_handler(NGSearchStorageConnectionError)
async def ngsearch_storage_backend_unavailable(request: Request, exc: NGSearchStorageConnectionError) -> JSONResponse:
    return JSONResponse(
        status_code=501,
        content={"error": "NGSearch storage backend unavailable", "details": str(exc)},
    )


@app.exception_handler(InvalidURL)
async def invalid_url_exception(request: Request, exc: InvalidURL) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Invalid URL", "details": str(exc)},
    )


@app.exception_handler(EmptyPluginList)
async def empty_plugin_list(request: Request, exc: EmptyPluginList) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Empty plugin list.", "details": str(exc)},
    )


@app.exception_handler(AssetNotFoundError)
async def asset_not_found(request: Request, exc: AssetNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": "Asset missing", "details": str(exc)},
    )


# instrument the app with the prometheus metrics
instrumentator = PrometheusFastApiInstrumentator().instrument(
    app,
    metric_namespace=main_service_settings.prom_metric_namespace,
    metric_subsystem=main_service_settings.prom_metric_subsystem,
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
