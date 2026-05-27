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
import os
from datetime import datetime
from itertools import chain
from queue import Empty
from typing import Any, Dict, List, Optional

from cache.src import ResultItem
from cache.src.client import CacheClientRedis
from cache.src.client.config import RedisCacheConfig
from monitor.src.logging_utils import setup_logging
from plugins import BasePlugin, Plugins
from plugins.models import PluginProcessingResult

# imports that are required for the Cache service to work from a different machine
from prometheus_client.metrics import Counter, Histogram

# local / proprietary modules
from storage.src.client import NGSearchStorageClient, NGSearchStorageHelper
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.misc_utils import check_dict_field
from search_utils.omni_microservice import AssetdbMS
from search_utils.prometheus_utils import GenericPublisher
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.storage_client.utils import task_wrapper

from .config import AssetDBConfig as service_Config

SENTRY_DSN = os.getenv("SENTRY_DSN")

logger = logging.getLogger(__name__)

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


class MonitorOmniWriter(AssetdbMS):
    def __init__(
        self,
        config: service_Config = service_Config,
        use_prom_metrics: Optional[bool] = False,
        prom_metrics_port: Optional[int] = None,
        omni_service: str = service_Config.omni_service,
        n_parallel_queue_processors: Optional[int] = None,
        cache_config: Optional[RedisCacheConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
        **kwargs,
    ) -> None:
        self._omni_service = omni_service
        if n_parallel_queue_processors is None:
            self._n_parallel_queue_processors = 1
        else:
            self._n_parallel_queue_processors = n_parallel_queue_processors

        if use_prom_metrics is None:
            use_prom_metrics = False
        if prom_metrics_port is None:
            prom_metrics_port = service_Config.prom_metrics_port

        if storage_config is None:
            self._storage_config = StorageConfig()
        else:
            self._storage_config = storage_config
        self._storage_client_config = storage_client_config
        self._search_backend_config = search_backend_config

        self.config: service_Config
        super().__init__(
            config=config,
            log_name="monitor omni writer",
            use_prom_metrics=use_prom_metrics,
            connection_names=[],
            redis_db_assetdbms=7,
            redis_url=service_Config.redis_url,
            **kwargs,
        )

        # save some parameters
        self.prom_metrics_port = prom_metrics_port
        self.queue_processed = asyncio.Event()
        self.batch_processed = asyncio.Event()

        # initialize clients
        # NOTE: Disable Redis tail auto trimming in workers. Since it is already done in the Monitor Crawler
        if cache_config is None:
            cache_config = RedisCacheConfig(cache_auto_trim_timeout=-1)
        else:
            cache_config.auto_trim_timeout = -1
        self.cache_client: CacheClientRedis = CacheClientRedis(
            config=cache_config, skip_worker_streams_initialization=True
        )

        # add process metrics
        self.metric_processed_items: Optional[Counter] = None
        self.metric_item_processing_time: Optional[Histogram] = None
        self.metric_full_batch_processing_time: Optional[Histogram] = None
        if use_prom_metrics:
            self.init_additional_prom_metrics()

    async def _terminate(self) -> None:
        """In practice this function is ont really used. It is convenient for tests to make sure all resources were deallocated"""
        await self.cache_client._terminate()

    def get_omni_service(self) -> str:
        return self._omni_service

    def init_additional_prom_metrics(self) -> None:
        # create prometheus metrics publisher
        self.prom_metrics = GenericPublisher(port=self.prom_metrics_port, labels=self.prom_labels)
        self.metric_processed_items = Counter(
            "omnideepsearch_writer_processed_items",
            "Count of items processed by the writer",
            labelnames=self.prom_labels.keys(),
        ).labels(*self.prom_labels.values())
        self.metric_full_batch_processing_time = Histogram(
            "omnideepsearch_writer_batch_processing_duration_seconds",
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
            labelnames=self.prom_labels.keys(),
        ).labels(*self.prom_labels.values())
        self.metric_item_processing_time = Histogram(
            "omnideepsearch_writer_item_processing_duration_seconds",
            "Duration of processing a single item (average from a batch)",
            labelnames=self.prom_labels.keys(),
        ).labels(*self.prom_labels.values())
        # start prometheus server
        self.prom_metrics.start_server()
        # init metrics processing task
        loop = asyncio.get_event_loop()
        loop.create_task(task_wrapper(self.process_metrics, name="Process metrics exporter"))

    async def push_tags_to_omniverse_task(
        self, ngsearch_storage_client: NGSearchStorageClient, timeout: int = 5
    ) -> None:
        # define some parameters
        # run main loop of the task
        while not self.get_stop_service():
            await self.push_tags_to_omniverse(ngsearch_storage_client=ngsearch_storage_client)

    async def get_storage_client(self) -> NGSearchStorageHelper:
        return await NGSearchStorageClient.get_service(
            storage_config=self._storage_config,
            storage_client_config=self._storage_client_config,
            search_backend_config=self._search_backend_config,
        )

    async def push_tags_to_omniverse(
        self, ngsearch_storage_client: NGSearchStorageClient, timeout: float = 0.5
    ) -> Optional[List[ResultItem]]:
        """Checks the results queue and pushes the elements from it to the omniverse.

        Args:
            c: omniverse connection
        """
        t_start = datetime.now()
        try:
            batch: List[ResultItem]
            async with self.cache_client.get_result() as batch:

                batch_len = len(batch)
                self.queue_processed.clear()

                logger.debug("Processing a batch of %d results...", batch_len)
                self.batch_processed.clear()

                logger.debug("%s", str([f"{b['uri']} ++ {b['hash_value']}; " for b in batch]))
                for item in batch:
                    await self.push_tags_task(item=item, storage_client=ngsearch_storage_client)

        except Empty:
            self.queue_processed.set()
            await asyncio.sleep(timeout)
            return None

        duration_seconds = (datetime.now() - t_start).total_seconds()

        # update some prometheus metrics
        if self.use_prom_metrics:
            if self.metric_processed_items is not None:
                self.metric_processed_items.inc(batch_len)
            if self.metric_item_processing_time is not None:
                self.metric_item_processing_time.observe(duration_seconds / batch_len)
            if self.metric_full_batch_processing_time is not None:
                self.metric_full_batch_processing_time.observe(duration_seconds)

        logger.info(
            "Processing a batch of %d results completed in %.04fs",
            batch_len,
            duration_seconds,
        )
        self.batch_processed.set()
        return batch

    async def update_plugin_metadata(
        self,
        plugin_name: str,
        es_content: Optional[Dict[str, Any]],
        item: ResultItem,
        storage_client: NGSearchStorageClient,
    ):
        plugin: BasePlugin = Plugins.get_plugin(plugin_name)

        if es_content is not None:
            await plugin.add_metadata(
                path=item["uri"],
                content=es_content,
                storage_client=storage_client,
            )
        elif hasattr(plugin, "delete_metadata"):
            try:
                await plugin.delete_metadata(
                    path=item["uri"],
                    storage_client=storage_client,
                )
            except KeyError:
                pass

    async def push_tags_task(self, item: ResultItem, storage_client: NGSearchStorageClient) -> None:
        plugin_output: Dict[str, Dict[str, PluginProcessingResult]] = item["prediction"]

        # NOTE: Update metadata for each plugin in parallel
        content = plugin_output.get("search_backend_content")
        if content is not None:
            await asyncio.gather(
                *[
                    self.update_plugin_metadata(
                        plugin_name=plugin_name,
                        es_content=es_content,
                        item=item,
                        storage_client=storage_client,
                    )
                    for plugin_name, es_content in content.items()
                ]
            )

        # update item cache
        try:
            logger.debug("updating: %s", str(item))
            await self.update_item_cache(item)
        except Exception as exc_info:
            logger.exception("item update failed: %s -- %s", str(item), str(exc_info))

        # some debugging info
        logger.info("asset: %s -- is processed", item["uri"])

    async def update_item_cache(self, item: ResultItem) -> None:
        """Update information about the item in the cache DB

        Args:
            item (dict): item dictionary
        """

        check_dict_field(item["asset_data"], ["plugins"])

        await asyncio.gather(
            *chain.from_iterable(
                [
                    [
                        self.cache_client.set_plugin_path_to_hash(
                            plugin_name=p_name,
                            uri=item["uri"],
                            hash_value=item["hash_value"],
                        ),
                        self.cache_client.set_plugin_hash_to_file(
                            plugin_name=p_name,
                            uri=item["uri"],
                            hash_value=item["hash_value"],
                            ttl_seconds=service_Config.hash_to_file_cache_ttl_seconds,
                        ),
                    ]
                    for p_name in item["asset_data"]["plugins"]
                ]
            )
        )

    def run(self) -> None:
        loop = asyncio.get_event_loop()

        async def task():
            ngsearch_storage_client = await self.get_storage_client()
            # wait for cache client to be initialized
            await self.cache_client.ready.wait()

            await asyncio.gather(
                *[
                    self.push_tags_to_omniverse_task(ngsearch_storage_client=ngsearch_storage_client)
                    for _ in range(self._n_parallel_queue_processors)
                ]
            )

        loop.run_until_complete(task())


def main(
    use_prom_metrics: Optional[bool] = service_Config.services.omni_writer.use_metrics,
    prom_metrics_port: Optional[int] = service_Config.services.omni_writer.metrics_port,
    omni_service: str = service_Config.services.omni_writer.omni_service,
    n_parallel_queue_processors: Optional[int] = service_Config.services.omni_writer.n_parallel_queue_processors,
):
    setup_logging()
    writer = MonitorOmniWriter(
        use_prom_metrics=use_prom_metrics,
        prom_metrics_port=prom_metrics_port,
        omni_service=omni_service,
        n_parallel_queue_processors=n_parallel_queue_processors,
    )
    writer.run()


if __name__ == "__main__":
    main()
