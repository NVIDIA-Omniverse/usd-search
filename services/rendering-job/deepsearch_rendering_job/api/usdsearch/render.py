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
import time
import warnings
from tempfile import TemporaryDirectory
from typing import Annotated, Optional

from deepsearch_rendering_job.exceptions import ProcessLimitReachedError
from deepsearch_rendering_job.models import (
    Authentication,
    RenderingRequest,
    RenderingStatus,
)
from deepsearch_rendering_job.render import _render_request
from deepsearch_rendering_job.utils import redact_url
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasicCredentials
from starlette.background import BackgroundTask

from ..auth import http_basic
from ..models import ContentType, SupportedMediaTypes
from ..utils import get_key, prepare_authentication, prepare_rendering_response
from .models import RenderingPostRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _log_response_sent(url: str, t_start: float) -> None:
    logger.info("Response fully sent for '%s' in %.2fs", redact_url(url), time.time() - t_start)


def _with_send_tracking(resp: Response, url: str, t_start: float) -> Response:
    """Attach a BackgroundTask to a Starlette Response. Converts Pydantic models first."""
    if not isinstance(resp, Response):
        resp = JSONResponse(content=jsonable_encoder(resp))
    resp.background = BackgroundTask(_log_response_sent, url, t_start)
    return resp


@router.get(
    "/render",
    responses={
        status.HTTP_200_OK: {
            "description": "Successful render response",
            "content": {
                "application/json": {
                    "description": "Render response",
                    "example": {
                        "images": [
                            "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgHBgkIBwgKCgkLDRYPDQwMDRsUFRAWIB0iIiAdHx8kKDQsJCYxJx8fLT0tMTU3Ojo6Iys/BQYH/8QAtRABAAIB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5Pj/3",
                            "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgHBgkIBwgKCgkLDRYPDQwMDRsUFRAWIB0iIiAdHx8kKDQsJCYxJx8fLT0tMTU3Ojo6Iys/BQYH/8QAtRABAAIB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5Pj/3",
                        ],
                        "status": "success",
                    },
                },
                "application/zip": {
                    "description": "Zip archive containing rendered images",
                    "example": "Binary zip file content",
                },
            },
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "description": "Bad request or unsupported media type",
            "content": {
                "application/json": {
                    "description": "Error response",
                    "example": {
                        "error": "UnsupportedMediaType",
                        "details": "Unsupported media type: application/xml, expected: application/json or application/zip",
                    },
                },
            },
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Error response",
            "content": {
                "application/json": {
                    "description": "Error response",
                    "example": {
                        "error": "error",
                        "details": "details",
                        "traceback": "traceback",
                    },
                },
            },
        },
    },
)
async def render(
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    url: Annotated[str, Query(description="URL of an asset that needs to be rendered")],
    x_basic_auth: Annotated[Optional[str], Header(description="Authorization header", alias="X-Basic-Auth")] = None,
    x_token_auth: Annotated[
        Optional[str], Header(description="Bearer token for the Storage API backend", alias="X-Token-Auth")
    ] = None,
    content_type: Annotated[
        SupportedMediaTypes,
        Header(
            description="Response format: application/json for base64 images, application/zip for zip archive",
            alias="X-Response-Format",
        ),
    ] = SupportedMediaTypes.json,
    force_render: Annotated[bool, Query(description="Force render the asset")] = False,
    enable_caching: Annotated[bool, Query(description="Enable caching")] = True,
    fastapi_request: Request = None,
    asset_rendering_timeout: Annotated[Optional[float], Query(description="Asset rendering timeout", gt=0)] = None,
    kit_worker_memory_limit: Annotated[
        Optional[int], Query(description="Render worker memory limit in MB", gt=0)
    ] = None,
    storage_api_url: Annotated[
        Optional[str],
        Query(description="Storage API endpoint to open the asset from (Storage API backend only)"),
    ] = None,
    discovery_url: Annotated[
        Optional[str],
        Query(
            description="Discovery Service base URL that advertises the Storage API; "
            "optional for open Storage API endpoints that do not require it"
        ),
    ] = None,
) -> Response:
    """
    Render a URL and return its images and metadata.

    Args:
        url: The URL to render
        content_type: Response format (application/json or application/zip)
        x_basic_auth: Authorization header
        force_render: Whether to force re-rendering even if cached
        enable_caching: Whether to enable caching
        fastapi_request: The FastAPI request object

    Returns:
        RenderResponse containing the rendered payload or StreamingResponse with zip archive
    """

    semaphore = fastapi_request.app.state.semaphore

    if url.endswith(".mdl"):
        warnings.warn(f"this is an MDL file '{redact_url(url)}', consider using the MDL render endpoint instead")

    if content_type not in SupportedMediaTypes:
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "error": f"Unsupported media type: {content_type}, expected: {SupportedMediaTypes.json} or {SupportedMediaTypes.zip}",
                "url": url,
            },
        )

    if not enable_caching or force_render:
        n_waiters = semaphore.waiters
        n_allowed = fastapi_request.app.state.worker_settings.n_allowed_waiting_requests
        if semaphore.value == 0 and n_allowed >= 0 and n_waiters >= n_allowed:
            raise ProcessLimitReachedError(f"Too many waiting requests: {n_waiters} > {n_allowed}")

    auth: Authentication = prepare_authentication(
        basic_auth,
        x_basic_auth,
        url,
        x_token_auth=x_token_auth,
        storage_api_url=storage_api_url,
        discovery_url=discovery_url,
    )

    # Check cache first
    cache_key = get_key(url, auth)
    if enable_caching and not force_render and cache_key in fastapi_request.app.state.cache:
        t_start_send = time.time()
        logger.info("Sending cached response for '%s'", redact_url(url))
        return _with_send_tracking(
            prepare_rendering_response(
                cache_key=cache_key, cache=fastapi_request.app.state.cache, url=url, content_type=content_type.value
            ),
            url,
            t_start_send,
        )

    # If not in cache, render the asset
    with TemporaryDirectory() as temp_dir:
        await _render_request(
            request=RenderingRequest(url_list=[url], local_path=temp_dir),
            auth=auth,
            semaphore=fastapi_request.app.state.semaphore,
            worker_settings=fastapi_request.app.state.worker_settings,
            asset_rendering_timeout=asset_rendering_timeout,
            kit_worker_memory_limit=kit_worker_memory_limit,
        )
        # Read the data from the file that was written by the rendering service
        asset_path = os.path.join(temp_dir, get_key(url))

        if not os.path.exists(asset_path):
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": RenderingStatus.error,
                    "details": "Rendering failed - no output file generated",
                    "url": url,
                },
            )

        with open(asset_path, "r", encoding="UTF-8") as f:
            response_data = json.load(f)

        payload: ContentType = ContentType(**response_data["payload"])

        # Use the same prepare_rendering_response function
        t_start_send = time.time()
        logger.info("Sending rendered response for '%s'", redact_url(url))
        return _with_send_tracking(
            prepare_rendering_response(
                payload=payload,
                cache_key=cache_key,
                cache=fastapi_request.app.state.cache,
                url=url,
                content_type=content_type.value,
                enable_caching=enable_caching,
            ),
            url,
            t_start_send,
        )


