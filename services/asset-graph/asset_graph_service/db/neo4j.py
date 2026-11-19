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
import os
import re
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import AsyncIterator, Coroutine, Iterator, List, Optional, Union

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
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .models import PropertiesFilter
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
RETRY_CONDITION = retry_if_exception_type((TransientError, RuntimeError, ClientError)) & retry_if_not_exception_type(
    ConstraintError
)

# Naming convention used by _create_prim_property_index / _create_numeric_property_index,
# duplicated here so seed_property_index_cache() can parse `SHOW INDEXES` results back into
# property names without a live Neo4j round trip per property.
_STRING_INDEX_PREFIX = "prim_property_"
_NUMERIC_INDEX_TYPES = ("int", "float")


class PropertyIndexCache:
    """Process-lifetime record of which USD prim-property Neo4j indices already exist.

    A fresh Neo4jDBBackend used to be constructed per HTTP request with its own empty
    `_indexed_properties` set (see api/dependencies.py), so "already indexed" state never
    survived past a single write: every distinct property name reissued
    CREATE INDEX IF NOT EXISTS on every asset write, and Neo4j takes an exclusive schema
    lock for each of these regardless of whether it's a no-op. This cache is owned by the
    FastAPI app (app.state) and shared by every request in the process, so a property is
    only ever (re-)created once per process lifetime.

    String and numeric indices are tracked in separate namespaces on purpose: the old
    single `_indexed_properties` set stored both `property_name` and
    `f"{numeric_type}_{property_name}"` keys together, so a property literally named
    e.g. `int_offset` could collide with the numeric-index bookkeeping key for a
    different property `offset` of type `int`.
    """

    def __init__(self) -> None:
        self._string_indexed: set[str] = set()
        self._numeric_indexed: set[tuple[str, str]] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    def is_string_indexed(self, property_name: str) -> bool:
        return property_name in self._string_indexed

    def mark_string_indexed(self, property_name: str) -> None:
        self._string_indexed.add(property_name)

    def is_numeric_indexed(self, property_name: str, numeric_type: str) -> bool:
        return (numeric_type, property_name) in self._numeric_indexed

    def mark_numeric_indexed(self, property_name: str, numeric_type: str) -> None:
        self._numeric_indexed.add((numeric_type, property_name))

    def lock_for(self, index_name: str) -> asyncio.Lock:
        """A per-physical-index-name lock so concurrent requests that both see the same
        never-before-seen property don't both race Neo4j's schema lock for it.

        Keyed by the physical Neo4j index name (e.g. `prim_property_int_offset`), not by
        (kind, property_name): a property literally named `int_offset` (string index) and
        a numeric property `offset` of type `int` both target that same physical index
        (see seed_property_index_cache's docstring), so they must serialize on the same
        lock — otherwise both could race a concurrent CREATE INDEX for it.
        """
        lock = self._locks.get(index_name)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[index_name] = lock
        return lock


# Neo4j rejects any single property value larger than the index key limit (~8167 bytes on the
# block store) when that property is backed by a range/TEXT index, failing the whole write
# transaction. Values above this threshold are stored under a non-indexed `raw_property_` prefix
# instead of the indexed `property_` prefix, and no index is created for them.
MAX_INDEXED_PROPERTY_VALUE_BYTES = int(os.getenv("MAX_INDEXED_PROPERTY_VALUE_BYTES", "8000"))
UNINDEXED_PROPERTY_PREFIX = "raw_property_"


def property_value_too_large(value: object) -> bool:
    """Return True if a string property value exceeds Neo4j's per-value index size limit."""
    return isinstance(value, str) and len(value.encode("utf-8")) > MAX_INDEXED_PROPERTY_VALUE_BYTES


# Some prim property names embed data rather than naming a field, e.g. flattened SimReady
# validation history keyed by date:
# `simready_metadata_validation__validated_features__2026-05-29__FET004_BASE_NEUTRAL__passed`.
# Such names grow without bound (nearly every new asset brings new ones), and each name used to
# get its own RANGE + TEXT index: ~15k indexes on one deployment, each a schema transaction plus a
# population scan over every Prim. Names matching this regex are still stored under `property_`
# and stay filterable, just without an index. An empty value disables the check.
PROPERTY_INDEX_EXCLUDE_REGEX = os.getenv("PROPERTY_INDEX_EXCLUDE_REGEX", r"(?:^|[_:])\d{4}-\d{2}-\d{2}(?:$|[_:T])")
_property_index_exclude_pattern = re.compile(PROPERTY_INDEX_EXCLUDE_REGEX) if PROPERTY_INDEX_EXCLUDE_REGEX else None


def property_index_excluded(property_name: str) -> bool:
    """Return True if no Neo4j index should be created for this prim property name."""
    return _property_index_exclude_pattern is not None and bool(_property_index_exclude_pattern.search(property_name))


