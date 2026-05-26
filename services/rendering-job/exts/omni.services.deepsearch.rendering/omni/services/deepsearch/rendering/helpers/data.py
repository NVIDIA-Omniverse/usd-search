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

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

# third part modules
import pydantic


class Sensors(str, Enum):
    rgb = "images"
    semantic_segmentation = "segmentation"
    distance_to_camera = "depth"
    distance_to_image_plane = "linear_depth"
    normals = "normal"
    camera_params = "camera_metadata"
    pointcloud = "pointcloud"
    bounding_box_2d_tight_fast = "bounding_box_2d_tight_fast"


class Status(str, Enum):
    ok = "ok"
    incomplete_data = "incomplete_data"
    data_retrieval_error = "data_retrieval_error"
    syntheticdata_timeout_error = "syntheticdata_timeout_error"
    unknown_error = "unknown_error"


class GetDataResponse(pydantic.BaseModel):
    status: Status = pydantic.Field(..., description="status of the operation")
    data: Dict[str, Any] = pydantic.Field(..., description="rendered data")


class ModeType(str, Enum):
    combined = "combined"


@dataclass
class BBox:
    xmin: float
    ymin: float
    xmax: float
    ymax: float


class CameraPosition(pydantic.BaseModel):
    az: float = pydantic.Field(..., title="azimuth of the camera on the surrounding sphere")
    el: float = pydantic.Field(..., title="elevation of the camera on the surrounding sphere")

    def __repr__(self) -> str:
        return f"[az: {self.az}; el: {self.el}]"


class CameraParameters(pydantic.BaseModel):
    width: int = pydantic.Field(..., title="camera width in pixels")
    height: int = pydantic.Field(..., title="camera height in pixels")


class CameraPlacingStrategy(str, Enum):
    manual = "manual"
    random = "random"


class CenterInfo(pydantic.BaseModel):
    all_inside: bool = pydantic.Field(..., title="Flag to show that all the pixels of the object are inside the vide")
    center: Optional[Tuple[float, float]] = pydantic.Field(default=None, title="Center location")
    offset: Optional[Tuple[float, float]] = pydantic.Field(default=None, title="Offset from the image center")
    offset_norm: Optional[float] = pydantic.Field(default=None, title="Norm of the Offset from the image center")
