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

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from enum import Enum
from functools import lru_cache
from typing import AsyncIterator, Coroutine, Dict, Iterator, List, Optional, Union

from asset_graph_service.db import BaseGraphDB, Prim, PrimCreateModel
from asset_graph_service.db.models import (
    Asset,
    AssetGraph,
    AssetRelationship,
    EdgeType,
    USDAsset,
)
from neo4j import AsyncGraphDatabase, AsyncSession
from neo4j.exceptions import ClientError, ConstraintError, TransientError
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .models import PropertiesFilter, PropertiesFilterRelation
from .utils import sanitize_for_cypher

logger = logging.getLogger(__name__)


def detect_numeric_property(value: str) -> tuple[str, Union[int, float], str]:
    """
    Detect if a string value can be converted to int or float.

    Returns:
        Tuple of (string_value, numeric_value_or_none, type_or_none)
        type_or_none is 'int', 'float', or None
    """
    # Try int conversion first (more restrictive)
    try:
        int_val = int(value)
        # Ensure no precision loss (e.g., "12.0" should be float, not int)
        if str(int_val) == value:
            return value, int_val, "int"
    except ValueError:
        pass

    # Try float conversion
    try:
        float_val = float(value)
        # Ensure it's a valid number and not inf/nan
        if str(float_val) not in ("inf", "-inf", "nan"):
            return value, float_val, "float"
    except ValueError:
        pass

    return value, None, None


def extract_numeric_properties(
    properties: dict[str, str],
) -> dict[str, Union[int, float]]:
    """
    Extract numeric properties from string properties dict.

    Args:
        properties: Dict of property_name -> string_value

    Returns:
        Dict of property_{type}_{name} -> numeric_value
    """
    numeric_properties = {}

    for key, value in properties.items():
        _, numeric_value, numeric_type = detect_numeric_property(value)
        if numeric_value is not None:
            numeric_properties[f"property_{numeric_type}_{key}"] = numeric_value

    return numeric_properties


MAX_RETRIES = 5
RETRY_WAIT_STRATEGY = wait_random_exponential(multiplier=2, max=60)


class Neo4jSettings(BaseSettings):
    db_uri: str
    db_username: str
    db_password: str
    db_name: str = "neo4j"
    n_workers: int = 5


@lru_cache
def get_settings():
    return Neo4jSettings()


