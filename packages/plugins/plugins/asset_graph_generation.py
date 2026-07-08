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

# standard modules
import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

# third-party modules
import aiohttp
import aiohttp.client_exceptions
from cache.src import GenericPluginStatus, PluginItemStatus
from opentelemetry import trace
from pydantic import Field
from pydantic_settings import SettingsConfigDict

# local/proprietary modules
from storage.src.client import NGSearchStorageHelper, Result, StorageClientInput

from search_utils.storage_client import PathType, StorageClient
from search_utils.storage_client.nucleus.client import NucleusStorageClient
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.storage_api.client import StorageAPIStorageClient

from .base_plugin import BasePlugin, BasePluginConfig
from .models import GenericPluginErrorItem, PluginProcessingResult

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)

MAX_OS_FLOAT_VALUE = 3.4028234663852886e38


class AGSPluginStatus(str, Enum):
    success = "success"
    graph_construction_failed = "graph_construction_failed"
    graph_storage_failed = "graph_storage_failed"


class AGSPluginBatchItem(TypedDict):
    graph: Any
    path: str


class AGSPluginErrorItem(GenericPluginErrorItem):
    path: str


class AGSPluginConfig(BasePluginConfig):
    graph_service_url: str = Field(
        default="http://deepsearch-asset-graph-service:8000",
        alias="asset_graph_service_endpoint",
    )
    kit_worker_url: str = Field(default="http://localhost:8000", alias="kit_worker_service_endpoint")
    get_graph_timeout: float = 60 * 30  # 30 minutes
    store_graph_timeout: float = 60 * 30  # 30 minutes
    use_embedding_client: bool = False
    model_config = SettingsConfigDict(env_prefix="ags_plugin_")


