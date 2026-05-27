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
from tempfile import TemporaryDirectory
from typing import Annotated, List, Optional

from deepsearch_rendering_job.models import Authentication, RenderingRequest
from deepsearch_rendering_job.render import _render_request
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.security import HTTPBasicCredentials

from ...exceptions import UnknownBackendError, UnsupportedMediaType
from ..auth import http_basic
from ..models import ContentType, SupportedMediaTypes
from ..utils import get_key, prepare_authentication, prepare_rendering_response
from .models import BaseObjectType, MDLRenderingPostRequest

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
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "MTL names are not part of the MDL file",
            "content": {
                "application/json": {
                    "description": "Error response",
                    "example": {
                        "error": "InvalidMTLNames",
                        "details": "MTL names are not part of the MDL file",
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
    mtl_names: Annotated[
        Optional[List[str]],
        Query(
            description="MTL name that need to be rendered.",
            openapi_examples={
                "None": {
                    "summary": "No mtl names",
                    "value": [],
                },
                "MTL names": {
                    "summary": "MTL names that are part of the MDL file",
                    "value": ["Brushed_Antique_Copper"],
                },
            },
        ),
    ] = None,
    width: Annotated[int, Query(description="Width of the thumbnail", gt=0)] = 448,
    height: Annotated[int, Query(description="Height of the thumbnail", gt=0)] = 448,
    base_object_type: Annotated[
        Optional[BaseObjectType],
        Query(description="Base object type that need to be rendered."),
    ] = None,
    mdl_template_url: Annotated[Optional[str], Query(description="Template URL that need to be rendered.")] = None,
    mdl_stdin: Annotated[Optional[str], Query(description="STDIN that need to be rendered.")] = None,
    fastapi_request: Request = None,
) -> Response:
    """
    Render an MDL file and return its images and metadata.

    This endpoint renders 3D assets from a given MDL file and returns the rendered images
    either as base64-encoded JSON or as a zip archive containing the image files.

    The rendering process supports caching to improve performance and can handle
    selected MTL names for MDL assets. If no MTL names are provided, all materials stored in the MDL file will be rendered.
    """
    if content_type not in SupportedMediaTypes:
        raise UnsupportedMediaType(
            f"Unsupported media type: {content_type}, expected: {SupportedMediaTypes.json} or {SupportedMediaTypes.zip}",
            traceback=None,
        )

    auth: Authentication = prepare_authentication(basic_auth, x_basic_auth, url)

    # If not in cache, render the asset
    with TemporaryDirectory() as temp_dir:

        if mdl_template_url is None and mdl_stdin is None and base_object_type is not None:
            if base_object_type == BaseObjectType.shaderknob:
                mdl_template_url = "/data/usd/scene.usd"
                mdl_stdin = "/World/Xform/shaderball_Mesh"
        elif base_object_type is not None:
            raise ValueError(
                "Both base_object_type and mdl_template_url/mdl_stdin are provided. Only one of them is allowed."
            )

        await _render_request(
            request=RenderingRequest(
                url_list=[url],
                local_path=temp_dir,
                mtl_name_dict={url: mtl_names},
                width=width,
                height=height,
                mdl_template_url=mdl_template_url,
                mdl_stdin=mdl_stdin,
            ),
            auth=auth,
            semaphore=fastapi_request.app.state.semaphore,
            worker_settings=fastapi_request.app.state.kit_worker_settings,
        )

        # Read the data from the file that was written by the rendering service
        asset_path = os.path.join(temp_dir, get_key(url))

        if not os.path.exists(asset_path):
            raise UnknownBackendError("Rendering failed - no output file generated", traceback=None)

        with open(asset_path, "r") as f:
            response_data = json.load(f)

        payload: ContentType = ContentType(**response_data["payload"])

        # Use the same prepare_rendering_response function
        return prepare_rendering_response(
            payload=payload,
            url=url,
            content_type=content_type.value,
            enable_caching=False,
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
    request: MDLRenderingPostRequest,
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
    """
    Render an MDL file and return its images and metadata.

    This endpoint renders 3D assets from a given MDL file and returns the rendered images
    either as base64-encoded JSON or as a zip archive containing the image files.

    The rendering process supports caching to improve performance and can handle
    selected MTL names for MDL assets. If no MTL names are provided, all materials stored in the MDL file will be rendered.
    """
    return await render(
        basic_auth=basic_auth,
        x_basic_auth=x_basic_auth,
        content_type=content_type,
        url=request.url,
        fastapi_request=fastapi_request,
        mtl_names=request.mtl_names,
        width=request.width,
        height=request.height,
        base_object_type=request.base_object_type,
        mdl_template_url=request.mdl_template_url,
        mdl_stdin=request.mdl_stdin,
    )
