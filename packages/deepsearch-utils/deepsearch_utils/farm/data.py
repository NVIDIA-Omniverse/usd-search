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

import os

# standard modules
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypedDict

# third party modules
import pydantic

# local / proprietary modules
from search_utils.misc_utils import str2bool

DEBUG_SAVE_FARM_DATA = str2bool(os.getenv("DEBUG_SAVE_FARM_DATA", "False"))
DEBUG_SAVE_FARM_DATA_FOLDER = os.getenv("DEBUG_SAVE_FARM_DATA_FOLDER", "/tmp")


# different response statuses
class ResponseStatus(Enum):
    success = "success"
    ok = "ok"
    error = "error"
    archival_error = "archival_error"
    cancellation_error = "cancellation_error"
    connection_error = "connection_error"
    empty_scene = "empty_scene"
    timeout = "timeout"
    load_error = "load_error"


class FarmResultContent(TypedDict):
    content: Any
    path: str


class FarmResponse(TypedDict):
    request: str
    payload: FarmResultContent


class ServerResponses(str, Enum):
    load_error = "load_error"
    rendering_error = "rendering_error"
    empty = ""


class ProcessedItemContent(TypedDict):
    status: ResponseStatus
    response: Dict[str, str]


class RenderingJob(pydantic.BaseModel):
    uri: Optional[str] = None
    token: Optional[str] = None


class ServerConfig(pydantic.BaseModel):
    url: str = pydantic.Field(..., description="Receiving server URL")
    get_item: Callable = pydantic.Field(..., description="Method for getting item")
    del_item: Callable = pydantic.Field(..., description="Method for deleting item")
    external_url: str = pydantic.Field(..., description="External URL of the receiving server")


class CameraPlacingStrategy(str, Enum):
    manual = "manual"
    random = "random"


class CameraPosition(pydantic.BaseModel):
    az: float = pydantic.Field(..., title="azimuth of the camera on the surrounding sphere")
    el: float = pydantic.Field(..., title="elevation of the camera on the surrounding sphere")


class RenderSettings(pydantic.BaseModel):
    adjust_camera_multiplier: bool = pydantic.Field(default=True, title="trigger to automatically adjust camera view")
    render_existing_views: bool = pydantic.Field(
        default=True, title="trigger to automatically render existing camera views"
    )
    camera_positions: List[CameraPosition] = pydantic.Field(
        default=None, title="list of cameras that need to be rendered"
    )
    camera_placing_strategy: CameraPlacingStrategy = pydantic.Field(
        default=CameraPlacingStrategy.manual, title="camera placing strategy"
    )
    n_random_cameras: int = pydantic.Field(default=1, title="number of random strategies")
    force_regenerate: bool = pydantic.Field(default=False, title="if True - skip existing data in Cache")


# set of errors that Farm client can raise
class FarmUnavailable(ConnectionError):
    pass


class ContentException(Exception):
    def __init__(self, content: Dict[str, Any] = None, errors=None):
        super().__init__(str(content))
        if content is None:
            self.content = {}
        else:
            self.content = content
        self.errors = errors


class RenderingError(ContentException):
    pass


class EmptyScene(ContentException):
    pass


class TaskSubmissionError(ConnectionError):
    pass


class FarmTimeoutError(ContentException):
    pass


class RunSingleError(ContentException):
    pass


class LoadError(ContentException):
    pass
