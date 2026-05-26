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

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from importlib.metadata import version
from time import time
from typing import Any

from asgi_correlation_id import CorrelationIdMiddleware, correlation_id
from asset_graph_service.api.dependencies import database
from asset_graph_service.api.endpoints import api_v1_router
from asset_graph_service.api.exceptions import NotFoundError
from asset_graph_service.api.healthchecks import healthchecks_router
from asset_graph_service.api.profiling import get_profiling_middleware
from asset_graph_service.api.tracing import provider
from asset_graph_service.db.neo4j import Neo4jDBBackend, Neo4jSettings, get_settings
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi_swagger import patch_fastapi
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import model_validator
from pydantic_settings import BaseSettings
from starlette import status
from starlette.requests import Request
from starlette.responses import JSONResponse

SENTRY_DSN = os.getenv("SENTRY_DSN")
logger = logging.getLogger(__name__)

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


from base_logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.config = AppConfig()
    app.neo4j_settings = Neo4jSettings()
    db = Neo4jDBBackend(app.neo4j_settings)
    async with db.session() as session:
        await session.setup()
        await session.close()
    yield


class AppConfig(BaseSettings):
    verify_access: bool = False
    verify_access_endpoint: str = ""

    @model_validator(mode="after")
    def validate(self) -> AppConfig:
        if self.verify_access and not self.verify_access_endpoint:
            raise ValueError("verify_access_endpoint is required when verify_access is True")
        return self


def get_version():
    try:
        return version("asset_graph_service")
    except Exception as e:
        return "0.0.0-unknown"


profiling_middleware = get_profiling_middleware()

openapi_tags = [
    {
        "name": "AGS Spatial Graph",
        "description": "Spatial graph queries APIs.",
    },
    {
        "name": "AGS Scene Graph",
        "description": "Scene graph queries APIs.",
    },
    {
        "name": "AGS Asset Graph",
        "description": "Asset graph/dependencies graph queries APIs.",
    },
]

app = FastAPI(
    title="Asset Graph Service API",
    description="""
The **Asset Graph Service (AGS) API** provides advanced querying capabilities for assets and USD trees indexed in a graph database. It supports proximity queries based on coordinates or prims to find objects within specified areas or radii, sorted by distance, and includes transformation options for vector alignment. The API also offers dependency and reverse dependency searches, helping to identify all assets referenced in a scene or scenes containing a particular asset, which can optimize scene loading and track dependency changes. By combining different query types, the AGS API enables complex scenarios for scene understanding, manipulation, and generation. It can also be integrated with DeepSearch to provide in-scene search functionality.

## Features

- **Proximity Queries:**
  - Find objects within a specified bounding box or radius.
  - Results sorted by distance with options for vector alignment using a transformation matrix.

- **USD Property Queries:** 
    - Enables querying objects in a 3D scene using USD properties, such as finding all assets with a specific semantic label.
     
- **Asset Dependency Searches:**
  - Identify all assets referenced in a scene - including USD references, material references, or textures.
  - Reverse search to find all scenes containing a particular asset.

- **Combined Query Capabilities:**
  - Enable complex scenarios for enhanced scene understanding, manipulation, and generation.

- **Integration with DeepSearch:**
  - Provides in-scene search functionality.
""",
    lifespan=lifespan,
    version=get_version(),
    docs_url=None,
    swagger_ui_oauth2_redirect_url=None,
    openapi_tags=openapi_tags,
)
app.middleware("http")(profiling_middleware)


app.include_router(healthchecks_router)
app.include_router(api_v1_router)
Instrumentator().instrument(app).expose(app, include_in_schema=False)


request_duration_logger = logging.getLogger("asset_graph_service.api.request_duration_logger")

patch_fastapi(app)


@app.middleware("http")
async def response_duration_logging_middleware(request: Request, call_next):
    start_time = time()
    response = await call_next(request)
    process_time = time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    if any(path in request.url.path for path in ["readyz", "livez", "metrics"]):
        return response
    request_duration_logger.info("Request duration:\t%ss", process_time)
    return response


requests_logger = logging.getLogger("asset_graph_service.api.requests_logger")


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    log_requests = os.getenv("LOG_REQUESTS", "false").lower() == "true"

    excluded_paths = set(["readyz", "livez", "health", "metrics"])
    is_internal_request = any(path in request.url.path for path in excluded_paths)

    if log_requests and not is_internal_request:
        log_content = {
            "url": str(request.url),
            "endpoint": request.url.path,
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


@app.middleware("http")
async def add_request_id_to_span(request: Request, call_next):
    request_id = correlation_id.get()
    if request_id:
        trace.get_current_span().set_attribute("http.request_id", request_id)
    return await call_next(request)


FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


@app.exception_handler(ValueError)
async def validation_exception_handler(request: Request, exc: ValueError):
    if not hasattr(exc, "errors"):
        raise exc

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=jsonable_encoder({"detail": exc.errors()}),
    )


@app.exception_handler(NotFoundError)
async def validation_exception_handler(request: Request, exc: NotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=jsonable_encoder(
            {
                "error": {
                    "code": exc.__class__.__name__,
                    "message": str(exc),
                    "target": exc.target,
                }
            }
        ),
    )
