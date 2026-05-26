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

from enum import Enum

# import standard packages
from typing import Dict, List, Optional

# third party modules
from pydantic import BaseModel, BaseSettings, Field

# local/ proprietary modules
from ..helpers.data import CameraParameters, CameraPlacingStrategy, CameraPosition


class Auth(BaseModel):
    username: str = Field(default=None, title="Omniverse user name")
    auth_token: str = Field(default=None, title="User access token")


class RenderSettings(BaseModel):
    adjust_camera_multiplier: bool = Field(default=True, title="trigger to automatically adjust camera view")
    render_existing_views: bool = Field(default=True, title="trigger to automatically render existing camera views")
    filter_by_segmentation: bool = Field(default=False, title="If True, drop views where the semantic mask is empty")
    camera_positions: Optional[List[CameraPosition]] = Field(
        default=None, title="list of cameras that need to be rendered"
    )
    camera_placing_strategy: str = Field(default=CameraPlacingStrategy.manual, title="camera placing strategy")
    n_random_cameras: int = Field(default=1, title="number of random strategies")
    force_regenerate: bool = Field(default=False, title="if True - skip existing data in Cache")
    camera_parameters: Optional[CameraParameters] = Field(default=None, title="camera parameters")
    sensors: Optional[List[str]] = Field(default=None, title="List of required sensors")
    width: int = Field(default=448, title="Width of the thumbnail")
    height: int = Field(default=448, title="Height of the thumbnail")
    mdl_template_url: Optional[str] = Field(
        default=None,
        title="Template URL that need to be rendered. Only relevant for MDL files",
    )
    mdl_stdin: Optional[str] = Field(
        default=None,
        title="STDIN that need to be rendered. Only relevant for MDL files",
    )


class RequestRenderUSD(BaseModel):
    url: str = Field(..., title="USD path that need to be rendered.")
    mtl_name: Optional[List[str]] = Field(
        default=None,
        title="MTL name that need to be rendered. Only relevant for MDL files",
    )
    ws: str = Field(default=None, title="Websocket endpoint, where results need to be posted")
    http: str = Field(default=None, title="HTTP endpoint, where results need to be posted")
    redis: str = Field(default=None, title="REDIS URL, where results need to be pushed")
    local_path: str = Field(default=None, title="Local path to the asset")
    n_retries: int = Field(default=100, title="Number of connection retries")
    auth: Auth = Field(default=Auth(), title="user authentication")
    render_settings: RenderSettings = Field(default=RenderSettings(), title="rendering settings")


class BatchRequestRenderUSD(BaseModel):
    url_list: List[str] = Field(..., title="list of USD paths that need to be rendered.")
    url_list_path_override: Optional[list] = Field(
        default=None,
        title="In case the input URL is not in USD format the the asset URL may be different from the actual converted asset URL. The list of URL overrides provides the list of original assets that are being rendered.",
    )
    mtl_name_dict: Dict[str, Optional[List[str]]] = Field(default=None, title="MTL name that need to be rendered.")
    ws: str = Field(default=None, title="Websocket endpoint, where results need to be posted")
    http: str = Field(default=None, title="HTTP endpoint, where results need to be posted")
    redis: str = Field(default=None, title="REDIS URL, where results need to be pushed")
    local_path: str = Field(default=None, title="Local path to the asset")
    n_retries: int = Field(default=100, title="Number of connection retries")
    auth: Auth = Field(default=Auth(), title="user authentication")
    render_settings: RenderSettings = Field(default=RenderSettings(), title="rendering settings")


class GetUSDRenderings(BaseModel):
    url_hash: str = Field(..., title="Hash of the URL, which is a key that is stored in cache")


class ContentType(BaseModel):
    path: str = Field(..., title="URL of the asset that is being loaded")
    content: str = Field(..., title="serialized content of rendered data")
    exception: Optional[str] = Field(default=None, title="exception message")
    traceback: Optional[str] = Field(default=None, title="traceback of the exception")


class ResponsePayload(BaseModel):
    request: str = Field(..., title="request type")
    url: str = Field(..., title="URL of the asset that is being loaded")
    url_hash: str = Field(..., title="Hash of the URL that can be used as a key")
    payload: ContentType = Field(..., title="rendered data")


class ResponseStatus(str, Enum):
    ok = "ok"
    error = "error"
    transport_error = "transport_error"
    payload_to_large = "payload_to_large"


class MDLConfig(BaseSettings):
    mdl_template_url: Optional[str] = Field(
        default=None,
        title="Template URL that need to be rendered. Only relevant for MDL files",
    )
    mdl_stdin: Optional[str] = Field(
        default=None,
        title="STDIN that need to be rendered. Only relevant for MDL files",
    )
