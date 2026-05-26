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

import logging
from enum import Enum
from typing import Optional

from fastapi import APIRouter
from fastapi.params import Query
from pydantic import BaseModel, Field, field_validator

api_v1_router = APIRouter()

logger = logging.getLogger(__name__)


class MatrixField(BaseModel):
    transformation_matrix: str = Query(
        default="1,0,0;0,1,0;0,0,1",
        description="Transformation matrix for the vector space. By default does not apply any transformation.",
    )

    @field_validator("transformation_matrix")
    def check_matrix_format(cls, v):
        rows = v.split(";")
        if len(rows) != 3:
            raise ValueError("The matrix must have three rows.")
        for row in rows:
            elements = row.split(",")
            if len(elements) != 3:
                raise ValueError("Each row must have three columns.")
            for element in elements:
                try:
                    float(element)  # Ensure each element is a float
                except ValueError:
                    raise ValueError("All elements must be numeric.")
        return v


class CommonPrimFilter(BaseModel):
    prim_type: Optional[str] = Field(
        Query(
            default=None,
            description="Retrieve prims of the specified type",
            examples=["Xform", "Mesh"],
        )
    )
    properties_filter: Optional[str] = Field(
        Query(
            default=None,
            description="Filter prims based on USD attributes (note: only a subset of attributes configured in the indexing service is available). Format: `attribute1=abc,attribute2=456`",
            examples=["my_attribute=val1,other_attr=val2"],
        )
    )
    min_bbox_dimension_x: Optional[float] = Field(Query(default=None, description="Minimum bounding box X dimension"))
    min_bbox_dimension_y: Optional[float] = Field(Query(default=None, description="Minimum bounding box Y dimension"))
    min_bbox_dimension_z: Optional[float] = Field(Query(default=None, description="Minimum bounding box Z dimension"))
    max_bbox_dimension_x: Optional[float] = Field(Query(default=None, description="Max bounding box X dimension"))
    max_bbox_dimension_y: Optional[float] = Field(Query(default=None, description="Max bounding box Y dimension"))
    max_bbox_dimension_z: Optional[float] = Field(Query(default=None, description="Max bounding box Z dimension"))

    @field_validator("properties_filter")
    def validate_properties_filter(cls, v):
        if v is None:
            return v
        parts = v.split(",")
        for part in parts:
            if "=" not in part:
                raise ValueError("Each attribute must be in the format 'key=value'.")
            key, value = part.split("=", 1)
            if not key or not value:
                raise ValueError("Both key and value must be non-empty.")
        return v

    @property
    def properties(self):
        if self.properties_filter is None:
            return None
        properties_filters = self.properties_filter.split(",")
        return {f.split("=")[0]: f.split("=")[1] for f in properties_filters}


class CommonPrimFilterBoundedBbox(CommonPrimFilter):
    # For spatial queries we use a default bbox size limit to filter out prims with infinite size, like materials etc.
    max_bbox_dimension_x: Optional[float] = Field(Query(default=4e38, description="Max bounding box X dimension"))
    max_bbox_dimension_y: Optional[float] = Field(Query(default=4e38, description="Max bounding box Y dimension"))
    max_bbox_dimension_z: Optional[float] = Field(Query(default=4e38, description="Max bounding box Z dimension"))


class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"
    PARENT = "parent_prim"
    ROOT_PRIM = "root_prim"
    SOURCE_ASSET = "source_asset"


class Asset(BaseModel):
    url: str
    deleted: bool = False


class AssetRelationship(BaseModel):
    node_1_url: str
    node_2_url: str
    type: EdgeType


class AssetGraph(BaseModel):
    nodes: list[Asset]
    edges: list[AssetRelationship]
