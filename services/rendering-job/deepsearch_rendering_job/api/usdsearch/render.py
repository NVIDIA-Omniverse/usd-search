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
import os
import warnings
from tempfile import TemporaryDirectory
from typing import Annotated, Optional

from deepsearch_rendering_job.models import (
    Authentication,
    RenderingRequest,
    RenderingStatus,
)
from deepsearch_rendering_job.render import _render_request
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.security import HTTPBasicCredentials

from ...exceptions import KitOutOfMemoryError, UnknownBackendError, UnsupportedMediaType
from ..auth import http_basic
from ..models import ContentType, SupportedMediaTypes
from ..utils import get_key, prepare_authentication, prepare_rendering_response
from .models import RenderingPostRequest

router = APIRouter()


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
    kit_worker_memory_limit: Annotated[Optional[int], Query(description="Kit worker memory limit in MB", gt=0)] = None,
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

    if url.endswith(".mdl"):
        warnings.warn(f"this is an MDL file '{url}', consider using the MDL render endpoint instead")

    if content_type not in SupportedMediaTypes:
        raise UnsupportedMediaType(
            f"Unsupported media type: {content_type}, expected: {SupportedMediaTypes.json} or {SupportedMediaTypes.zip}",
            traceback=None,
        )

    auth: Authentication = prepare_authentication(basic_auth, x_basic_auth, url)

    # Check cache first
    cache_key = get_key(url, auth)
    if cache_key in fastapi_request.app.state.cache and not force_render and enable_caching:
        return prepare_rendering_response(
            cache_key=cache_key,
            cache=fastapi_request.app.state.cache,
            url=url,
            content_type=content_type.value,
        )

    # If not in cache, render the asset
    with TemporaryDirectory() as temp_dir:
        status: RenderingStatus = await _render_request(
            request=RenderingRequest(url_list=[url], local_path=temp_dir),
            auth=auth,
            semaphore=fastapi_request.app.state.semaphore,
            worker_settings=fastapi_request.app.state.kit_worker_settings,
            asset_rendering_timeout=asset_rendering_timeout,
            kit_worker_memory_limit=kit_worker_memory_limit,
        )
        if status is RenderingStatus.out_of_memory:
            raise KitOutOfMemoryError("Process was killed due to out of memory", traceback=None, url=url)

        # Read the data from the file that was written by the rendering service
        asset_path = os.path.join(temp_dir, get_key(url))

        if not os.path.exists(asset_path):
            raise UnknownBackendError("Rendering failed - no output file generated", traceback=None, url=url)

        with open(asset_path, "r") as f:
            response_data = json.load(f)

        payload: ContentType = ContentType(**response_data["payload"])

        # Use the same prepare_rendering_response function
        return prepare_rendering_response(
            payload=payload,
            cache_key=cache_key,
            cache=fastapi_request.app.state.cache,
            url=url,
            content_type=content_type.value,
            enable_caching=enable_caching,
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
        content_type=content_type,
        url=request.url,
        force_render=request.force_render,
        enable_caching=request.enable_caching,
        fastapi_request=fastapi_request,
        asset_rendering_timeout=request.asset_rendering_timeout,
        kit_worker_memory_limit=request.kit_worker_memory_limit,
    )