class AssetGraphGeneration(BasePlugin):
    """
    Constructs several graphs based on the prim hierarchy of a USD file. This plugin is an essential component of Asset Graph Service (AGS).
    """

    def __init__(self, config: Optional[AGSPluginConfig] = None) -> None:
        if config is None:
            config = AGSPluginConfig()

        super().__init__(
            plugin_name="asset_graph_generation",
            data_types=set(["usd", "usda", "usdc", "usdz"]),
            render=False,
            namespace=".deeptag.asset_graph",
            system_namespace=".deeptag.asset_graph_plugin",
            config=config,
        )
        self.graph_service_url = self.config.graph_service_url
        self.kit_worker_url = self.config.kit_worker_url

    @property
    def config(self) -> AGSPluginConfig:
        return self._config

    def load_data(
        self,
        omni_path: Optional[str] = None,
        data=None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        return {
            "omni_path": omni_path,
            "status": status,
            "error_message": error_message,
        }

    async def get_omni_file(self, omni_item: PathType, storage_client=None, timeout: float = 60):
        return {"data": None}

    def default_on_none(self, parameter: Optional[str], default: str = None) -> str:
        if default is None:
            default = ""
        if parameter is None:
            return default
        return parameter

    def get_authentication_parameters(self, url: str, storage_client: StorageClient) -> Dict[str, str]:
        if isinstance(storage_client, NucleusStorageClient):
            return {
                "omni_user": storage_client._auth.user,
                "omni_pass": storage_client._auth.password,
            }
        if isinstance(storage_client, S3StorageClient):
            return {
                "aws_bucket": storage_client.config.bucket_name,
                "aws_region": self.default_on_none(storage_client.config.region_name),
                "aws_access_key": self.default_on_none(storage_client.config.aws_secret_access_key),
                "aws_access_key_id": self.default_on_none(storage_client.config.aws_access_key_id),
                **(
                    {"aws_endpoint_url": storage_client.config.aws_endpoint_url}
                    if storage_client.config.aws_endpoint_url
                    else {}
                ),
            }
        if isinstance(storage_client, StorageAPIStorageClient):
            auth_kwargs = dict(
                storage_api_url=storage_client.config.grpc_endpoint,
            )
            if storage_client.config.token is not None:
                auth_kwargs["storage_api_token"] = storage_client.config.token
            if storage_client.config.openid_client_id is not None:
                auth_kwargs["storage_api_openid_client_id"] = storage_client.config.openid_client_id
            if storage_client.config.openid_client_secret is not None:
                auth_kwargs["storage_api_openid_client_secret"] = storage_client.config.openid_client_secret
            if storage_client.config.openid_token_url is not None:
                auth_kwargs["storage_api_openid_token_url"] = storage_client.config.openid_token_url
            if storage_client.config.openid_scope is not None:
                auth_kwargs["storage_api_openid_scope"] = storage_client.config.openid_scope
            if storage_client.config.openid_grant_type is not None:
                auth_kwargs["storage_api_openid_grant_type"] = storage_client.config.openid_grant_type

            return auth_kwargs

        raise NotImplementedError(f"support for {type(storage_client)} client is not added in the Asset Graph Service")

    async def add_metadata(self, path: str, content: dict, storage_client: NGSearchStorageHelper) -> Result:
        return await storage_client.update_meta(input=StorageClientInput(key=path, meta=content))

    async def get_graph(self, url: str, storage_client: StorageClient):
        auth_kwargs = self.get_authentication_parameters(url=url, storage_client=storage_client)
        body = {"url": url}
        body.update(**auth_kwargs)

        logger.debug("Requesting graph for %s", body)

        async with aiohttp.ClientSession(
            raise_for_status=True,
            timeout=aiohttp.ClientTimeout(total=self.config.get_graph_timeout),
        ) as session:
            async with session.post(f"{self.kit_worker_url}/construct_graph/", json=body) as resp:
                return await resp.json()

    async def store_graph(self, graph):
        async with aiohttp.ClientSession(
            raise_for_status=True,
            timeout=aiohttp.ClientTimeout(total=self.config.store_graph_timeout, sock_read=None),
        ) as session:
            async with session.post(f"{self.graph_service_url}/asset_graph/", json=graph) as resp:
                return await resp.json()

    async def wait_for_kit_worker(self) -> None:
        while True:
            try:
                async with aiohttp.ClientSession(raise_for_status=True) as session:
                    async with session.get(f"{self.kit_worker_url}/docs") as response:
                        if response.status == 200:
                            return
            except aiohttp.client_exceptions.ClientConnectionError as exc:
                self.logger.warning("Kit worker unavailable %s", str(exc))
                await asyncio.sleep(2)

            except aiohttp.client_exceptions.ClientResponseError as exc:
                self.logger.warning("Unexpected response %s", str(exc))
                await asyncio.sleep(2)

    async def preprocess(
        self,
        data: list,
        storage_client: StorageClient,
    ) -> Tuple[list[AGSPluginBatchItem], list[str], Dict[str, AGSPluginErrorItem]]:
        with tracer.start_as_current_span("asset_graph_generation.preprocess") as span:
            span.set_attribute("data_length", len(data))

            batch_data: list[AGSPluginBatchItem] = []
            indices: list[str] = []
            error_indices: Dict[str, AGSPluginErrorItem] = {}

            for index, path in enumerate(data):
                # TODO: Add error handling
                try:
                    with tracer.start_as_current_span("asset_graph_generation.wait_for_kit_worker"):
                        await self.wait_for_kit_worker()
                    self.logger.info("Building graph for %s ...", path["omni_path"])
                    with tracer.start_as_current_span("asset_graph_generation.get_graph") as item_span:
                        item_span.set_attribute("omni_path", path["omni_path"])
                        graph = await self.get_graph(path["omni_path"], storage_client=storage_client)
                    indices.append(index)
                    batch_data.append(AGSPluginBatchItem(graph=graph, path=path["omni_path"]))
                    self.logger.debug("Graph for %s: %s", path["omni_path"], graph)
                except aiohttp.client_exceptions.ClientConnectionError as exc:
                    raise ConnectionError("AGS Kit unavailable") from exc
                except Exception as exc:
                    self.logger.error("Processing %s failed", path["omni_path"], exc_info=exc)
                    error_indices[index] = AGSPluginErrorItem(
                        status=AGSPluginStatus.graph_construction_failed,
                        path=path["omni_path"],
                        error_message=str(exc),
                    )

            span.set_attribute("batch_data_length", len(batch_data))
            span.set_attribute("error_indices_length", len(error_indices))
            return batch_data, indices, error_indices

    @staticmethod
    def _extract_properties_from_default_prim(graph) -> dict:
        default_prim_path = graph.get("default_prim_path", None)
        if not default_prim_path:
            logger.warning("No default prim path for %s", graph["scene_url"])
            return {}

        prims = graph.get("prims", {})
        default_prim = prims.get(default_prim_path)
        if not default_prim:
            logger.warning(
                "Default prim path '%s' not found in prims for asset %s.",
                default_prim_path,
                graph["scene_url"],
            )
            return {}

        default_prim_properties = default_prim.get("properties", {})
        logger.debug(
            "Default prim properties for %s: %s",
            graph["scene_url"],
            default_prim_properties,
        )
        return default_prim_properties

    @staticmethod
    def _enforce_os_limits(float_input: float) -> float:
        return max(min(float_input, MAX_OS_FLOAT_VALUE), -1 * MAX_OS_FLOAT_VALUE)

    @staticmethod
    def _extract_dimensions_from_default_prim(graph: dict) -> dict:
        default_prim_path = graph.get("default_prim_path", None)
        if not default_prim_path:
            logger.warning("No default prim path for %s", graph["scene_url"])
            return {}

        prims: dict = graph.get("prims", {})
        default_prim: dict = prims.get(default_prim_path)
        if not default_prim:
            logger.warning(
                "Default prim path '%s' not found in prims for asset %s.",
                default_prim_path,
                graph["scene_url"],
            )
            return {}

        # Extract dimensional data from the default prim
        dimensions = {}

        # Raw bounding box data - use _x, _y, _z suffixes
        bbox_max = default_prim.get("bbox_max", [])
        bbox_min = default_prim.get("bbox_min", [])
        bbox_midpoint = default_prim.get("bbox_midpoint", [])

        axis_suffixes = ["_x", "_y", "_z"]

        # Store bbox_max with proper field names
        if isinstance(bbox_max, list) and len(bbox_max) >= 3:
            for i, suffix in enumerate(axis_suffixes):
                if i < len(bbox_max):
                    dimensions[f"bbox_max{suffix}"] = AssetGraphGeneration._enforce_os_limits(bbox_max[i])

        # Store bbox_min with proper field names
        if isinstance(bbox_min, list) and len(bbox_min) >= 3:
            for i, suffix in enumerate(axis_suffixes):
                if i < len(bbox_min):
                    dimensions[f"bbox_min{suffix}"] = AssetGraphGeneration._enforce_os_limits(bbox_min[i])

        # Store bbox_midpoint with proper field names
        if isinstance(bbox_midpoint, list) and len(bbox_midpoint) >= 3:
            for i, suffix in enumerate(axis_suffixes):
                if i < len(bbox_midpoint):
                    dimensions[f"bbox_midpoint{suffix}"] = AssetGraphGeneration._enforce_os_limits(bbox_midpoint[i])

        # Computed dimensions - check if AGS provided them, otherwise calculate from max-min
        for i, suffix in enumerate(axis_suffixes):
            dim_key = f"bbox_dimension{suffix}"
            if dim_key in default_prim:
                # AGS provided the dimension
                dimensions[dim_key] = AssetGraphGeneration._enforce_os_limits(default_prim[dim_key])
            elif isinstance(bbox_max, list) and isinstance(bbox_min, list) and len(bbox_max) > i and len(bbox_min) > i:
                # Calculate dimension from max - min
                dimensions[dim_key] = AssetGraphGeneration._enforce_os_limits(abs(bbox_max[i] - bbox_min[i]))

        # Scale-adjusted dimensions - check if AGS provided them, otherwise calculate
        scale_x = default_prim.get("scale_x", 1.0)
        scale_y = default_prim.get("scale_y", 1.0)
        scale_z = default_prim.get("scale_z", 1.0)
        scales = [scale_x, scale_y, scale_z]

        for i, suffix in enumerate(axis_suffixes):
            scaled_dim_key = f"scaled_bbox_dimension{suffix}"
            if scaled_dim_key in default_prim:
                # AGS provided the scaled dimension
                dimensions[scaled_dim_key] = AssetGraphGeneration._enforce_os_limits(default_prim[scaled_dim_key])
            elif isinstance(bbox_max, list) and isinstance(bbox_min, list) and len(bbox_max) > i and len(bbox_min) > i:
                # Calculate scaled dimension from (max - min) * scale
                raw_dimension = abs(bbox_max[i] - bbox_min[i])
                dimensions[scaled_dim_key] = AssetGraphGeneration._enforce_os_limits(raw_dimension * scales[i])

        # Transform data - store scales individually
        if "scale_x" in default_prim:
            dimensions["scale_x"] = default_prim["scale_x"]
        if "scale_y" in default_prim:
            dimensions["scale_y"] = default_prim["scale_y"]
        if "scale_z" in default_prim:
            dimensions["scale_z"] = default_prim["scale_z"]

        # Store translate with proper field names
        if "translate" in default_prim and isinstance(default_prim["translate"], list):
            translate = default_prim["translate"]
            for i, suffix in enumerate(axis_suffixes):
                if i < len(translate):
                    dimensions[f"translate{suffix}"] = translate[i]

        # Scene-level metadata
        if "scene_mpu" in graph:
            dimensions["scene_mpu"] = graph["scene_mpu"]
        if "scene_up_axis" in graph:
            dimensions["scene_up_axis"] = graph["scene_up_axis"]

        logger.debug("Default prim dimensions for %s: %s", graph["scene_url"], dimensions)
        return dimensions

    @staticmethod
    def _detect_numeric_value(value: str) -> Tuple[Optional[float], str]:
        """
        Detect if a string value can be converted to a numeric type.

        Args:
            value: String value to check

        Returns:
            Tuple of (numeric_value_or_none, type_string)
            type_string is "int", "float", or "string"
        """
        # Try int conversion first (more restrictive)
        try:
            int_val = int(value)
            # Ensure no precision loss (e.g., "1.0" should be float, not int)
            if str(int_val) == value:
                return float(int_val), "int"
        except ValueError:
            pass

        # Try float conversion
        try:
            float_val = float(value)
            # Reject inf and nan
            if str(float_val) not in ("inf", "-inf", "nan"):
                return float_val, "float"
        except ValueError:
            pass

        return None, "string"

    @staticmethod
    def _format_property_for_os(name: str, value: str) -> Dict[str, Union[str, float, None]]:
        """
        Format a single property for OpenSearch storage with numeric type support.

        Args:
            name: Property name
            value: Property value (string)

        Returns:
            Dict with name, value, and optional numeric fields
        """
        numeric_value, value_type = AssetGraphGeneration._detect_numeric_value(value)

        property_doc = {
            "name": name,
            "name_sayt": name,
            "value": value,
            "value_sayt": value,
            "value_type": value_type,
        }

        # Only include value_numeric if it's actually numeric
        if numeric_value is not None:
            property_doc["value_numeric"] = numeric_value

        return property_doc

    def get_os_content(self, graph) -> Dict[str, List[Dict[str, Any]]]:
        properties = self._extract_properties_from_default_prim(graph)
        dimensions = self._extract_dimensions_from_default_prim(graph)

        os_content = {
            "usd_properties": [self._format_property_for_os(k, v) for k, v in properties.items()],
            "usd_dimensions": dimensions,
        }
        logger.debug("OS content for %s: %s", graph["scene_url"], os_content)
        return os_content

    async def process_valid_items(
        self,
        batch_data: list[AGSPluginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:

        with tracer.start_as_current_span("asset_graph_generation.process_valid_items") as span:
            span.set_attribute("batch_data_length", len(batch_data))
            span.set_attribute("indices_length", len(indices))
            span.set_attribute("sample_ids_length", len(sample_ids))

            self.logger.debug(
                "In process batch_data: %s, indices: %s, sample_ids: %s",
                batch_data,
                indices,
                sample_ids,
            )
            results: Dict[int, PluginProcessingResult] = {}
            for batch_item, item_index in zip(batch_data, indices):
                self.logger.info("Storing graph for %s in the asset graph service...", batch_item["path"])
                with tracer.start_as_current_span("asset_graph_generation.store_graph") as item_span:
                    item_span.set_attribute("path", batch_item["path"])
                    await self.store_graph(batch_item["graph"])
                self.logger.info("Graph for %s stored successfully", batch_item["path"])
                results[sample_ids[item_index]] = {
                    "asset_status": PluginItemStatus(
                        status=GenericPluginStatus.ok.value,
                        processing_timestamp=time.time(),
                    ),
                    "search_backend_content": {self.plugin_name: self.get_os_content(batch_item["graph"])},
                }

            return results

    def clean_up(self) -> bool:
        return True
