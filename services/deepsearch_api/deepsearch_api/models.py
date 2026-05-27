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

"""Pydantic models shared across multiple deepsearch-api subpackages.

These were previously housed in the legacy ``routers_v1.base_models`` module
alongside V1-specific request/response shapes that have since been retired.
``Prim`` is consumed by ``search_backend/models_extra.py``,
``search_backend/filtered.py``, ``routers_v2/service.py``, and
``routers_v2/models.py``. ``Prediction`` is consumed by
``search_backend/embeddings.py`` and ``routers_v2/models.py``.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Prediction(BaseModel):
    tag: str = Field(description="The tag of the prediction")
    prob: float = Field(description="The probability of the prediction")


class Prim(BaseModel):
    scene_url: str
    scene_mpu: float
    usd_path: str
    prim_type: str
    bbox_max: List[float]
    bbox_min: List[float]
    bbox_midpoint: List[float]
    bbox_dimension_x: float
    bbox_dimension_y: float
    bbox_dimension_z: float
    scaled_bbox_dimension_x: float
    scaled_bbox_dimension_y: float
    scaled_bbox_dimension_z: float
    source_asset_url: Optional[str] = None
    properties: Optional[Dict[str, Any]] = None
    root_prim: Optional[bool] = None
    default_prim: Optional[bool] = None
