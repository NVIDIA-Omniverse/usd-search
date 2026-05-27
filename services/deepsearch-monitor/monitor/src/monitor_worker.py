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
import dataclasses
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from queue import Empty
from typing import AsyncIterator, Dict, List, Optional, Tuple, Union

from cache.src import (
    CacheConnectionError,
    GenericPluginStatus,
    JobItem,
    JobItemType,
    PluginItemStatus,
    ResultItem,
)
from cache.src.client import CacheClientRedis
from cache.src.client.config import RedisCacheConfig
from deepsearch_utils.ds_plugin_utils import GetFileResponse
from deepsearch_utils.farm.client import FarmClient, K8sRenderer
from deepsearch_utils.rendering_service.client import RenderingServiceClient

# third party modules
from fire import Fire
from monitor.src.logging_utils import setup_logging
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import (
    OTELResourceDetector,
    Resource,
    get_aggregated_resources,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from plugins import BasePlugin, Plugins
from prometheus_client import Counter, Gauge, Histogram

from search_utils.hashing_utils import get_hash
from search_utils.log_utils import prepare_message, print_wrapper
from search_utils.omni_microservice import AssetdbMS
from search_utils.prometheus_utils import GenericPublisher
from search_utils.storage_client import (
    PathType,
    RemoteFileUri,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.storage_client.utils import task_wrapper

from .config import AssetDBConfig as service_Config
from .config import DeepSearchMonitorWorkerConfig

# local / proprietary modules


logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


class MonitorWorker(AssetdbMS):
    def __init__(
        self,
        worker_config: Optional[DeepSearchMonitorWorkerConfig] = None,
        config: service_Config = service_Config,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        cache_config: Optional[RedisCacheConfig] = None,
        **kwargs,
    ):
        if worker_config is None:
            worker_config = DeepSearchMonitorWorkerConfig()

        self._omni_service = f"deepsearch-plugin-worker-{worker_config.plugin_name}"

        # disable Redis tail auto trimming in workers. Since it is already done in the Monitor Crawler
        if cache_config is None:
            cache_config = RedisCacheConfig(cache_auto_trim_timeout=-1)
        else:
            cache_config.auto_trim_timeout = -1

        self._cache_config = cache_config
        self._worker_config = worker_config
        self.prom_labels: Dict[str, str] = {}

        super().__init__(
            config=config,
            log_name="monitor worker",
            use_prom_metrics=self._worker_config.use_metrics,
            connection_names=[],  # NOTE: these are legacy settings that are not used. To be cleaned up in the future.
            redis_url=service_Config.redis_url,  # NOTE: these are legacy settings that are not used. To be cleaned up in the future.
            redis_db_assetdbms=-1,  # NOTE: these are legacy settings that are not used. To be cleaned up in the future.
            **kwargs,
        )

        prepare_message(
            msg="Cache configuration:",
            item_list=[f"{k}: {v}" for k, v in self._cache_config.model_dump().items()],
            logger=logger.info,
        )

        prepare_message(
            msg="Worker configuration:",
            item_list=[f"{k}: {v}" for k, v in self._worker_config.model_dump().items()],
            logger=logger.info,
        )

        # save some parameters
        self.prom_metrics_port = self._worker_config.metrics_port
        self._n_parallel_queue_processors = self._worker_config.n_parallel_queue_processors
        self.use_prom_metrics = self._worker_config.use_metrics
        self.queue_processed = asyncio.Event()
        self._data_load_lock = asyncio.Lock()

        # plugin initialization
        self._plugin = Plugins.get_plugin(plugin_name=self._worker_config.plugin_name)

        if storage_config is None:
            self._storage_config = StorageConfig()
        else:
            self._storage_config = storage_config

        # storage backend client
        self._storage_client = get_client(
            client_type=self._storage_config.storage_backend_type,
            config=storage_client_config,
        )

        # initialize clients
        # > required prometheus metrics to be initialized
        self.farm_client: Optional[K8sRenderer] = None
        self.cache_client: Optional[CacheClientRedis] = None
        self.init_clients()
        # create task for initialization of storage connection
        # loop = asyncio.get_event_loop()
        # loop.create_task(task_wrapper(self.initialize_storage_connection, name="Storage initialization"))

        self.metric_processed_items: Optional[Counter] = None
        self.metric_item_processing_time: Optional[Histogram] = None
        self.metric_full_batch_processing_time: Optional[Histogram] = None

        # init prom metrics
        if self.use_prom_metrics:
            self.init_additional_prom_metrics()

    async def _terminate(self) -> None:
        """In practice this function is ont really used. It is convenient for tests to make sure all resources were deallocated"""
        await self.cache_client._terminate()

    def get_omni_service(self) -> str:
        return self._omni_service

    @asynccontextmanager
    async def get_next_items(self, count: Optional[int] = None) -> AsyncIterator[List[JobItem]]:
        """Get new jobs for processing and check if the Job type is in the list of types supported by the worker.

        Args:
            count (Optional[int], optional): Number of jobs that are processed at once. If set to None - will retrieve the default number of Jobs defined in Cache class (typically is 1). Defaults to None.

        Raises:
            ValueError: If Cache client is not set.

        Yields:
            Iterator[AsyncIterator[List[JobItem]]]: List of JobItems filtered by type
        """
        await self.cache_client.ready.wait()
        if self.cache_client is None:
            raise ValueError("Cache client is not set")

        jobs: List[JobItem] = []
        if self.use_prom_metrics:
            self.metric_plugin_tasks_count_per_group.set(
                await self.cache_client.plugin_queue_len(plugin_name=self._worker_config.plugin_name)
            )
        async with self.cache_client.get_plugin_job(plugin_name=self._worker_config.plugin_name, count=count) as jobs:
            jobs_for_processing: List[JobItem] = []
            job: JobItem
            for job in jobs:
                if job.get("job_type") is None:
                    if JobItemType.none in self._worker_config.job_item_type:
                        jobs_for_processing.append(job)
                else:
                    if job["job_type"] in self._worker_config.job_item_type:
                        jobs_for_processing.append(job)

            yield jobs_for_processing

    async def get_queue_len(self) -> int:
        await self.cache_client.ready.wait()
        if self.cache_client is None:
            raise ValueError("Cache client is not set")
        return await self.cache_client.plugin_queue_len(plugin_name=self._worker_config.plugin_name)

    async def insert_items(self, items: List[JobItem]) -> None:
        await self.cache_client.ready.wait()
        if self.cache_client is None:
            raise ValueError("Cache client is not set")

        for item in items:
            await self.cache_client.enqueue_plugin_job(plugin_name=self._worker_config.plugin_name, content=item)

    def init_clients(self) -> None:
        # initialize cache client
        self.cache_client = CacheClientRedis(config=self._cache_config, active_plugins=[self._plugin.plugin_name])
        # initialize farm client
        if self._plugin.render:
            self.farm_client: K8sRenderer = FarmClient(
                plugin_name=self._plugin.plugin_name,
                worker_type=self._cache_config.consumer_group,
                queue_host=self.config.farm_queue_host,
                queue_port=self.config.farm_queue_port,
                queue_protocol=self.config.farm_queue_protocol,
                ws_host=self.config.farm_ws_host,
                ws_port=self.config.farm_ws_port,
                ws_protocol=self.config.farm_ws_protocol,
                internal_ws_host=self.config.farm_internal_ws_host,
                internal_ws_port=self.config.farm_internal_ws_port,
                rendering_batch_size=self.config.farm_rendering_batch_size,
                rendering_batch_timeout=self.config.farm_rendering_batch_timeout,
                use_prom_metrics=self.use_prom_metrics,
                prom_metrics_labels=self.prom_labels,
                use_cache_server=False,
                storage_client=self._storage_client,
            )
            logger.info("Rendering client initialized: %s", self.farm_client)
        else:
            self.farm_client = None

    def init_additional_prom_metrics(self) -> None:
        # create prometheus metrics publisher
        self.prom_metrics = GenericPublisher(port=self.prom_metrics_port, labels=self.prom_labels)
        if self._plugin.render:
            self.not_requested_farm_tasks = Gauge(
                "omnideepsearch_running_farm_rendering_unique_items",
                "Count of unique items currently being rendered by the farm",
                labelnames=list(self.prom_labels.keys()),
            ).labels(*self.prom_labels.values())
        # get farm / non-farm label
        farm_label = "rendering" if self._plugin.render else "non-rendering"

        self.metric_processed_items = Counter(
            "omnideepsearch_worker_processed_items",
            "Count of items processed by the worker",
            labelnames=list(self.prom_labels.keys()) + ["worker_type", "plugin_name"],
        ).labels(*self.prom_labels.values(), farm_label, self._worker_config.plugin_name)

        self.metric_full_batch_processing_time = Histogram(
            "omnideepsearch_worker_batch_processing_duration_seconds",
            "Duration of processing a batch of results (recorded only for full batches)",
            buckets=(
                0.25,
                0.5,
                0.75,
                1.0,
                2.5,
                5.0,
                7.5,
                10.0,
                12.5,
                15.0,
                20.0,
                30.0,
                45.0,
                60.0,
                120.0,
                float("inf"),
            ),
            labelnames=list(self.prom_labels.keys()) + ["worker_type", "plugin_name"],
        ).labels(*self.prom_labels.values(), farm_label, self._worker_config.plugin_name)
        self.metric_item_processing_time = Histogram(
            "omnideepsearch_worker_item_processing_duration_seconds",
            "Duration of processing a single item by the worker (average from a batch)",
            labelnames=list(self.prom_labels.keys()) + ["worker_type", "plugin_name"],
        ).labels(*self.prom_labels.values(), farm_label, self._worker_config.plugin_name)

        self.metric_plugin_tasks_count_per_group = Gauge(
            "omnideepsearch_worker_plugin_tasks_count_per_group",
            "Count of tasks for a given plugin",
            labelnames=list(self.prom_labels.keys()) + ["worker_type", "plugin_name", "group_name"],
        ).labels(
            *self.prom_labels.values(),
            farm_label,
            self._worker_config.plugin_name,
            self._cache_config.consumer_group,
        )

        # start prometheus server
        self.prom_metrics.start_server()
        # init metrics processing task
        loop = asyncio.get_event_loop()
        loop.create_task(task_wrapper(self.process_metrics, name="Process metrics exporter"))

    def get_memory_metrics(self) -> None:
        super().get_memory_metrics()
        if self._plugin.render and not isinstance(self.farm_client, RenderingServiceClient):
            self.not_requested_farm_tasks.set(len(self.farm_client.uri_to_task_mapping))

    async def plugin_pipeline(
        self,
        paths: list,
        plugin_name: str,
        storage_client: StorageClient,
    ) -> List[ResultItem]:

        plugin: BasePlugin = Plugins.get_plugin(plugin_name)

        if not isinstance(paths, list):
            paths = [paths]

        # check that the file exists in omniverse
        exists = await asyncio.gather(*[storage_client.check_if_exists(path) for path in paths])
        paths = [plugin for plugin, e in zip(paths, exists) if e[0]]
        no_existent_paths = [plugin for plugin, e in zip(paths, exists) if not e[0]]

        if len(no_existent_paths) > 0:
            logger.info(
                dict(
                    message="plugin pipeline stats",
                    exists=len(paths),
                    not_exists=len(no_existent_paths),
                    not_existent_paths=[str(p) for p in no_existent_paths],
                )
            )

        if len(paths) == 0:
            logger.info("All paths in batch do not exist on storage — skipping plugin pipeline")
            return []

        # get omni file content
        with print_wrapper(f"load omni file content: {paths}", print_after=False, logger=logger.debug):
            omni_items, content = await self.load_omni_file_content(plugin, paths, storage_client=storage_client)
        # get sample data
        with print_wrapper(f"plugin load data: {paths}", print_after=False, logger=logger.debug):
            data = [
                plugin.load_data(
                    omni_path=path.uri,
                    data=content_item.get("data", None),
                    status=content_item.get("status", None),
                    error_message=content_item.get("error_message", None),
                )
                for path, content_item in zip(omni_items, content)
            ]
        # get formats from the data
        fmts = [os.path.splitext(path.uri)[1][1:] for path in omni_items]

        result, _ = await self.plugin_processing_pipeline(
            plugin=plugin,
            data=data,
            formats=fmts,
            config=self.config,
            return_plugin_reference=True,
            storage_client=storage_client,
            rendering_client=self.farm_client,
        )
        return [
            ResultItem(
                uri=it.uri,
                hash_value=PathType(
                    uri=it.uri,
                    hash_value=it.hash_value,
                    modified_date_seconds=it.modified_date_seconds,
                ).get_hash(),
                prediction=(dataclasses.asdict(result[r]) if dataclasses.is_dataclass(result[r]) else result[r]),
                asset_data={"plugins": {plugin_name: "added"}},
                asset_status=result[r]["asset_status"],
            )
            for r, it in zip(result, omni_items)
        ]

    async def load_omni_file_content(
        self,
        plugin: BasePlugin,
        paths: List[RemoteFileUri],
        storage_client: Optional[StorageClient] = None,
    ) -> Tuple[List[PathType], List[GetFileResponse]]:
        with tracer.start_as_current_span(
            "plugin.load_omni_file_content",
            attributes={
                "plugin.name": plugin.plugin_name,
                "plugin.paths_count": len(paths),
            },
        ) as span:
            # NOTE: this lock is needed, as sometimes large assets are loaded in parallel and occupy too much memory
            async with self._data_load_lock:
                server_responses: List[Optional[PathType]] = await asyncio.gather(
                    *[storage_client.get_item(path) for path in paths]
                )
                omni_paths: List[PathType] = [p for p in server_responses if p is not None]
                span.set_attribute("plugin.resolved_paths_count", len(omni_paths))

                content: List[dict] = []
                for r in omni_paths:
                    if plugin.should_process(file_type=os.path.splitext(r.uri)[1][1:]):
                        content.append(
                            await plugin.get_omni_file(
                                omni_item=r,
                                storage_client=storage_client,
                                timeout=self.config.usd_read_timeout,
                            )
                        )
                    else:
                        content.append({})
            return omni_paths, content

    @staticmethod
    async def plugin_processing_pipeline(
        plugin: Union[str, BasePlugin],
        data: list,
        formats: List[str],
        ids: Optional[List[int]] = None,
        return_plugin_reference: bool = False,
        storage_client: StorageClient = None,
        rendering_client: Optional[FarmClient] = None,
        config: service_Config = None,
    ) -> tuple:

        if isinstance(plugin, str):
            plugin: BasePlugin = Plugins.get_plugin(plugin)

        plugin_name = plugin.plugin_name
        with tracer.start_as_current_span(
            "plugin.processing_pipeline",
            attributes={
                "plugin.name": plugin_name,
                "plugin.input_size": len(data),
                "plugin.render": plugin.render,
            },
        ) as span:
            if ids is None:
                ids = list(range(len(data)))
            try:
                with tracer.start_as_current_span(
                    "plugin.preprocess", attributes={"plugin.name": plugin_name}
                ) as preprocess_span:
                    if plugin.render:
                        batch_data, indices, error_indices = await plugin.preprocess(
                            data=data,
                            formats=formats,
                            client=rendering_client,
                            storage_client=storage_client,
                        )
                    else:
                        batch_data, indices, error_indices = await plugin.preprocess(
                            data=data, storage_client=storage_client
                        )
                    preprocess_span.set_attribute("plugin.valid_count", len(indices))
                    preprocess_span.set_attribute("plugin.error_count", len(error_indices))

                assert len(batch_data) == len(
                    indices
                ), f"Extraction error: lengths of indices and batch data do not match ({len(batch_data)} vs {len(indices)})"

                results = await plugin.process(
                    batch_data=batch_data,
                    indices=indices,
                    error_indices=error_indices,
                    sample_ids=ids,
                    storage_client=storage_client,
                )
                assert len(results) == len(batch_data) + len(
                    error_indices
                ), f"Output size is incorrect: {len(results)=} vs {len(batch_data)=} + {len(error_indices)=}"

                span.set_attribute("plugin.result_count", len(results))
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise
            finally:
                plugin.clean_up()

            return results, plugin if return_plugin_reference else plugin.plugin_name

    async def process_batch(
        self,
        items: List[JobItem],
        storage_client: StorageClient,
    ) -> None:
        with tracer.start_as_current_span(
            "plugin.process_batch",
            attributes={
                "plugin.batch_size": len(items),
                "plugin.uris": [item["uri"] for item in items],
            },
        ) as span:
            plugin_group: Dict[str, List[RemoteFileUri]] = {}
            hash_dict: Dict[RemoteFileUri, str] = {}
            for job_item in items:
                plugin_group[job_item["plugin_name"]] = plugin_group.get(job_item["plugin_name"], []) + [
                    job_item["uri"]
                ]
                hash_dict[job_item["uri"]] = job_item.get("hash_value")
                logger.info(
                    "Processing item: %s hash: %s",
                    job_item["uri"],
                    job_item.get("hash_value"),
                )
                await self.cache_client.add_asset_status(
                    plugin_name=job_item["plugin_name"],
                    uri=job_item["uri"],
                    hash_value=job_item.get("hash_value"),
                    status=GenericPluginStatus.processing,
                )

            span.set_attribute("plugin.plugin_names", list(plugin_group.keys()))

            with print_wrapper("plugin pipeline", logger=logger.debug, print_after=False):
                plugin_results: Dict[str, List[ResultItem]] = {}
                for p_name, paths in plugin_group.items():
                    plugin_results[p_name] = await self.plugin_pipeline(
                        paths=paths,
                        plugin_name=p_name,
                        storage_client=storage_client,
                    )
                    if len(plugin_results[p_name]) == 0:
                        logger.info(
                            "Plugin '%s' produced no results for paths: %s",
                            p_name,
                            [str(p) for p in paths],
                        )

            total_results = 0
            for p_name, results in plugin_results.items():
                for r in results:
                    if hash_dict.get(r["uri"]) is not None:
                        logger.debug(
                            "%s -- %s vs %s",
                            r["uri"],
                            r["hash_value"],
                            hash_dict[r["uri"]],
                        )
                        r["hash_value"] = hash_dict[r["uri"]]
                    # store item status
                    asset_status: PluginItemStatus = r["asset_status"]
                    logger.info("setting '%s' status to %s", r["uri"], asset_status.status)
                    await self.cache_client.add_asset_status(
                        plugin_name=p_name,
                        uri=r["uri"],
                        hash_value=r["hash_value"],
                        status=asset_status.status,
                        exception=asset_status.exception,
                    )
                    # store results
                    logger.debug("Adding '%s' to results queue", r["uri"])
                    await self.cache_client.enqueue_result(r)
                    logger.debug("processing '%s' completed", r["uri"])
                    total_results += 1
            span.set_attribute("plugin.total_results", total_results)

    async def check_is_job_still_valid(self, job: JobItem) -> bool:
        """Check if the job is still valid i.e. if the item hasn't already been processed in another job

        Args:
            job (JobItem): Job definition

        Returns:
            bool: True if the Job is still valid
        """
        if self.cache_client is None:
            raise ValueError("Cache client is not set")

        try:
            cached_hash_value = await self.cache_client.plugin_get_raw(
                dest=f"{job['plugin_name']}_path_to_hash", key=job["uri"]
            )
        except KeyError:
            cached_hash_value = None

        # NOTE: if the values are equal - it means the job has already been processed
        return cached_hash_value != get_hash(job.get("hash_value"))

    async def process_next_batch(self, storage_client: StorageClient) -> Optional[List[JobItem]]:
        """Get next batch of items from respective stream and process them

        Args:
            storage_client (StorageClient): storage backend client

        Raises:
            ValueError: in case Cache client is not set

        Returns:
            Optional[List[JobItem]]: List of next items from the respective stream
        """
        items: List[JobItem] = []
        self.queue_processed.clear()
        if self.cache_client is None:
            raise ValueError("Cache client is not set")
        results_queue_len = await self.cache_client.result_queue_len()
        if results_queue_len >= service_Config.maxsize_results_queue:
            logger.warning(
                "Results queue full (actual size: %d, max size: %d), waiting",
                results_queue_len,
                service_Config.maxsize_results_queue,
            )
            await asyncio.sleep(1)
            return None

        try:
            if self.farm_client is not None and not await self.farm_client.is_available():
                raise ConnectionError(f"Rendering client ({self.farm_client}) is not available")

            if self.farm_client is not None and self.farm_client.ds_renderer_config.pending_job_limit >= 0:
                pending_jobs = await self.farm_client.get_pending_jobs()
                while len(pending_jobs) > self.farm_client.ds_renderer_config.pending_job_limit:
                    logger.debug(
                        "Too many pending jobs: %d [allowed: %d]",
                        len(pending_jobs),
                        self.farm_client.ds_renderer_config.pending_job_limit,
                    )
                    await asyncio.sleep(10)
                    pending_jobs = await self.farm_client.get_pending_jobs()

            # NOTE: return only one Job.
            jobs: List[JobItem]
            async with self.get_next_items(count=1) as jobs:

                if len(jobs) == 0:
                    return []

                job = jobs[0]
                is_valid = await self.check_is_job_still_valid(job)
                if is_valid:
                    items = [job]
                else:
                    logger.info(
                        "Job skipped (already processed): %s hash=%s",
                        job.get("uri"),
                        job.get("hash_value"),
                    )

                if len(items) == 0:
                    return []

                logger.debug("%s", prepare_message(msg="Items: ", item_list=items))

                # process all the items in batch concurrently
                await self.process_batch(  # it processes only one item
                    items,
                    storage_client=storage_client,
                )

                return items
        except Empty:
            self.queue_processed.set()
            await asyncio.sleep(1)
            return None

    async def task_processor(self, storage_client: StorageClient) -> None:
        """Process results of CPU tasks"""
        while not self.get_stop_service():
            try:
                t_start = datetime.now()
                items = await self.process_next_batch(storage_client=storage_client)
                if items is None:
                    # wait a bit if there is nothing to process
                    await asyncio.sleep(10)
                    continue

                batch_len = len(items)
                if batch_len > 0 and self.use_prom_metrics:
                    duration_seconds = (datetime.now() - t_start).total_seconds()

                    if self.use_prom_metrics:
                        if self.metric_processed_items is not None:
                            self.metric_processed_items.inc(batch_len)
                        if self.metric_item_processing_time is not None:
                            self.metric_item_processing_time.observe(duration_seconds / batch_len)
                        if self.metric_full_batch_processing_time is not None:
                            self.metric_full_batch_processing_time.observe(duration_seconds)
                    logger.info(
                        "Processing a batch of %d items completed in %.02fs",
                        batch_len,
                        duration_seconds,
                    )
            except CacheConnectionError:
                logger.warning("Cache client Connection Error")
            except RuntimeError as exc:
                logger.exception("Runtime Error (likely connection is broken: %s)", str(exc))
            except ConnectionError as exc:
                logger.warning("Connection Error: %s", str(exc))
                await asyncio.sleep(1)
            except Exception as exc:
                logger.exception("Unexpected error: %s", str(exc))
                raise Exception("Unexpected error: %s", str(exc)) from exc

    def run(self) -> None:

        logger.info("%s plugin worker started.", self._worker_config.plugin_name)
        # logger.info(self.config.to_string())
        try:
            logger.info(
                "Plugin configuration: %s",
                json.dumps(self._plugin.config.model_dump(), indent=2),
            )
        except TypeError:
            logger.warning("Plugin configuration class is not JSON serializable")
            logger.info("Plugin configuration: %s", str(self._plugin.config))

        async def task() -> None:
            if self.cache_client is None:
                raise ValueError("Cache client is not set")

            # wait for cache client to be initialized
            await self.cache_client.ready.wait()

            async with self._storage_client.connection_context() as storage_client:
                await asyncio.gather(
                    *[
                        self.task_processor(storage_client=storage_client)
                        for _ in range(self._n_parallel_queue_processors)
                    ]
                )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(task())


def main(
    plugin_name: Optional[str] = None,
    job_item_type: Optional[List[JobItemType]] = None,
    group_name: Optional[str] = None,
) -> None:
    setup_logging()

    resource = get_aggregated_resources(
        [OTELResourceDetector()],
        Resource(
            attributes={
                "service.name": "deepsearch-worker",
                "plugin.name": plugin_name if plugin_name is not None else "None",
                "group.name": group_name if group_name is not None else "None",
                "job.item.type": job_item_type if job_item_type is not None else "None",
                "host.name": os.uname()[1],
            }
        ),
    )
    provider = TracerProvider(resource=resource)
    if os.getenv("OTEL_TRACES_EXPORTER", "false").lower() == "true":
        logger.info("Enabling OpenTelemetry traces exporter")
        processor = BatchSpanProcessor(OTLPSpanExporter())
        provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    # setup optional arguments
    kwargs = {}
    if plugin_name is not None:
        kwargs["plugin_name"] = plugin_name
    if job_item_type is not None:
        kwargs["job_item_type"] = job_item_type

    cache_config: Optional[RedisCacheConfig] = None
    if group_name is not None:
        cache_config = RedisCacheConfig(cache_consumer_group=group_name)

    worker = MonitorWorker(worker_config=DeepSearchMonitorWorkerConfig(**kwargs), cache_config=cache_config)

    worker.run()


if __name__ == "__main__":
    Fire(main)
