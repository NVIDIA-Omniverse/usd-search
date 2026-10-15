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
import json
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

# Lucene caps a single indexed term (keyword field) at 32766 bytes of UTF-8. The
# OpenSearch mapping indexes `usd_properties.value` as a keyword, so a value whose
# UTF-8 encoding exceeds this rejects the *entire* document write with an
# illegal_argument_exception ("immense term"). Such properties (e.g. a comma-joined
# list of every robot joint path) are skipped rather than truncated.
_MAX_USD_PROPERTY_VALUE_BYTES = 32766

#: Response header the graph builder uses to report per-phase build timings
#: (Kit startup, stage open, traversal). Kept out of the response body because
#: the success body is the graph document, forwarded verbatim to AGS.
GRAPH_BUILD_TIMINGS_HEADER = "X-Graph-Build-Timings"

tracer = trace.get_tracer(__name__)

MAX_OS_FLOAT_VALUE = 3.4028234663852886e38


class AGSPluginStatus(str, Enum):
    """Per-asset outcome recorded for the asset-graph plugin.

    The build path used to collapse every failure into ``graph_construction_failed``,
    which made a crawl's failure rate impossible to act on — "5% failed" says
    nothing about whether to raise the memory limit, fix credentials, or ignore a
    handful of broken assets. The graph builder now returns a ``reason`` with every
    failure (``graph_builder.failures.GraphBuildReason``) and it is mapped here.

    ``graph_construction_failed`` is kept as the catch-all for unmapped or missing
    reasons, so anything already matching on it still sees the unclassified tail.
    """

    success = "success"
    graph_construction_failed = "graph_construction_failed"
    graph_storage_failed = "graph_storage_failed"
    # Kit exceeded the builder's memory watchdog, or was OOM-killed by the kernel.
    graph_construction_oom = "graph_construction_oom"
    # The build exceeded the configured timeout.
    graph_construction_timeout = "graph_construction_timeout"
    # The stage could not be opened (malformed layer, unresolvable sublayer, ...).
    graph_construction_open_layer_failed = "graph_construction_open_layer_failed"
    # The storage backend reports the asset does not exist.
    graph_construction_asset_not_found = "graph_construction_asset_not_found"
    # The storage backend rejected the credentials, or could not be reached.
    graph_construction_access_denied = "graph_construction_access_denied"
    # Kit exited non-zero without classifying the failure itself.
    graph_construction_kit_crashed = "graph_construction_kit_crashed"
    # The kit-worker sidecar was unreachable or restarted mid-request.
    graph_construction_service_unavailable = "graph_construction_service_unavailable"


#: ``GraphBuildReason`` (graph-builder wire value) -> per-asset status. Kept as a
#: plain mapping rather than importing the builder's enum: the plugin ships in the
#: usdsearch image and the builder in the Kit image, and they are versioned apart.
GRAPH_BUILD_REASON_STATUSES: Dict[str, AGSPluginStatus] = {
    "oom": AGSPluginStatus.graph_construction_oom,
    "timeout": AGSPluginStatus.graph_construction_timeout,
    "open_layer_failed": AGSPluginStatus.graph_construction_open_layer_failed,
    "asset_not_found": AGSPluginStatus.graph_construction_asset_not_found,
    "access_denied": AGSPluginStatus.graph_construction_access_denied,
    "kit_crashed": AGSPluginStatus.graph_construction_kit_crashed,
    "client_disconnected": AGSPluginStatus.graph_construction_service_unavailable,
    "internal_error": AGSPluginStatus.graph_construction_failed,
}


def _is_phase_label(phase: Any) -> bool:
    """Whether ``phase`` is safe to use as a metric label value.

    Phase names come from the graph builder, which is versioned apart from this
    plugin, and each distinct one becomes its own time series. New phases are
    expected; an unbounded set (a phase named after a prim, say) is not — so
    accept only identifier-shaped names and let the span carry the rest.
    """
    return isinstance(phase, str) and phase.isidentifier()