@router.post(
    "/render",
    responses={
        status.HTTP_200_OK: {
            "description": "Successful render response",
            "content": {
                "application/json": {
                    "description": "Render response",
                    "example": {
                        "images": [
                            "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgHBgkIBwgKCgkLDRYPDQwMDRsUFRAWIB0iIiAdHx8kKDQsJCYxJx8fLT0tMTU3Ojo6Iys/BQYH/8QAtRABAAIB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5Pj/3",
                            "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBwgHBgkIBwgKCgkLDRYPDQwMDRsUFRAWIB0iIiAdHx8kKDQsJCYxJx8fLT0tMTU3Ojo6Iys/BQYH/8QAtRABAAIB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5Pj/3",
                        ],
                        "status": "success",
                    },
                },
                "application/zip": {
                    "description": "Zip archive containing rendered images",
                    "example": "Binary zip file content",
                },
            },
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "description": "Bad request or unsupported media type",
            "content": {
                "application/json": {
                    "description": "Error response",
                    "example": {
                        "error": "UnsupportedMediaType",
                        "details": "Unsupported media type: application/xml, expected: application/json or application/zip",
                    },
                },
            },
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Error response",
            "content": {
                "application/json": {
                    "description": "Error response",
                    "example": {
                        "error": "error",
                        "details": "details",
                        "traceback": "traceback",
                    },
                },
            },
        },
    },
)
async def render_post(
    request: RenderingPostRequest,
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    x_basic_auth: Annotated[Optional[str], Header(description="Authorization header", alias="X-Basic-Auth")] = None,
    x_token_auth: Annotated[
        Optional[str], Header(description="Bearer token for the Storage API backend", alias="X-Token-Auth")
    ] = None,
    content_type: Annotated[
        SupportedMediaTypes,
        Header(
            description="Response format: application/json for base64 images, application/zip for zip archive",
            alias="X-Response-Format",
        ),
    ] = SupportedMediaTypes.json,
    fastapi_request: Request = None,
):
    return await render(
        basic_auth=basic_auth,
        x_basic_auth=x_basic_auth,
        x_token_auth=x_token_auth,
        content_type=content_type,
        url=request.url,
        force_render=request.force_render,
        enable_caching=request.enable_caching,
        fastapi_request=fastapi_request,
        asset_rendering_timeout=request.asset_rendering_timeout,
        kit_worker_memory_limit=request.kit_worker_memory_limit,
        storage_api_url=request.storage_api_url,
        discovery_url=request.discovery_url,
    )