# Prim property names that also get a TEXT index (Lucene) next to their RANGE index, as a
# comma-separated list of exact names. Only CONTAINS / ENDS WITH filters use a TEXT index, and
# AGS's own filters (=, =~, numeric comparisons) never do, while Neo4j updates every touched TEXT
# index file on every commit: on NFS-backed storage that was most of each store's time. Empty by
# default; Neo4jDBBackend.sync_text_property_indexes() makes Neo4j match this list at startup.
PROPERTY_TEXT_INDEX_FIELDS = frozenset(
    name.strip() for name in os.getenv("PROPERTY_TEXT_INDEX_FIELDS", "").split(",") if name.strip()
)
_TEXT_INDEX_PREFIX = f"text_{_STRING_INDEX_PREFIX}"


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
    def __init__(self, settings: Neo4jSettings, property_index_cache: Optional[PropertyIndexCache] = None):
        self.n_workers = settings.n_workers
        self.db_uri = settings.db_uri
        self.db_username = settings.db_username
        self.db_password = settings.db_password
        self.db_name = settings.db_name
        self.driver = AsyncGraphDatabase.driver(self.db_uri, auth=(self.db_username, self.db_password))
        self._active_session = None

        # Falls back to a private, request-scoped cache when the caller doesn't share one
        # (e.g. direct construction in tests) — see PropertyIndexCache's docstring for why
        # a *shared* instance (app.state.property_index_cache in production) matters.
        self._property_index_cache = property_index_cache if property_index_cache is not None else PropertyIndexCache()

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

    async def seed_property_index_cache(self) -> None:
        """Populate the shared PropertyIndexCache from Neo4j's own index catalog.

        Runs once at process startup (see api/__init__.py's lifespan) so a freshly
        started process — or one started after another replica already indexed a
        property — doesn't reissue CREATE INDEX, and pay for its exclusive schema lock,
        for properties Neo4j has already indexed.

        Parses index *names*, not the indexed property key: both encode the property
        name using the same `{numeric_type}_{property_name}` template for numeric
        indices, so a property literally named e.g. `int_offset` is indistinguishable
        from the numeric index for a property named `offset` of type `int` either way.
        This is a pre-existing ambiguity in the naming scheme (see docs/plans), not
        introduced by this parsing step; on a false classification the affected
        property's next write simply reissues its CREATE INDEX once (self-correcting)
        rather than being permanently skipped.
        """
        result = await self._session.run("SHOW INDEXES YIELD name")
        async for record in result:
            name = record["name"]
            if not name.startswith(_STRING_INDEX_PREFIX):
                continue
            remainder = name[len(_STRING_INDEX_PREFIX) :]
            for numeric_type in _NUMERIC_INDEX_TYPES:
                prefix = f"{numeric_type}_"
                if remainder.startswith(prefix):
                    self._property_index_cache.mark_numeric_indexed(remainder[len(prefix) :], numeric_type)
                    break
            else:
                self._property_index_cache.mark_string_indexed(remainder)

    async def sync_text_property_indexes(self, fields: frozenset[str] = PROPERTY_TEXT_INDEX_FIELDS) -> None:
        """Create the TEXT indexes listed in PROPERTY_TEXT_INDEX_FIELDS and drop all other
        per-property TEXT indexes (older versions created one for every prim property).

        Runs once at process startup (see api/__init__.py's lifespan). A listed property
        needn't exist yet: Neo4j indexes it as soon as a prim carries it.
        """
        # Keyed by the name SHOW INDEXES reports: Neo4j stores a backtick-quoted identifier
        # with its doubled backticks collapsed.
        wanted = {f"{_TEXT_INDEX_PREFIX}{sanitize_for_cypher(name)}".replace("``", "`"): name for name in fields}
        result = await self._session.run("SHOW INDEXES YIELD name, type WHERE type = 'TEXT' RETURN name")
        existing = {record["name"] async for record in result}

        stale = sorted(name for name in existing if name.startswith(_TEXT_INDEX_PREFIX) and name not in wanted)
        if stale:
            logger.info("Dropping %d prim property TEXT indexes not in PROPERTY_TEXT_INDEX_FIELDS", len(stale))
        for index_name in stale:
            await self._session.run(f"DROP INDEX `{index_name.replace('`', '``')}` IF EXISTS")

        for index_name, property_name in wanted.items():
            if index_name in existing:
                continue
            safe_name = sanitize_for_cypher(property_name)
            query = f"CREATE TEXT INDEX `{_TEXT_INDEX_PREFIX}{safe_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{safe_name}`)"
            logger.info("create text property index query: %s", query)
            await self._session.run(query)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=RETRY_CONDITION,
    )
    async def _create_prim_property_index(self, session: AsyncSession, property_name: str):
        cache = self._property_index_cache
        if cache.is_string_indexed(property_name):
            return
        async with cache.lock_for(f"{_STRING_INDEX_PREFIX}{property_name}"):
            if cache.is_string_indexed(property_name):
                return
            safe_name = sanitize_for_cypher(property_name)
            query = f"CREATE INDEX `prim_property_{safe_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{safe_name}`)"
            logger.debug("create_prim_property_index query: %s", query)
            await session.run(query)
            cache.mark_string_indexed(property_name)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=RETRY_CONDITION,
    )
    async def _create_numeric_property_index(self, session: AsyncSession, property_name: str, numeric_type: str):
        cache = self._property_index_cache
        if cache.is_numeric_indexed(property_name, numeric_type):
            return
        async with cache.lock_for(f"{_STRING_INDEX_PREFIX}{numeric_type}_{property_name}"):
            if cache.is_numeric_indexed(property_name, numeric_type):
                return
            safe_name = sanitize_for_cypher(property_name)
            query = f"CREATE INDEX `prim_property_{numeric_type}_{safe_name}` IF NOT EXISTS FOR (p:Prim) ON (p.`property_{numeric_type}_{safe_name}`)"
            logger.debug("create_numeric_property_index query: %s", query)
            await session.run(query)
            cache.mark_numeric_indexed(property_name, numeric_type)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=RETRY_CONDITION,
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
        retry=RETRY_CONDITION,
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
            root_prim_filter = "(p.root_prim = true OR p.default_prim = true)"
        elif root_prim:
            root_prim_filter = "p.root_prim = true"
        elif default_prim:
            default_prim_filter = "p.default_prim = true"

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
        retry=RETRY_CONDITION,
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
        retry=RETRY_CONDITION,
    )
    async def delete_prims(self, scene_url: str, session: Optional[AsyncSession] = None) -> None:
        session = session or self._session
        query = "MATCH (n:Prim {scene_url:$scene_url}) CALL { WITH n DETACH DELETE n }"
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

        await self._create_property_indexes(prims)

    async def _create_property_indexes(self, prims: list[PrimCreateModel]) -> None:
        # Create indices for prim properties
        # Must be run outside of transaction as it is a schema changing operation
        numeric_properties_seen = set()

        for prim in prims:
            # Create string property indexes
            for property_name, property_value in prim.properties.items():
                if property_index_excluded(property_name):
                    continue

                # Oversized values are stored unindexed (see _create_multiple_prims), so skip
                # creating an index that Neo4j would refuse to populate for them.
                if not property_value_too_large(property_value):
                    await self._create_prim_property_index(self._session, property_name)

                # Check if this property has numeric values and create numeric indexes
                _, numeric_value, numeric_type = detect_numeric_property(property_value)
                if numeric_value is not None:
                    numeric_key = f"{numeric_type}_{property_name}"
                    if numeric_key not in numeric_properties_seen:
                        await self._create_numeric_property_index(self._session, property_name, numeric_type)
                        numeric_properties_seen.add(numeric_key)

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=RETRY_WAIT_STRATEGY,
        retry=RETRY_CONDITION,
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
                    # Store original string properties. Values larger than Neo4j's index size
                    # limit go under a non-indexed `raw_property_` prefix so the write does not
                    # fail on the per-value index limit; they are folded back into `properties`
                    # on read (see Prim.from_db).
                    for k, v in prim.properties.items():
                        prefix = UNINDEXED_PROPERTY_PREFIX if property_value_too_large(v) else "property_"
                        prim_data["extra"][f"{prefix}{k}"] = v
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
            result = await session.run(query, prims=prims_data, timeout=60 * 60 * 2)
            await result.consume()

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

            # One row per connection, each matched through the (scene_url, usd_path) and url indexes.
            # (Collecting matches per asset node used to connect only the first prim of each
            # source asset / scene.) MERGE keeps two concurrent stores of one scene from doubling them.
            source_asset_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Asset {url: connection.source_asset_url}) "
                "MATCH (b:Prim {scene_url: connection.scene_url, usd_path: connection.usd_path}) "
                "MERGE (a)-[:SOURCE_ASSET]->(b)"
            )

            root_prim_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Asset {url: connection.asset_url}) "
                "MATCH (b:Prim {scene_url: connection.scene_url, usd_path: connection.usd_path}) "
                "MERGE (a)-[:ROOT_PRIM]->(b)"
            )

            parent_prim_query = (
                "UNWIND $connections AS connection "
                "MATCH (a:Prim {scene_url: connection.scene_url, usd_path: connection.usd_path}) "
                "MATCH (b:Prim {scene_url: connection.scene_url, usd_path: connection.parent_usd_path}) "
                "MERGE (a)-[:PARENT]->(b)"
            )

            # Due to what appears to be a bug in neo4j, connections must be processed in batches.
            # The bug occurs when neo4j clears the internal query cache during the insert operation, which seems to
            # clear the cache for all the operations in `UNWIND` clause, making it incredibly slow.
            # Using smaller batches doesn't eliminate the issue, but makes it limited to a single batch.
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