class GraphConstructionError(Exception):
    """A graph build that failed with a known reason.

    Raised by :meth:`AssetGraphGeneration.get_graph` so ``preprocess`` can record
    the specific status instead of the catch-all.
    """

    def __init__(self, message: str, status: AGSPluginStatus = AGSPluginStatus.graph_construction_failed) -> None:
        super().__init__(message)
        self.status = status


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
    # Wall clock the *builder* gets for one build, sent with every request so the
    # effective timeout is decided in one place (the chart derives both this and
    # `get_graph_timeout` from `kit_worker.timeout_seconds`). Left unset, the
    # builder falls back to its own `KIT_TIMEOUT_SECONDS` default — which is what
    # a deployment predating this field does.
    build_timeout: Optional[int] = None
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
                # Kit-bound form: omni.client reads TLS off the endpoint string, not `ssl`.
                storage_api_url=storage_client.config.kit_storage_api_url,
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
        body: Dict[str, Any] = {"url": url}
        # The builder accepts a per-request timeout and caps it server-side. Sending
        # it keeps the client's own `get_graph_timeout` provably longer than the
        # build it is waiting on, so a slow build ends as the builder's 408 (which
        # carries a reason) rather than an opaque client-side timeout.
        if self.config.build_timeout:
            body["timeout_seconds"] = int(self.config.build_timeout)
        body.update(**auth_kwargs)

        logger.debug("Requesting graph for %s", body)

        # Note: no `raise_for_status=True`. It raises on the status line alone and
        # never reads the body — which is exactly where the graph builder puts the
        # `reason` for the failure. Handle the status explicitly instead, the same
        # way `store_graph` does.
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.get_graph_timeout),
        ) as session:
            async with session.post(f"{self.kit_worker_url}/construct_graph/", json=body) as resp:
                # Record where the build spent its time on whichever span is
                # current — `preprocess` runs this inside its per-asset
                # `get_graph` span, so the phase breakdown lands on the span that
                # already measures the call, on both the success and failure path.
                self._record_build_timings(resp.headers.get(GRAPH_BUILD_TIMINGS_HEADER), url)
                if resp.status >= 400:
                    raise self._graph_construction_error(await self._read_error_body(resp), resp.status)
                return await resp.json()

    def _record_build_timings(self, header_value: Optional[str], url: str) -> None:
        """Attach the builder's phase timings to the current span and to metrics.

        Kit startup, stage open and traversal happen in a subprocess of another
        service, so these numbers cannot be derived here — the builder measures
        them and hands them over on a response header. Chiefly this answers "how
        much of a build is Kit cold start", which is what decides whether warming
        Kit up is worth doing.

        Both destinations earn their keep: the span keeps per-asset attribution
        ("*this* asset spent 22 minutes in traverse"), while the metrics give the
        distribution over a whole crawl without depending on trace sampling.
        """
        if not header_value:
            return
        try:
            timings = json.loads(header_value)
        except ValueError:
            logger.warning("Malformed %s header for %s", GRAPH_BUILD_TIMINGS_HEADER, url)
            return

        span = trace.get_current_span()
        if timings.get("kit_startup_ms") is not None:
            span.set_attribute("graph_build.kit_startup_ms", timings["kit_startup_ms"])
            self._observe_phase("kit_startup", timings["kit_startup_ms"])
        if timings.get("total_ms") is not None:
            span.set_attribute("graph_build.total_ms", timings["total_ms"])
            self._observe_phase("total", timings["total_ms"])
        if timings.get("died_in"):
            span.set_attribute("graph_build.died_in", timings["died_in"])
            if self.phase_metrics is not None and _is_phase_label(timings["died_in"]):
                self.phase_metrics.count_failure_phase(timings["died_in"])
        for phase, duration_ms in (timings.get("phases") or {}).items():
            span.set_attribute(f"graph_build.phase.{phase}_ms", duration_ms)
            self._observe_phase(phase, duration_ms)

        logger.debug("Graph build timings for %s: %s", url, timings)

    def _observe_phase(self, phase: str, duration_ms: Any) -> None:
        """Record one phase duration, in seconds, if a metrics sink is attached."""
        if self.phase_metrics is None or not _is_phase_label(phase):
            return
        try:
            self.phase_metrics.observe_phase(phase, float(duration_ms) / 1000)
        except (TypeError, ValueError):
            logger.warning("Non-numeric duration for build phase %r: %r", phase, duration_ms)

    @staticmethod
    async def _read_error_body(resp: aiohttp.ClientResponse) -> Dict[str, Any]:
        """Best-effort decode of a graph-builder error body."""
        try:
            body = await resp.json()
        except Exception:  # noqa: BLE001 — a non-JSON error body must not mask the failure
            body = None
        if isinstance(body, dict):
            return body
        try:
            return {"detail": (await resp.text()).strip()}
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _graph_construction_error(body: Dict[str, Any], http_status: int) -> GraphConstructionError:
        """Map a graph-builder error body onto a per-asset status."""
        reason = body.get("reason")
        status = GRAPH_BUILD_REASON_STATUSES.get(reason, AGSPluginStatus.graph_construction_failed)
        if reason is not None and status is AGSPluginStatus.graph_construction_failed:
            # A builder newer than this plugin, or a genuinely unclassified failure.
            logger.warning("Unrecognized graph construction reason %r; recording as %s", reason, status.value)
        detail = body.get("detail") or "graph construction failed"
        return GraphConstructionError(f"{http_status}: {detail}", status=status)

    async def store_graph(self, graph):
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.store_graph_timeout, sock_read=None),
        ) as session:
            async with session.post(f"{self.graph_service_url}/asset_graph/", json=graph) as resp:
                if resp.status >= 400:
                    # AGS returns the validation detail (e.g. which prim fields failed on a 422)
                    # in the response body. Fold it into the raised error so callers see *why*
                    # the write was rejected, not just the bare "422, message='Unprocessable Entity'".
                    body = (await resp.text()).strip()
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                        message=f"{resp.reason}: {body}" if body else resp.reason,
                        headers=resp.headers,
                    )
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

            unavailable_count = 0

            for index, path in enumerate(data):
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
                    # A kit-worker OOM kill drops the connection mid-request. This
                    # used to raise straight out of the loop, failing the *whole*
                    # batch — including assets that had already built fine and ones
                    # never attempted — which is why the observed failure rate was
                    # both opaque and inflated. Record it per asset and carry on;
                    # `wait_for_kit_worker` blocks until the sidecar is back.
                    unavailable_count += 1
                    self.logger.warning(
                        "Kit worker unavailable while processing %s (%s)",
                        path["omni_path"],
                        exc,
                    )
                    error_indices[index] = AGSPluginErrorItem(
                        status=AGSPluginStatus.graph_construction_service_unavailable,
                        path=path["omni_path"],
                        error_message=f"AGS Kit unavailable: {exc}",
                    )
                except GraphConstructionError as exc:
                    self.logger.error("Processing %s failed (%s): %s", path["omni_path"], exc.status.value, exc)
                    error_indices[index] = AGSPluginErrorItem(
                        status=exc.status,
                        path=path["omni_path"],
                        error_message=str(exc),
                    )
                except Exception as exc:
                    self.logger.error("Processing %s failed", path["omni_path"], exc_info=exc)
                    error_indices[index] = AGSPluginErrorItem(
                        status=AGSPluginStatus.graph_construction_failed,
                        path=path["omni_path"],
                        error_message=str(exc),
                    )

            # Every asset failing to connect means the sidecar is down rather than
            # the assets being bad. Escalate so the batch is retried instead of
            # burning through the corpus marking everything failed.
            if data and unavailable_count == len(data):
                raise ConnectionError("AGS Kit unavailable")

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
    def _format_property_for_os(name: str, value: Any) -> Optional[Dict[str, Union[str, float, None]]]:
        """
        Format a single property for OpenSearch storage with numeric type support.

        Args:
            name: Property name
            value: Property value. Usually a string, but USD custom-layer metadata
                (e.g. SimReady) can carry bools/ints/floats that survive the JSON
                round-trip as native types, so it is coerced to ``str`` here — the
                OpenSearch ``value``/``value_sayt`` keyword fields require a string.

        Returns:
            Dict with name, value, and optional numeric fields, or ``None`` if the value
            exceeds the max keyword-term byte length and the property must be skipped.
        """
        value = str(value)
        value_bytes = len(value.encode("utf-8"))
        if value_bytes > _MAX_USD_PROPERTY_VALUE_BYTES:
            logger.warning(
                "Skipping USD property %r: value is %d bytes, exceeds the %d-byte OpenSearch "
                "keyword-term limit (would reject the whole document); property dropped.",
                name,
                value_bytes,
                _MAX_USD_PROPERTY_VALUE_BYTES,
            )
            return None

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
            "usd_properties": [
                formatted
                for k, v in properties.items()
                if (formatted := self._format_property_for_os(k, v)) is not None
            ],
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
