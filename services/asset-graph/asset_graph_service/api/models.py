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

from typing import Optional

from asset_graph_service.db import Prim, PrimCreateModel
from asset_graph_service.db.models import AXIS, Asset, AssetRelationship
from fastapi import Query
from pydantic import BaseModel, validator
from pydantic.fields import Field


class UpdateDependencyGraphRequest(BaseModel):
    scene_url: str
    scene_mpu: float | None = None
    scene_up_axis: AXIS | None = None
    default_prim_path: str | None = None
    total_polygon_count: int = Field(
        default=0,
        description="Total polygon count across all geometry in the USD scene",
    )
    total_point_count: int = Field(
        default=0,
        description="Total point count across all Points prims in the USD scene",
    )
    total_curve_segment_count: int = Field(
        default=0,
        description="Total curve segment count across all Curves prims in the USD scene",
    )
    assets: list[Asset]
    asset_relationships: list[AssetRelationship]
    prims: Optional[dict[str, PrimCreateModel]] = Field(default_factory=dict)


class SpatialQueryResponseItem(BaseModel):
    prim: Prim
    distance: float = Field(description="Distance from the query center to the bounding box midpoint of the result.")
    vector: list[float] = Field(
        description="Vector from the query center to the result. If the `transformation_matrix` argument is provided, the vector is transformed using the given matrix."
    )


class MatrixField(BaseModel):
    transformation_matrix: str = Query(
        default="1,0,0;0,1,0;0,0,1",
        description="Transformation matrix for the vector space. By default does not apply any transformation.",
    )

    @validator("transformation_matrix")
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


class SceneSummaryResponse(BaseModel):
    scene_url: str
    scene_mpu: float | None = Field(description="Scene meters per unit, if available.")
    scene_up_axis: AXIS | None = Field(description="Scene up axis, if available.")
    n_prims: int = Field(description="Number of prims in the scene.")
    total_polygon_count: int = Field(description="Total polygon count across all geometry in the scene.")
    total_point_count: int = Field(description="Total point count across all Points prims in the scene.")
    total_curve_segment_count: int = Field(
        description="Total curve segment count across all Curves prims in the scene."
    )
    prim_types: dict[str, int] = Field(description="Number of prims per type.")
    unique_property_keys: dict[str, int] = Field(description="Number of unique property keys.")
    unique_properties: dict[tuple[str, str | bool], int] = Field(
        description="Number of unique property (key,value) pairs."
    )
    referenced_assets: dict[str, int] = Field(description="Number of unique assets referenced by the scene.")
    default_prim: Prim | None = Field(default=None, description="Default prim of the scene, if any.")