class Neo4jDBBackend(BaseGraphDB):
    def __init__(self, settings: Neo4jSettings):
        self.n_workers = settings.n_workers
        self.db_uri = settings.db_uri
        self.db_username = settings.db_username
        self.db_password = settings.db_password
        self.db_name = settings.db_name
        self.driver = AsyncGraphDatabase.driver(self.db_uri, auth=(self.db_username, self.db_password))
        self._active_session = None

        self._indexed_properties = set()

    @property
    def _session(self) -> AsyncSession:
        if self._active_session is None:
            raise RuntimeError("No active DB session")
        return self._active_session

    @asynccontextmanager
    async def session(self) -> AsyncIterator["Neo4jDBBackend"]:
        async with self.driver.session(database=self.db_name) as session:
            self._active_session = session
            try:
                yield self
            finally:
                self._active_session = None

    async def setup(self):
        await self._setup_constraints_and_indices()

    async def close(self):
        await self.driver.close()

    async def clear_db(self):
        await self._session.run("match (a) -[r] -> () delete a, r")
        await self._session.run("match (a) delete a")

    async def ping(self) -> bool:
        if await self._session.run("RETURN 1"):
            return True
        return False

    async def _setup_constraints_and_indices(self):
        logger.info("Setting up constraints and indices")
        query = "CREATE CONSTRAINT asset_unique_url IF NOT EXISTS " "FOR (asset:Asset) REQUIRE asset.url IS UNIQUE"
        await self._session.run(query)
        # neo4j community edition doesn't support constraints on multiple fields so we concatenate
        # scene url and usd path and create index on this field
        query = (
            "CREATE CONSTRAINT prim_scene_url_path IF NOT EXISTS "
            "FOR (p:Prim) REQUIRE p.scene_url__usd_path IS UNIQUE"
        )
        await self._session.run(query)

        # Prim indices
        query = "CREATE INDEX prim_scene_url_usd_path_m IF NOT EXISTS FOR (p:Prim) ON (p.scene_url__usd_path)"
        await self._session.run(query)
        query = "CREATE INDEX prim_scene_url_usd_path IF NOT EXISTS FOR (p:Prim) ON (p.scene_url, p.usd_path)"
        await self._session.run(query)
        query = "CREATE INDEX prim_scene_url_type IF NOT EXISTS FOR (p:Prim) ON (p.scene_url, p.prim_type)"
        await self._session.run(query)
        query = "CREATE INDEX prim_scene_url IF NOT EXISTS FOR (p:Prim) ON (p.scene_url)"
        await self._session.run(query)
        query = "CREATE INDEX prim_usd_path IF NOT EXISTS FOR (p:Prim) ON (p.usd_path)"
        await self._session.run(query)
        query = "CREATE INDEX prim_type IF NOT EXISTS FOR  (p:Prim) ON (p.prim_type)"
        await self._session.run(query)
        query = "CREATE INDEX prim_source_asset_url IF NOT EXISTS FOR (p:Prim) ON (p.source_asset_url)"
        await self._session.run(query)

        for axis in ["x", "y", "z"]:
            query = f"CREATE INDEX prim_bbox_dimension_{axis} IF NOT EXISTS FOR (p:Prim) ON (p.bbox_dimension_{axis})"
            await self._session.run(query)

        # Asset indices
        query = "CREATE INDEX asset_url IF NOT EXISTS FOR (a:Asset) ON (a.url)"
        await self._session.run(query)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def _create_prim_property_index(self, session: AsyncSession, property_name: str):
        if property_name in self._indexed_properties:
            return
        query = (
            f"CREATE INDEX `prim_property_{property_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{property_name}`)"
        )
        logger.debug("create_prim_property_index query: %s", query)
        await session.run(query)
        query = f"CREATE TEXT INDEX `text_prim_property_{property_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{property_name}`)"
        logger.debug("create_prim_property_index query: %s", query)
        await session.run(query)
        self._indexed_properties.add(property_name)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def _create_numeric_property_index(self, session: AsyncSession, property_name: str, numeric_type: str):
        index_key = f"{numeric_type}_{property_name}"
        if index_key in self._indexed_properties:
            return

        query = f"CREATE INDEX `prim_property_{numeric_type}_{property_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{numeric_type}_{property_name}`)"
        logger.debug("create_numeric_property_index query: %s", query)
        await session.run(query)
        self._indexed_properties.add(index_key)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def upsert_asset_nodes(self, nodes: list[Asset | USDAsset], session: Optional[AsyncSession] = None) -> None:
        async with self.driver.session(database=self.db_name) as session:
            query = (
                "UNWIND $nodes AS node "
                "MERGE (n:Asset {url: node.url}) "
                "SET n = apoc.map.merge(apoc.convert.fromJsonMap(node.extra), "
                "{url: node.url})"
            )
            nodes = [{"url": node.url, "extra": json.dumps(node.extra)} for node in nodes]
            logger.debug("upsert_asset_nodes query: %s nodes: %s", query, nodes)
            await session.run(query, nodes=nodes)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def upsert_asset_edges(
        self,
        edges: list[AssetRelationship],
        scene_url: str,
        session: Optional[AsyncSession] = None,
    ) -> None:
        async with self.driver.session(database=self.db_name) as session:
            query = (
                "UNWIND $edges AS edge "
                "MATCH (a:Asset), (b:Asset) "
                "WHERE a.url = edge.node_1_url AND b.url = edge.node_2_url "
                f'CALL apoc.create.relationship(a, edge.type, {{ scene_url: "{sanitize_for_cypher(scene_url)}" }}, b) YIELD rel '
                "RETURN rel"
            )
            await session.run(query, edges=[edge.model_dump() for edge in edges])

    async def get_asset(
        self,
        url: str,
    ) -> Asset | USDAsset | None:
        query = "MATCH (a:Asset {url: $url}) RETURN a"
        results = await (await self._session.run(query, url=url)).value()
        if not results:
            return None
        result = results[0]
        if "scene_mpu" in result or "scene_up_axis" in result:
            return USDAsset(**result)
        return Asset(**result)

    async def get_asset_dependencies_flat(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[Asset]:
        result = await self.get_related_assets_flat(
            root_node_url,
            f"{EdgeType.DEPENDS_ON.value}>",
            max_level=max_level,
            limit=limit,
        )
        return [Asset(**r["node"]) for r in result]

    async def get_inverse_asset_dependencies_flat(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[Asset]:
        result = await self.get_related_assets_flat(
            root_node_url,
            f"<{EdgeType.DEPENDS_ON.value}",
            max_level=max_level,
            limit=limit,
        )
        return [Asset(**r["node"]) for r in result]

    async def get_asset_dependencies_graph(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> AssetGraph:
        nodes, relationships = await self.get_related_assets_graph(
            root_node_url,
            f"{EdgeType.DEPENDS_ON.value}>",
            max_level=max_level,
            limit=limit,
        )
        try:
            node_objects = [Asset(**node) for node in nodes]
            relationship_objects = [
                AssetRelationship(
                    node_1_url=relationship.nodes[0]["url"],
                    node_2_url=relationship.nodes[1]["url"],
                    type=relationship.type,
                )
                for relationship in relationships
            ]
            graph = AssetGraph(nodes=node_objects, edges=relationship_objects)
            return graph
        except ValidationError as e:
            raise RuntimeError(f"Failed to validate graph: {e}") from e

    async def get_inverse_asset_dependencies_graph(
        self,
        root_node_url: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> AssetGraph:
        nodes, relationships = await self.get_related_assets_graph(
            root_node_url,
            f"<{EdgeType.DEPENDS_ON.value}",
            max_level=max_level,
            limit=limit,
        )
        try:
            node_objects = [Asset(**node) for node in nodes]
            relationship_objects = [
                AssetRelationship(
                    node_1_url=relationship.nodes[0]["url"],
                    node_2_url=relationship.nodes[1]["url"],
                    type=relationship.type,
                )
                for relationship in relationships
            ]
            graph = AssetGraph(nodes=node_objects, edges=relationship_objects)
            return graph
        except ValidationError as e:
            raise RuntimeError(f"Failed to validate graph: {e}") from e

    def _get_prim_filters(
        self,
        scene_url: Optional[str] = None,
        usd_paths: Optional[List[str]] = None,
        usd_path_prefix: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = None,
        max_bbox_dimension_y: Optional[float] = None,
        max_bbox_dimension_z: Optional[float] = None,
        prim_types: Optional[List[str]] = None,
        root_prim: Optional[bool] = None,
        default_prim: Optional[bool] = None,
        source_asset_url: Optional[str] = None,
        use_scaled_bbox_dimensions: Optional[bool] = None,
    ):
        properties_filter = None
        if properties is not None:
            property_filters = []
            for property_filter in properties:
                if property_filter.is_numeric_relation():
                    # For numeric relations, try both int and float indexes with fallback to string
                    try:
                        numeric_value = float(property_filter.value)
                        int_value = int(numeric_value) if numeric_value.is_integer() else None

                        conditions = []
                        # Try int index if the value is a whole number
                        if int_value is not None and str(int_value) == property_filter.value:
                            conditions.append(
                                f"p.`property_int_{sanitize_for_cypher(property_filter.key)}` {sanitize_for_cypher(property_filter.get_relation())} {int_value}"
                            )
                        # Try float index
                        conditions.append(
                            f"p.`property_float_{sanitize_for_cypher(property_filter.key)}` {sanitize_for_cypher(property_filter.get_relation())} {numeric_value}"
                        )

                        # Combine with OR since either numeric type could match
                        property_filters.append(f"({' OR '.join(conditions)})")
                    except ValueError:
                        # Fallback to string comparison if value is not numeric
                        property_filters.append(
                            f"p.`property_{sanitize_for_cypher(property_filter.key)}` {sanitize_for_cypher(property_filter.get_relation())} '{sanitize_for_cypher(property_filter.value)}'"
                        )
                else:
                    # String-based relations (equals, almost_equals)
                    # Handle boolean values specially (no quotes, lowercase true/false)
                    if isinstance(property_filter.value, bool):
                        bool_value = str(property_filter.value).lower()
                        property_filters.append(
                            f"p.`property_{sanitize_for_cypher(property_filter.key)}` {sanitize_for_cypher(property_filter.get_relation())} {bool_value}"
                        )
                    else:
                        property_filters.append(
                            f"p.`property_{sanitize_for_cypher(property_filter.key)}` {sanitize_for_cypher(property_filter.get_relation())} '{sanitize_for_cypher(property_filter.value)}'"
                        )

            properties_filter = " AND ".join(property_filters)

        scene_filter = None
        if scene_url is not None:
            scene_filter = f"p.scene_url = '{sanitize_for_cypher(scene_url)}'"

        usd_paths_filter = None
        if usd_paths is not None:
            usd_paths_filter = (
                "(" + " OR ".join([f"p.usd_path = '{sanitize_for_cypher(usd_path)}'" for usd_path in usd_paths]) + ")"
            )

        usd_path_prefix_filter = None
        if usd_path_prefix is not None:
            usd_path_prefix_filter = f"p.usd_path STARTS WITH '{sanitize_for_cypher(usd_path_prefix)}'"

        prim_types_filter = None
        if prim_types is not None:
            prim_types_filter = (
                "("
                + " OR ".join([f"p.prim_type = '{sanitize_for_cypher(prim_type)}'" for prim_type in prim_types])
                + ")"
            )

        source_asset_url_filter = None
        if source_asset_url:
            source_asset_url_filter = f"p.source_asset_url = '{sanitize_for_cypher(source_asset_url)}'"

        root_prim_filter = None
        default_prim_filter = None
        if root_prim and default_prim:
            # if both are true, we want to match either
            root_prim_filter = f"(p.root_prim = true OR p.default_prim = true)"
        elif root_prim:
            root_prim_filter = f"p.root_prim = true"
        elif default_prim:
            default_prim_filter = f"p.default_prim = true"

        dimension_filters = []

        # get filters for bbox min dimensions
        for val, field in zip(
            [min_bbox_dimension_x, min_bbox_dimension_y, min_bbox_dimension_z],
            (
                [
                    "scaled_bbox_dimension_x",
                    "scaled_bbox_dimension_y",
                    "scaled_bbox_dimension_z",
                ]
                if use_scaled_bbox_dimensions
                else ["bbox_dimension_x", "bbox_dimension_y", "bbox_dimension_z"]
            ),
        ):
            if val is not None:
                dimension_filters.append(f"p.{field} > {val}")

        # get filters for bbox max dimensions
        for val, field in zip(
            [max_bbox_dimension_x, max_bbox_dimension_y, max_bbox_dimension_z],
            (
                [
                    "scaled_bbox_dimension_x",
                    "scaled_bbox_dimension_y",
                    "scaled_bbox_dimension_z",
                ]
                if use_scaled_bbox_dimensions
                else ["bbox_dimension_x", "bbox_dimension_y", "bbox_dimension_z"]
            ),
        ):
            if val is not None:
                dimension_filters.append(f"p.{field} < {val}")

        filters = " AND ".join(
            f
            for f in [
                scene_filter,
                usd_paths_filter,
                usd_path_prefix_filter,
                properties_filter,
                prim_types_filter,
                root_prim_filter,
                default_prim_filter,
                source_asset_url_filter,
                *dimension_filters,
            ]
            if f is not None
        )
        return filters

    async def get_prims(
        self,
        scene_url: Optional[str] = None,
        usd_paths: Optional[List[str]] = None,
        usd_path_prefix: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = None,
        max_bbox_dimension_y: Optional[float] = None,
        max_bbox_dimension_z: Optional[float] = None,
        prim_types: Optional[List[str]] = None,
        limit: Optional[int] = None,
        root_prim: Optional[bool] = None,
        default_prim: Optional[bool] = None,
        source_asset_url: Optional[str] = None,
        use_scaled_bbox_dimensions: Optional[bool] = None,
    ):
        filters = self._get_prim_filters(
            scene_url=scene_url,
            usd_paths=usd_paths,
            usd_path_prefix=usd_path_prefix,
            properties=properties,
            min_bbox_dimension_x=min_bbox_dimension_x,
            min_bbox_dimension_y=min_bbox_dimension_y,
            min_bbox_dimension_z=min_bbox_dimension_z,
            max_bbox_dimension_x=max_bbox_dimension_x,
            max_bbox_dimension_y=max_bbox_dimension_y,
            max_bbox_dimension_z=max_bbox_dimension_z,
            prim_types=prim_types,
            root_prim=root_prim,
            default_prim=default_prim,
            source_asset_url=source_asset_url,
            use_scaled_bbox_dimensions=use_scaled_bbox_dimensions,
        )

        limit_str = ""
        if limit is not None:
            limit_str = f"LIMIT {limit}"

        where_str = f"WHERE {filters}" if filters else ""

        query = f"""
        MATCH (p:Prim)
        {where_str}
        RETURN p as prim {limit_str}
        """
        logger.debug("get_prims query: %s", query)
        result = await self._session.run(query)
        results_list = []
        async for record in result:
            results_list.append(record)
        logger.debug("get_prims result: %s", results_list)
        return [Prim.from_db(**res["prim"]) for res in results_list]

    async def get_prims_within_bounding_box(
        self,
        scene_url: str,
        min_bbox_x: float,
        min_bbox_y: float,
        min_bbox_z: float,
        max_bbox_x: float,
        max_bbox_y: float,
        max_bbox_z: float,
        usd_path_prefix: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> list[Prim]:
        filters = self._get_prim_filters(
            scene_url=scene_url,
            usd_path_prefix=usd_path_prefix,
            properties=properties,
            min_bbox_dimension_x=min_bbox_dimension_x,
            min_bbox_dimension_y=min_bbox_dimension_y,
            min_bbox_dimension_z=min_bbox_dimension_z,
            max_bbox_dimension_x=max_bbox_dimension_x,
            max_bbox_dimension_y=max_bbox_dimension_y,
            max_bbox_dimension_z=max_bbox_dimension_z,
            prim_types=prim_types,
        )

        query = f"""
        MATCH (p:Prim)
        WHERE {filters} AND point.withinBBox(p.bbox_midpoint, Point({{x: {min_bbox_x}, y: {min_bbox_y}, z: {min_bbox_z}}}), Point({{x: {max_bbox_x}, y: {max_bbox_y}, z: {max_bbox_z}}}))
        RETURN p as prim LIMIT {limit}
        """
        logger.debug("get_prims_within_bounding_box query: %s", query)
        result = await self._session.run(query)
        results_list = []
        async for record in result:
            results_list.append(record)
        return [Prim.from_db(**res["prim"]) for res in results_list]

    async def get_prims_within_radius_of_another_prim(
        self,
        scene_url: str,
        center_prim_usd_path: str,
        radius: float,
        usd_path_prefix: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> list[tuple[Prim, float]]:
        filters = self._get_prim_filters(
            scene_url=scene_url,
            usd_path_prefix=usd_path_prefix,
            properties=properties,
            min_bbox_dimension_x=min_bbox_dimension_x,
            min_bbox_dimension_y=min_bbox_dimension_y,
            min_bbox_dimension_z=min_bbox_dimension_z,
            max_bbox_dimension_x=max_bbox_dimension_x,
            max_bbox_dimension_y=max_bbox_dimension_y,
            max_bbox_dimension_z=max_bbox_dimension_z,
            prim_types=prim_types,
        )

        query = f"""
        MATCH (center:Prim)
        WHERE center.scene_url = '{sanitize_for_cypher(scene_url)}' AND center.usd_path = '{sanitize_for_cypher(center_prim_usd_path)}'
        WITH center
        CALL {{
            WITH center
            MATCH (p:Prim)
            WHERE {filters} AND point.distance(p.bbox_midpoint, center.bbox_midpoint) < {radius}
            RETURN p, point.distance(p.bbox_midpoint, center.bbox_midpoint) as dist ORDER BY dist LIMIT {limit}
        }}
        RETURN p as prim, dist as distance ORDER BY dist LIMIT {limit}
        """
        logger.debug("get_prims_within_radius_of_another_prim query: %s", query)
        result = await self._session.run(query)
        results_list = []
        async for record in result:
            results_list.append(record)
        return [(Prim.from_db(**res["prim"]), res["distance"]) for res in results_list]

    async def get_prims_within_radius_of_a_point(
        self,
        scene_url: str,
        center_x: float,
        center_y: float,
        center_z: float,
        radius: float,
        usd_path_prefix: Optional[str] = None,
        properties: Optional[List[PropertiesFilter]] = None,
        min_bbox_dimension_x: Optional[float] = None,
        min_bbox_dimension_y: Optional[float] = None,
        min_bbox_dimension_z: Optional[float] = None,
        max_bbox_dimension_x: Optional[float] = 4e38,
        max_bbox_dimension_y: Optional[float] = 4e38,
        max_bbox_dimension_z: Optional[float] = 4e38,
        prim_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> list[tuple[Prim, float]]:
        filters = self._get_prim_filters(
            scene_url=scene_url,
            usd_path_prefix=usd_path_prefix,
            properties=properties,
            min_bbox_dimension_x=min_bbox_dimension_x,
            min_bbox_dimension_y=min_bbox_dimension_y,
            min_bbox_dimension_z=min_bbox_dimension_z,
            max_bbox_dimension_x=max_bbox_dimension_x,
            max_bbox_dimension_y=max_bbox_dimension_y,
            max_bbox_dimension_z=max_bbox_dimension_z,
            prim_types=prim_types,
        )

        query = f"""
            MATCH (p:Prim)
            WHERE {filters} AND point.distance(p.bbox_midpoint, Point({{x: {center_x}, y: {center_y}, z: {center_z}}})) < {radius} 
            RETURN p as prim, point.distance(p.bbox_midpoint, Point({{x: {center_x}, y: {center_y}, z: {center_z}}})) as distance ORDER BY distance LIMIT {limit}
        """
        logger.debug("get_prims_within_radius_of_a_point query: %s", query)
        result = await self._session.run(query)
        results_list = []
        async for record in result:
            results_list.append(record)
        return [(Prim.from_db(**res["prim"]), res["distance"]) for res in results_list]

    async def get_related_assets_graph(
        self,
        root_node_url: str,
        relationship_filter: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        config_map = ["minLevel:0"]
        if max_level is not None:
            config_map.append(f"maxLevel:{max_level}")
        if limit is not None:
            config_map.append(f"limit:{limit}")
        config_map.append(f"relationshipFilter:'{sanitize_for_cypher(relationship_filter)}'")

        config_str = ", ".join(config_map)

        query = f"""
        MATCH (root:Asset {{url:$root_url}})
        CALL apoc.path.subgraphAll(root, {{
            {config_str}
        }}) YIELD nodes, relationships
        UNWIND relationships AS r
        WITH nodes, startNode(r) AS n, endNode(r) AS m, r
        ORDER BY id(r)
        WITH nodes, n, m, COLLECT(r)[0] AS uniqueR  // Keep only one relationship per node pair
        RETURN nodes, COLLECT(uniqueR) AS relationships
        """

        logger.debug("get_related_assets_graph query: %s", query)
        result = await self._session.run(query, parameters={"root_url": sanitize_for_cypher(root_node_url)})

        nodes = []
        relationships = []
        async for record in result:
            nodes.extend(record["nodes"])
            relationships.extend(record["relationships"])
        logger.debug("get_related_assets_graph result: nodes=%s edges=%s", nodes, relationships)

        return nodes, relationships

    async def get_related_assets_flat(
        self,
        root_node_url: str,
        relationship_filter: str,
        max_level: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        max_level_filter = ""
        if max_level is not None:
            max_level_filter = f"maxLevel:{max_level}, "

        limit_str = ""
        if limit is not None:
            limit_str = f"LIMIT {limit}"

        query = f"MATCH (n:Asset {{url:'{sanitize_for_cypher(root_node_url)}' }}) CALL apoc.path.subgraphNodes(n, {{minLevel:1, {max_level_filter}relationshipFilter:'{sanitize_for_cypher(relationship_filter)}'  }}) YIELD node RETURN node {limit_str}"
        logger.debug("get_related_nodes_flat query: %s", query)
        result = await self._session.run(query, parameters={"root_url": sanitize_for_cypher(root_node_url)})
        results_list = []
        async for record in result:
            results_list.append(record)
        return results_list
        # TODO: rewrite as async iterator

    async def delete_asset_subgraph(self, root_node_url: str, session: Optional[AsyncSession]) -> None:
        session = session or self._session
        query = f"MATCH (n:Asset {{url:'{root_node_url}'}}) CALL apoc.path.subgraphNodes(n, {{minLevel:1, relationshipFilter:'{EdgeType.DEPENDS_ON.value}>'  }}) YIELD node DETACH DELETE node"
        logger.debug("delete_asset_subgraph query: %s", query)
        await session.run(query)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def delete_assets(self, asset_urls: list[str]) -> None:
        async with self.driver.session(database=self.db_name) as session:
            query = "UNWIND $asset_urls AS asset_url MATCH (n:Asset {url: asset_url}) DETACH DELETE n"
            logger.debug("delete_assets query: %s", query)
            await session.run(query, asset_urls=asset_urls)

    async def delete_asset_edges(self, scene_url: str) -> None:
        async with self.driver.session(database=self.db_name) as session:
            query = f'MATCH ()-[r:{EdgeType.DEPENDS_ON.value} {{scene_url: "{sanitize_for_cypher(scene_url)}" }}]->() DELETE r'
            logger.debug("delete_asset_edges query: %s", query)
            await session.run(query)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def delete_prims(self, scene_url: str, session: Optional[AsyncSession] = None) -> None:
        session = session or self._session
        query = f"MATCH (n:Prim {{scene_url:$scene_url}}) CALL {{ WITH n DETACH DELETE n }}"
        logger.debug("delete_prims_subgraph query: %s", query)
        await session.run(query, scene_url=sanitize_for_cypher(scene_url))

    async def mark_assets_as_deleted(self, asset_urls: List[str]) -> None:
        for asset_url in asset_urls:
            query = f"MATCH (n:Asset {{url:'{asset_url}'}}) SET n.deleted = true"
            logger.debug("mark_assets_as_deleted query: %s", query)
            await self._session.run(query)

    async def update_graph(
        self,
        assets: list[Asset | USDAsset],
        asset_relationships: list[AssetRelationship],
        prims: list[PrimCreateModel],
        scene_url: str,
        default_prim_path: str | None = None,
    ) -> None:
        """
        Update graph in a transaction. Assumes all assets and prims are a result of traversing a single scene
        """

        # TODO: think of possible race conditions when parts of the same graph are processed in parallel transactions; see if/how neo4j supports locking

        # await self.delete_assets([asset.url for asset in assets])
        await self.delete_asset_edges(scene_url)
        await self.delete_prims(scene_url)

        await self.upsert_asset_nodes(assets, self._session)
        logger.debug("Upserting %s assets done", len(assets))

        await self.upsert_asset_edges(asset_relationships, scene_url, self._session)
        logger.debug("Upserting %s asset relationships done", len(asset_relationships))

        for prim in prims:
            if prim.usd_path == default_prim_path:
                prim.default_prim = True

        # get root asset
        root_asset = await self.get_asset(scene_url)
        logger.debug("Root asset for the scene: %s", str(root_asset))
        if root_asset is None:
            logger.warning("root asset missing for scene URL: %s", scene_url)
        elif isinstance(root_asset, USDAsset) and root_asset.scene_mpu is not None:
            for prim in prims:
                prim.scene_mpu = root_asset.scene_mpu

        await self.upsert_prims(prims, self._session)
        logger.debug("Upserting %s prims done", len(prims))

        # Create indices for prim properties
        # Must be run outside of transaction as it is a schema changing operation
        numeric_properties_seen = set()

        for prim in prims:
            # Create string property indexes
            for property_name in prim.properties.keys():
                await self._create_prim_property_index(self._session, property_name)

                # Check if this property has numeric values and create numeric indexes
                _, numeric_value, numeric_type = detect_numeric_property(prim.properties[property_name])
                if numeric_value is not None:
                    numeric_key = f"{numeric_type}_{property_name}"
                    if numeric_key not in numeric_properties_seen:
                        await self._create_numeric_property_index(self._session, property_name, numeric_type)
                        numeric_properties_seen.add(numeric_key)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=retry_if_exception_type((TransientError, RuntimeError, ClientError)),
    )
    async def upsert_prims(self, prims: list[Prim], session: Optional[AsyncSession] = None) -> None:
        for prims_batch in self.batch(prims, 50000):
            await self._create_multiple_prims(prims_batch)
        await self._connect_multiple_prims(prims)

    async def _batch_worker(self, tasks_iterator: Iterator[Coroutine], n_workers: int | None = None):
        if n_workers is None:
            n_workers = self.n_workers

        async def _worker():
            for task in tasks_iterator:
                await task

        await asyncio.gather(*[_worker() for i in range(n_workers)])

    async def _create_multiple_prims(self, prims: list[Prim]):
        async with self.driver.session(database=self.db_name) as session:
            prims_data = []
            for prim in prims:
                # Format properties for Cypher - booleans need special handling (no quotes, lowercase)
                def format_property_value(v):
                    if isinstance(v, bool):
                        return str(v).lower()  # true/false without quotes
                    return f"'{v}'"  # strings with quotes

                properties_str = (
                    ", ".join([f"`property_{k}`: {format_property_value(v)}" for k, v in prim.properties.items()])
                    if prim.properties
                    else ""
                )

                translate = {axis: float(v) for v, axis in zip(prim.translate, ["x", "y", "z"])}
                bbox_midpoint = {axis: float(v) for v, axis in zip(prim.bbox_midpoint, ["x", "y", "z"])}
                bbox_min = {axis: float(v) for v, axis in zip(prim.bbox_min, ["x", "y", "z"])}
                bbox_max = {axis: float(v) for v, axis in zip(prim.bbox_max, ["x", "y", "z"])}

                prim_data = {
                    "scene_url_usd_path": f"{prim.scene_url}:{prim.usd_path}",
                    "scene_url": prim.scene_url,
                    "scene_mpu": prim.scene_mpu,
                    "usd_path": prim.usd_path,
                    "source_asset_url": prim.source_asset_url,
                    "prim_type": prim.prim_type,
                    "translate": translate,
                    "rotate_x": prim.rotate_x,
                    "rotate_y": prim.rotate_y,
                    "rotate_z": prim.rotate_z,
                    "scale_x": prim.scale_x,
                    "scale_y": prim.scale_y,
                    "scale_z": prim.scale_z,
                    "bbox_midpoint": bbox_midpoint,
                    "bbox_min": bbox_min,
                    "bbox_max": bbox_max,
                    "bbox_dimension_x": prim.bbox_dimension_x,
                    "bbox_dimension_y": prim.bbox_dimension_y,
                    "bbox_dimension_z": prim.bbox_dimension_z,
                    "scaled_bbox_dimension_x": prim.scaled_bbox_dimension_x,
                    "scaled_bbox_dimension_y": prim.scaled_bbox_dimension_y,
                    "scaled_bbox_dimension_z": prim.scaled_bbox_dimension_z,
                    "polygon_count": prim.polygon_count,
                    "point_count": prim.point_count,
                    "curve_segment_count": prim.curve_segment_count,
                    "default_prim": prim.default_prim,
                }

                prim_data["extra"] = {}

                if prim.parent == "/":
                    prim_data["extra"]["root_prim"] = True
                if properties_str:
                    # Store original string properties
                    prim_data["extra"].update({f"property_{k}": v for k, v in prim.properties.items()})
                    # Store numeric properties alongside string properties
                    numeric_props = extract_numeric_properties(prim.properties)
                    prim_data["extra"].update(numeric_props)

                prim_data["extra"] = json.dumps(prim_data["extra"])

                prims_data.append(prim_data)

            query = (
                "UNWIND $prims AS prim "
                "CREATE (p:Prim) "
                "SET p = apoc.map.merge(apoc.convert.fromJsonMap(prim.extra),"
                "{scene_url__usd_path: prim.scene_url_usd_path, "
                "scene_url: prim.scene_url, "
                "scene_mpu: prim.scene_mpu, "
                "source_asset_url: prim.source_asset_url, "
                "usd_path: prim.usd_path, "
                "prim_type: prim.prim_type, "
                "translate: Point(prim.translate), "
                "rotate_x: prim.rotate_x, "
                "rotate_y: prim.rotate_y, "
                "rotate_z: prim.rotate_z, "
                "scale_x: prim.scale_x, "
                "scale_y: prim.scale_y, "
                "scale_z: prim.scale_z, "
                "bbox_midpoint: Point(prim.bbox_midpoint), "
                "bbox_min: Point(prim.bbox_min), "
                "bbox_max: Point(prim.bbox_max), "
                "bbox_dimension_x: prim.bbox_dimension_x, "
                "bbox_dimension_y: prim.bbox_dimension_y, "
                "bbox_dimension_z: prim.bbox_dimension_z, "
                "scaled_bbox_dimension_x: prim.scaled_bbox_dimension_x, "
                "scaled_bbox_dimension_y: prim.scaled_bbox_dimension_y, "
                "scaled_bbox_dimension_z: prim.scaled_bbox_dimension_z, "
                "polygon_count: prim.polygon_count, "
                "point_count: prim.point_count, "
                "curve_segment_count: prim.curve_segment_count, "
                "default_prim: prim.default_prim "
                "})"
            )
            logger.debug("upsert_prims: add prims query: %s", query)
            try:
                await session.run(query, prims=prims_data, timeout=60 * 60 * 2)
            except ConstraintError:
                logger.debug("One or more Prims already exist")

    @staticmethod
    def batch(iterable, n=1):
        length = len(iterable)
        for ndx in range(0, length, n):
            yield iterable[ndx : min(ndx + n, length)]

    async def _connect_multiple_prims(self, prims: list[Prim]):
        async with self.driver.session(database=self.db_name) as session:
            source_asset_connections = []
            root_prim_connections = []
            parent_prim_connections = []

            for prim in prims:
                if prim.source_asset_url:
                    source_asset_connections.append(
                        {
                            "source_asset_url": prim.source_asset_url,
                            "usd_path": prim.usd_path,
                            "scene_url": prim.scene_url,
                        }
                    )

                if prim.parent == "/":
                    root_prim_connections.append(
                        {
                            "asset_url": prim.scene_url,
                            "usd_path": prim.usd_path,
                            "scene_url": prim.scene_url,
                        }
                    )
                else:
                    parent_prim_connections.append(
                        {
                            "usd_path": prim.usd_path,
                            "scene_url": prim.scene_url,
                            "parent_usd_path": prim.parent,
                        }
                    )

            source_asset_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Asset) WHERE a.url = connection.source_asset_url "
                "WITH collect(a) AS aNodes, connection "
                "MATCH (b:Prim) WHERE b.usd_path = connection.usd_path AND b.scene_url = connection.scene_url "
                "WITH aNodes, collect(b) AS bNodes "
                "CALL apoc.create.relationship(aNodes[0], 'SOURCE_ASSET', {}, bNodes[0]) YIELD rel "
                "RETURN rel"
            )

            root_prim_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Asset) WHERE a.url = connection.asset_url "
                "WITH collect(a) AS aNodes, connection "
                "MATCH (b:Prim) WHERE b.usd_path = connection.usd_path AND b.scene_url = connection.scene_url "
                "WITH aNodes, collect(b) AS bNodes "
                "CALL apoc.create.relationship(aNodes[0], 'ROOT_PRIM', {}, bNodes[0]) YIELD rel "
                "RETURN rel"
            )

            parent_prim_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Prim) WHERE a.scene_url = connection.scene_url AND a.usd_path = connection.usd_path "
                "WITH collect(a) AS aNodes, connection "
                "MATCH (b:Prim) WHERE b.usd_path = connection.parent_usd_path AND b.scene_url = connection.scene_url "
                "WITH aNodes, collect(b) AS bNodes "
                "CALL apoc.create.relationship(aNodes[0], 'PARENT', {}, bNodes[0]) YIELD rel "
                "RETURN rel"
            )

            # Due to what appears to be a bug in neo4j, connections must be processed in batches.
            # The bug occurs when neo4j clears the internal query cache during the insert operation, which seems to
            # clear the cache for all the operations in `UNWIND` clause, making it incredibly slow.
            # Using smaller batches doesn't eliminate the issue, but makes it limited to a single batch.
            try:
                for batch_connections in self.batch(source_asset_connections, 100):
                    logger.debug(
                        "upsert_prims: add source asset connections, batch size: %d, query: %s",
                        len(batch_connections),
                        source_asset_query,
                    )
                    result = await session.run(source_asset_query, connections=batch_connections)
                    await result.consume()

                for batch_connections in self.batch(root_prim_connections, 100):
                    logger.debug(
                        "upsert_prims: add root prim connections, batch size: %d, query: %s",
                        len(batch_connections),
                        root_prim_query,
                    )
                    result = await session.run(root_prim_query, connections=batch_connections)
                    await result.consume()

                for batch_connections in self.batch(parent_prim_connections, 100):
                    logger.debug(
                        "upsert_prims: add parent prim connections, batch size: %d, query: %s",
                        len(batch_connections),
                        parent_prim_query,
                    )
                    result = await session.run(parent_prim_query, connections=batch_connections)
                    await result.consume()
            except ConstraintError:
                logger.debug("One or more connections already exist")
