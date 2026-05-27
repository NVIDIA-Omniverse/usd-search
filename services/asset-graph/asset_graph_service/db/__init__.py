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

import abc
from abc import abstractmethod
from typing import Any, AsyncIterator, Iterable, List, Optional

from asset_graph_service.db.models import (
    Asset,
    AssetGraph,
    AssetRelationship,
    Prim,
    PrimCreateModel,
    PropertiesFilter,
    USDAsset,
)


class BaseGraphDB(abc.ABC):
    @abstractmethod
    async def setup(self): ...

    @abstractmethod
    async def ping(self) -> bool: ...

    @abstractmethod
    async def session(self) -> AsyncIterator["BaseGraphDB"]: ...

    @abstractmethod
    async def update_graph(
        self,
        assets: list[Asset | USDAsset],
        asset_relationships: list[AssetRelationship],
        prims: list[PrimCreateModel],
        scene_url: str,
        default_prim_path: str,
    ) -> None: ...

    @abstractmethod
    async def close(self): ...

    @abstractmethod
    async def clear_db(self): ...

    @abstractmethod
    async def upsert_asset_nodes(self, nodes: list[Asset]) -> None: ...

    @abstractmethod
    async def mark_assets_as_deleted(self, asset_urls: list[str]) -> None: ...

    @abstractmethod
    async def delete_assets(self, asset_urls: list[str], session: Optional[Any] = None) -> None: ...

    @abstractmethod
    async def upsert_asset_edges(self, edges: list[AssetRelationship]) -> None: ...

    @abstractmethod
    async def get_asset_dependencies_flat(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[Asset]: ...

    @abstractmethod
    async def get_asset(
        self,
        url: str,
    ) -> list[Asset | USDAsset]: ...

    @abstractmethod
    async def get_asset_dependencies_graph(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> AssetGraph: ...

    @abstractmethod
    async def get_inverse_asset_dependencies_graph(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> AssetGraph: ...

    @abstractmethod
    async def get_inverse_asset_dependencies_flat(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[Asset]: ...

    @abstractmethod
    async def upsert_prims(self, prims: Iterable[Prim]) -> None: ...

    @abstractmethod
    async def get_prims(
        self,
        scene_url: Optional[str] = None,
        usd_path: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = None,
        max_bbox_dimension_y: Optional[float] = None,
        max_bbox_dimension_z: Optional[float] = None,
        prim_type: Optional[str] = None,
        limit: Optional[int] = None,
        root_prim: Optional[bool] = False,
        default_prim: Optional[bool] = None,
        source_asset_url: Optional[str] = None,
        use_scaled_bbox_dimensions: Optional[bool] = None,
    ) -> list[Prim]: ...

    @abstractmethod
    async def get_prims_within_radius_of_another_prim(
        self,
        scene_url: str,
        center_prim_usd_path: str,
        radius: float,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[Prim, float]]: ...

    @abstractmethod
    async def get_prims_within_bounding_box(
        self,
        scene_url: str,
        min_bbox_x: float,
        min_bbox_y: float,
        min_bbox_z: float,
        max_bbox_x: float,
        max_bbox_y: float,
        max_bbox_z: float,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[Prim]: ...

    @abstractmethod
    async def get_prims_within_radius_of_a_point(
        self,
        scene_url: str,
        center_x: float,
        center_y: float,
        center_z: float,
        radius: float,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_type: Optional[str] = None,
        limit: int = 100,
    ) -> list[tuple[Prim, float]]: ...
