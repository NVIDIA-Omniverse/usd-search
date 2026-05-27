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
from asyncio import Semaphore
from contextlib import asynccontextmanager

from cachetools import TTLCache
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import PrometheusFastApiInstrumentator

from ..exceptions import (
    EmptySceneError,
    InvalidMTLNames,
    KitOutOfMemoryError,
    LoadError,
    ProcessLimitReachedError,
    RenderError,
    TimeoutError,
    UnknownBackendError,
    UnsupportedMediaType,
)
from ..models import (
    KitWorkerSettings,
    MainServiceSettings,
    RenderingStatus,
    response_status_gauge,
)
from .config import CACHE_MAXSIZE, CACHE_TTL, get_api_description, get_package_version
from .health import router as health_router
from .info import router as info_router
from .mdl import router as mdl_router
from .usdsearch import router as usdsearch_router
from .utils import AccessLogFilter, TooManyRequestsLogFilter

logger = logging.getLogger(__name__)

global_settings = MainServiceSettings()
worker_settings = KitWorkerSettings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(AccessLogFilter())
    uvicorn_access_logger.addFilter(TooManyRequestsLogFilter())
    # Create cache instance
    instrumentator.expose(app, tags=["internal_metrics"], include_in_schema=False)
    app.state.cache = TTLCache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)
    app.state.semaphore = Semaphore(worker_settings.n_workers)
    app.state.kit_worker_settings = worker_settings
    for rendering_status in RenderingStatus:
        response_status_gauge.labels(status=rendering_status.value).set(0)
    yield
    # Cleanup (if needed)
    app.state.cache.clear()


app = FastAPI(
    title="USD Search Rendering Service",
    description=get_api_description(),
    version=get_package_version(),
    lifespan=lifespan,
)

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


@app.exception_handler(LoadError)
async def load_error_handler(request: Request, exc: LoadError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.load_error.value).inc()
    content = {
        "error": RenderingStatus.load_error,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


@app.exception_handler(InvalidMTLNames)
async def invalid_mtl_names_error_handler(request: Request, exc: InvalidMTLNames) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.invalid_mtl_names.value).inc()
    content = {
        "error": RenderingStatus.invalid_mtl_names,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=content,
    )


@app.exception_handler(RenderError)
async def render_error_handler(request: Request, exc: RenderError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.render_error.value).inc()
    content = {
        "error": RenderingStatus.render_error,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


@app.exception_handler(EmptySceneError)
async def empty_scene_error_handler(request: Request, exc: EmptySceneError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.empty_scene.value).inc()
    content = {
        "error": RenderingStatus.empty_scene,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


@app.exception_handler(UnknownBackendError)
async def unknown_backend_error_handler(request: Request, exc: UnknownBackendError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.error.value).inc()
    content = {
        "error": RenderingStatus.error,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


@app.exception_handler(ProcessLimitReachedError)
async def process_limit_reached_error_handler(request: Request, exc: UnknownBackendError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.process_limit_reached.value).inc()
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": RenderingStatus.process_limit_reached,
            "details": str(exc),
            "traceback": exc.traceback,
        },
    )


@app.exception_handler(TimeoutError)
async def timeout_error_handler(request: Request, exc: TimeoutError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.timeout.value).inc()
    content = {
        "error": RenderingStatus.timeout,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


@app.exception_handler(UnsupportedMediaType)
async def unsupported_media_type_error_handler(request: Request, exc: UnsupportedMediaType) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.unsupported_media_type.value).inc()
    content = {
        "error": RenderingStatus.unsupported_media_type,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, content=content)


@app.exception_handler(KitOutOfMemoryError)
async def kit_out_of_memory_error_handler(request: Request, exc: KitOutOfMemoryError) -> JSONResponse:
    response_status_gauge.labels(status=RenderingStatus.out_of_memory.value).inc()
    content = {
        "error": RenderingStatus.out_of_memory,
        "details": str(exc),
        "traceback": exc.traceback,
        "url": exc.url,
    }
    logger.error(json.dumps(content))
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=content)


# Include routers
app.include_router(usdsearch_router)
app.include_router(health_router)
app.include_router(info_router)
app.include_router(mdl_router)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
