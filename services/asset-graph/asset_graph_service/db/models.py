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
import re
from enum import Enum

from pydantic import BaseModel, computed_field
from pydantic.fields import Field


class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"
    PARENT = "parent_prim"
    ROOT_PRIM = "root_prim"
    SOURCE_ASSET = "source_asset"


class PropertiesFilterRelation(str, Enum):
    equals = "equals"
    almost_equals = "almost_equals"
    # Numeric relations
    greater_than = "gt"
    greater_equal = "gte"
    less_than = "lt"
    less_equal = "lte"


class PropertiesFilter(BaseModel):
    key: str
    value: str | bool
    relation: PropertiesFilterRelation = PropertiesFilterRelation.equals

    def get_relation(self) -> str:
        relation_map = {
            PropertiesFilterRelation.equals: "=",
            PropertiesFilterRelation.almost_equals: "=~",
            PropertiesFilterRelation.greater_than: ">",
            PropertiesFilterRelation.greater_equal: ">=",
            PropertiesFilterRelation.less_than: "<",
            PropertiesFilterRelation.less_equal: "<=",
        }

        if self.relation in relation_map:
            return relation_map[self.relation]

        raise ValueError(f"'{self.relation}' relation is unknown")

    def is_numeric_relation(self) -> bool:
        """Check if this is a numeric relation that requires numeric indexes."""
        return self.relation in [
            PropertiesFilterRelation.greater_than,
            PropertiesFilterRelation.greater_equal,
            PropertiesFilterRelation.less_than,
            PropertiesFilterRelation.less_equal,
        ]


class Asset(BaseModel):
    """A file node in the asset dependency graph.

    Represents any file tracked by the Asset Graph Service (USD scenes, textures, materials, etc.).
    The `url` uniquely identifies the asset on the storage backend.
    """

    url: str = Field(
        description="Full URL of the asset on the storage backend (e.g., omniverse://server/path/file.usd or s3://bucket/key)"
    )
    deleted: bool = Field(
        default=False,
        description="Whether this asset has been marked as deleted from the storage backend",
    )

    @property
    def extra(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if k not in ["url", "deleted"]}


class AXIS(str, Enum):
    X = "X"
    Y = "Y"
    Z = "Z"


class USDAsset(Asset):
    scene_mpu: float | None
    scene_up_axis: AXIS | None


class AssetRelationship(BaseModel):
    """A directed edge in the asset dependency graph.

    Represents that node_1_url has a reference/dependency on node_2_url via the specified relationship type.
    """

    node_1_url: str = Field(description="URL of the dependent asset (the one that contains the reference)")
    node_2_url: str = Field(description="URL of the dependency (the referenced asset)")
    type: EdgeType = Field(
        description="Relationship type: depends_on (file reference), parent_prim (hierarchy), root_prim, or source_asset"
    )


class AssetGraph(BaseModel):
    """Directed graph of asset dependencies.

    Nodes are files (assets) in the storage backend, edges are reference relationships between them.
    For example, a USD scene depends_on its textures and sub-assembly assets.
    """

    nodes: list[Asset] = Field(description="All assets (files) in the dependency graph")
    edges: list[AssetRelationship] = Field(description="Directed dependency relationships between assets")


class Prim(BaseModel):
    scene_url: str = Field(description="URL of the Prim's scene")
    scene_mpu: float = Field(default=1, description="MPU of the Prim's scene")
    usd_path: str = Field(description="USD path of the prim withn scene `scene_url`. Unique within a single scene.")
    prim_type: str = Field(description="Prim type", examples=["Xform", "Mesh"])
    source_asset_url: str | None = Field(
        default=None,
        description="URL of Prim's source asset (returned only if the prim contains a reference to another asset)",
    )
    properties: dict[str, str | bool] | None = Field(default_factory=dict)
    translate: list[float] = Field(default=[0, 0, 0], description="Translate X, Y, Z world coordinates of the prim")
    rotate_x: float | None = Field(default=None, description="X rotation (degrees) of the prim")
    rotate_y: float | None = Field(default=None, description="Y rotation (degrees) of the prim")
    rotate_z: float | None = Field(default=None, description="Z rotation (degrees) of the prim")
    scale_x: float | None = Field(default=None, description="X scaling of the prim")
    scale_y: float | None = Field(default=None, description="Y scaling of the prim")
    scale_z: float | None = Field(default=None, description="Z scaling of the prim")
    bbox_max: list[float] = Field(description="Max X, Y, Z coordinates of the bounding box")
    bbox_min: list[float] = Field(description="Min X, Y, Z coordinates of the bounding box")
    bbox_midpoint: list[float] = Field(
        description="Midpoint X, Y, Z coordinates of the bounding box, i.e. Prim's location within the scene `scene_url`."
    )
    root_prim: bool | None = Field(default=None, description="Is the prim a root prim for the scene")
    default_prim: bool | None = Field(default=None, description="Is the prim a default prim for the scene")
    polygon_count: int = Field(
        default=0,
        description="Number of polygons/faces in the geometry if it's a mesh, curves, or points prim",
    )
    point_count: int | None = Field(
        default=None,
        description="Number of points in the geometry if it's a points prim (only set if > 0)",
    )
    curve_segment_count: int | None = Field(
        default=None,
        description="Number of curve segments in the geometry if it's a curves prim (only set if > 0)",
    )

    @computed_field(description="X axis dimension of prim's bounding box")
    @property
    def bbox_dimension_x(self) -> float:
        return abs(self.bbox_max[0] - self.bbox_min[0])

    @computed_field(description="Y axis dimension of prim's bounding box")
    @property
    def bbox_dimension_y(self) -> float:
        return abs(self.bbox_max[1] - self.bbox_min[1])

    @computed_field(description="Z axis dimension of prim's bounding box")
    @property
    def bbox_dimension_z(self) -> float:
        return abs(self.bbox_max[2] - self.bbox_min[2])

    @computed_field(description="X axis dimension of prim's bounding box scaled by the MPU")
    @property
    def scaled_bbox_dimension_x(self) -> float:
        return abs(self.bbox_max[0] - self.bbox_min[0]) * self.scene_mpu

    @computed_field(description="Y axis dimension of prim's bounding box scaled by the MPU")
    @property
    def scaled_bbox_dimension_y(self) -> float:
        return abs(self.bbox_max[1] - self.bbox_min[1]) * self.scene_mpu

    @computed_field(description="Z axis dimension of prim's bounding box scaled by the MPU")
    @property
    def scaled_bbox_dimension_z(self) -> float:
        return abs(self.bbox_max[2] - self.bbox_min[2]) * self.scene_mpu

    @classmethod
    def from_db(cls, **kwargs):
        props = {
            k.removeprefix("property_"): v
            for k, v in kwargs.items()
            if k.startswith("property_") and not k.startswith("property_int_") and not k.startswith("property_float_")
        }
        if kwargs.get("source_asset_url") == "None":
            kwargs["source_asset_url"] = None
        kwargs = {k: v for k, v in kwargs.items() if not k.startswith("property_")}
        return cls(properties=props, **kwargs)

    def clean_up_semantic_labels(self) -> None:
        # Semantic labels contain a hash in their key, which leads to explosion of unique property keys.
        # This function removes those hash values from the keys.

        properties_with_hash = {k: v for k, v in self.properties.items() if k.startswith("semantic:Semantics_")}

        self.properties = {k: v for k, v in self.properties.items() if not k.startswith("semantic:Semantics_")}

        if properties_with_hash:
            self.properties["semantic:Semantics_hash"] = json.dumps(properties_with_hash)


class PrimCreateModel(Prim):
    parent: str | None = None
