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
import signal
import socket
import time
from ast import literal_eval
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Union

from cache.src import (
    GenericPluginStatus,
    JobItem,
    JobItemType,
    PluginItemStatus,
    PluginItemStatusHistory,
)
from cache.src.client import CacheClientRedis
from cache.src.client.config import RedisCacheConfig
from cache.src.client.redis_metrics import RedisCacheMetrics

# local/proprietary modules
from deepsearch_crawler.config import ConsumerConfig
from deepsearch_crawler.consumer import DeepSearchConsumer
from monitor.src.logging_utils import setup_logging
from plugins import BasePlugin, Plugins
from storage.src.client import (
    BackendUnavailable,
    NGSearchStorageClient,
    NGSearchStorageHelper,
)
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.datetime_utils import date_from_timestamp
from search_utils.hashing_utils import get_hash
from search_utils.log_utils import print_wrapper
from search_utils.misc_utils import get_percentage
from search_utils.prometheus_utils import (
    GaugeMetric,
    GenericPublisher,
    ProcessMetricsCollector,
)
from search_utils.storage_client import (
    FileTypeMapping,
    PathType,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.storage_client.data import EventMapping, SubscriptionSource
from search_utils.storage_client.utils import is_exclude_uri
from search_utils.streams.redis import RedisStreamConfig

from . import logger
from .config import DeepSearchMonitorConfig
from .data import MonitorPromMetrics, MonitorServiceTasks

# third party modules


SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


signal.signal(signal.SIGINT, signal.SIG_DFL)


class DeepSearchMonitorBase:
    def __init__(
        self,
        monitor_config: Optional[DeepSearchMonitorConfig] = None,
        cache_config: Optional[RedisCacheConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
    ) -> None:
        if monitor_config is None:
            self._monitor_config = DeepSearchMonitorConfig()
        else:
            self._monitor_config = monitor_config

        self.storage_initialized = asyncio.Event()
        self._search_backend_config = search_backend_config

        if storage_config is None:
            self._storage_config = StorageConfig()
        else:
            self._storage_config = storage_config
        self._storage_client_config = storage_client_config

        self._cache_client: CacheClientRedis = CacheClientRedis(config=cache_config)  # type: ignore[no-any-unimported] # missing stubs
        self._plugins: list[BasePlugin] = Plugins.get_active_plugins(
            config_path=self._monitor_config.plugins_config_path
        )
        self._ngsearch_storage_client: Optional[NGSearchStorageHelper] = None  # type: ignore[no-any-unimported] # missing stubs

    async def _terminate(self) -> None:
        await self.cache_client._terminate()

    @property
    def monitor_config(self) -> DeepSearchMonitorConfig:
        return self._monitor_config

    async def initialize_storage_client(self) -> None:
        self.storage_initialized.clear()
        initialized = False
        while not initialized:
            try:
                self._ngsearch_storage_client = await NGSearchStorageClient.get_service(
                    storage_config=self._storage_config,
                    storage_client_config=self._storage_client_config,
                    search_backend_config=self._search_backend_config,
                )
                initialized = True
            except ConnectionError as e:
                logger.warning(str(e))
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(e)
                await asyncio.sleep(5)

        # set mutex value so that the other processes can go forward
        self.storage_initialized.set()

    @property
    def plugins(self) -> List[BasePlugin]:  # type: ignore[no-any-unimported,misc] # missing stubs
        return self._plugins

    @property
    def cache_client(self) -> CacheClientRedis:  # type: ignore[no-any-unimported,misc] # missing stubs
        return self._cache_client

    async def clear_cached_item(self, omni_item: PathType, p_name: str) -> None:  # type: ignore[no-any-unimported] # missing stubs
        # # add item to the set of deleted items that will be processed by the service
        # remove item from cache
        await self.cache_client.plugin_del(f"{p_name}_path_to_hash", [omni_item.uri])


class DeepSearchMonitorService(DeepSearchConsumer, DeepSearchMonitorBase):  # type: ignore[no-any-unimported,misc] # missing stubs
    def __init__(  # type: ignore[no-any-unimported] # missing stubs
        self,
        stream_config: Optional[RedisStreamConfig] = None,
        consumer_config: Optional[ConsumerConfig] = None,
        monitor_config: Optional[DeepSearchMonitorConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        cache_config: Optional[RedisCacheConfig] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
    ) -> None:
        DeepSearchMonitorBase.__init__(
            self,
            monitor_config=monitor_config,
            cache_config=cache_config,
            storage_config=storage_config,
            storage_client_config=storage_client_config,
            search_backend_config=search_backend_config,
        )

        # initialize superclass
        if consumer_config is None:
            consumer_config = ConsumerConfig(
                stream_group_name=self._monitor_config.stream_group_name,
                stream_consumer_name=socket.gethostname(),
            )

        DeepSearchConsumer.__init__(self, stream_config=stream_config, consumer_config=consumer_config)

        # storage backend client
        self._storage_client = get_client(
            client_type=self._storage_config.storage_backend_type,
            config=self._storage_client_config,
        )
        logger.debug("Storage client config:\n%s", self._storage_client.config)

        # some additional args
        self._queues_cleaned_event = asyncio.Event()

        self._prom_metrics_dict: Optional[MonitorPromMetrics] = None
        # create prometheus metrics publisher
        if self._monitor_config.use_prom_metrics:
            self._process_metrics_collector = ProcessMetricsCollector(prom_labels=self.prom_labels)
            self.prom_metrics = GenericPublisher(port=self._monitor_config.prom_metrics_port, labels=self.prom_labels)

            self._prom_metrics_dict = MonitorPromMetrics(
                redis_cache_metrics=RedisCacheMetrics(
                    self.cache_client,
                    common_labels=self.prom_labels,
                    plugins=self._plugins,
                    refresh_interval_seconds=self._monitor_config.metrics_refresh_interval_seconds,
                ),
                progress_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_queue_progress")),
                queued_length_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_queued")),
                processed_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_processed")),
            )

            self._prom_metrics_dict["progress_metric"].set(100)
            self._prom_metrics_dict["queued_length_metric"].set(0)
            self._prom_metrics_dict["processed_metric"].set(0)
            # start prometheus server
            self.prom_metrics.start_server()

        # prepare concurrent tasks
        self._tasks: MonitorServiceTasks = self.prepare_tasks()

    @property
    def prom_prefix(self) -> str:
        return f"omnideepsearch_{self._monitor_config.metric_name}"

    @property
    def prom_labels(self) -> Dict[str, str]:
        return dict(
            omni_service=self._monitor_config.omni_service,
            omni_instance=self._monitor_config.omni_instance,
            omni_host="legacy (not used)",
            stream_consumer_name=self._config.stream_consumer_name,
            stream_consumer_group=self._config.stream_group_name,
            omni_alert="0",
        )

    @asynccontextmanager
    async def client_context(self) -> StorageClient:  # type: ignore[no-any-unimported,misc] # missing stubs
        async with self._storage_client.connection_context() as client:
            yield client

    @property
    def exclude_uri_substrings(self) -> List[str]:
        patterns: List[str] = literal_eval(self._monitor_config.exclude_uri_substrings)
        return patterns

    async def await_readiness(self) -> None:
        """Wait for both stream consumer and cache client to be ready"""
        # make sure DeepSearch consumer is connected
        await self.ready.wait()
        # make sure all redis cache streams are initialized
        await self.cache_client.ready.wait()

    async def process_queue(self) -> None:
        # run main loop
        bg = time.time()
        await self.await_readiness()
        # wait for queues to be cleaned
        if self.monitor_config.clean_queues:
            await self.queues_cleaned_event.wait()
        client: StorageClient  # type: ignore[no-any-unimported] # missing stubs
        async with self.client_context() as client:
            while True:
                if self.monitor_config.processing_batch_size == 1:
                    await self.process_single_asset(client=client)
                else:
                    responses: List[Optional[Exception]] = await asyncio.gather(
                        *[
                            self.process_single_asset(client=client)
                            for _ in range(self.monitor_config.processing_batch_size)
                        ],
                        return_exceptions=True,
                    )

                    for response in responses:
                        if isinstance(response, Exception):
                            # propagate exception further
                            raise response from response

                # update prometheus metrics
                stats = await self.statistics()
                progress = get_percentage(stats["processed"], stats["read"])
                if self._monitor_config.use_prom_metrics:
                    if self._prom_metrics_dict is None:
                        raise ValueError("Metrics dict is not initialized")
                    self._prom_metrics_dict["queued_length_metric"].set(stats["read"] - stats["processed"])
                    self._prom_metrics_dict["progress_metric"].set(progress)
                    self._prom_metrics_dict["processed_metric"].set(stats["processed"])

                # dump cache to local system
                if time.time() - bg > 60:
                    logger.info("read: %s", stats["read"])
                    bg = time.time()

    async def process_single_asset(self, client: StorageClient) -> None:
        try:
            path_list: Optional[List[dict]]  # type: ignore[type-arg] # here the dictionary can be arbitrary - later on the code would try to convert it to PathType
            async with self.consume(count=1) as path_list:
                if path_list is None:
                    await asyncio.sleep(self.monitor_config.idle_timeout)
                    return

                item: PathType  # type: ignore[no-any-unimported] # missing stubs
                for item in [PathType.model_construct(**dict_item) for dict_item in path_list]:

                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug("getting item: %s", str(item))

                    if item.uri is None:
                        logger.debug("Item uri is None: %s", item)
                        return
                    if is_exclude_uri(item.uri, self.exclude_uri_substrings):
                        logger.debug("Item uri is excluded: %s", item.uri)
                        return
                    if not client.is_supported_uri(item.uri):
                        logger.debug("Item uri is not supported: %s", item.uri)
                        continue
                    if client.get_file_type(item) != FileTypeMapping.asset:
                        logger.debug("Item is not an asset: %s", item.uri)
                        continue

                    if self._monitor_config.verify_asset_existence:
                        exists, _ = await client.check_if_exists(uri=item.uri)
                        if not exists:
                            logger.debug("Asset: %s is not present on the server", item.uri)
                            continue

                    # process item
                    with print_wrapper(
                        f"processing event: {item.uri}",
                        print_after=False,
                        logger=logger.debug,
                    ):
                        await self.process_path(item, client)
        except Exception as e:
            logger.exception("Error processing item: %s", e)
            raise e

    async def process_path(self, r: PathType, client: StorageClient) -> None:  # type: ignore[no-any-unimported] # missing stubs

        # remove item from the processing queue and cache DB
        if client.get_event_type(r) == EventMapping.delete:
            # log that an items was deleted
            logger.debug("detected removed uri: %s", r.uri)
            # remove plugins metadata for this path
            await asyncio.gather(*[self.process_deleted_item(r, p) for p in self.plugins])
            # publish prometheus metrics
            self.prom_metrics.get_metrics()

        # changed ACL
        # TODO: Handle ACL 'properly' if they should be anyhow handled in our case
        elif client.get_event_type(r) == EventMapping.acl_change:
            logger.info("detected acl change: %s", r.uri)

        # created or updated path
        else:
            # make sure all the required fields are correctly set
            if isinstance(r, PathType):
                path_item = r
            else:
                path_item = PathType.model_construct(**r)
            # cache hash values
            hash_value = path_item.get_hash()
            file_type = os.path.splitext(path_item.uri)[1][1:]

            # Process all the plugins concurrently
            await asyncio.gather(
                *[
                    self.process_plugin(
                        p,
                        file_type=file_type,
                        path_item=path_item,
                        hash_value=p.asset_state_hash(hash_value),
                        hashed_hash_value=get_hash(p.asset_state_hash(hash_value)),
                        client=client,
                    )
                    for p in self.plugins
                ]
            )

    async def check_plugin_cache(self, r: PathType, plugin: BasePlugin, hash_value: Union[str, bytes]) -> bool:  # type: ignore[no-any-unimported] # missing stubs
        try:
            cached_hash_value = await self.cache_client.plugin_get_raw(
                dest=f"{plugin.plugin_name}_path_to_hash", key=r.uri
            )
            if cached_hash_value != hash_value:
                plugin.logger.debug("%s -- %s vs %s", r.uri, cached_hash_value, hash_value)
        except KeyError:
            cached_hash_value = None
        except Exception as e:
            logger.exception("cache plugin check exception: %s", str(e))
            cached_hash_value = None

        return bool(cached_hash_value == hash_value)

    async def process_plugin(  # type: ignore[no-any-unimported] # missing stubs
        self,
        p: BasePlugin,
        file_type: str,
        path_item: PathType,
        hash_value: str,
        hashed_hash_value: str,
        client: StorageClient,
    ) -> None:
        # if plugin cannot process this path - directly exit
        if not p.should_process(file_type):
            return

        # check if exactly this item with the exact same hash was already processed.
        if await self.check_plugin_cache(r=path_item, plugin=p, hash_value=hashed_hash_value):
            return

        # skip_same_hash
        if self._monitor_config.skip_same_hash:
            if await self.proc_hash_plugin(
                omni_item=path_item,
                plugin=p,
                hash_value=hashed_hash_value,
                client=client,
            ):
                logger.debug("Same hash already processed %s", path_item.uri)
                return

        if path_item.source == SubscriptionSource.subscription:
            job_type = JobItemType.priority
        else:
            job_type = JobItemType.normal

        await self.cache_client.enqueue_plugin_job(
            plugin_name=p.plugin_name,
            content=JobItem(
                uri=path_item.uri,
                hash_value=hash_value,
                plugin_name=p.plugin_name,
                job_type=job_type,
            ),
        )

        # update plugin status
        await self.cache_client.add_asset_status(
            plugin_name=p.plugin_name,
            uri=path_item.uri,
            hash_value=hash_value,
            status=GenericPluginStatus.queued,
        )

    async def proc_hash_plugin(  # type: ignore[no-any-unimported] # missing stubs
        self,
        omni_item: PathType,
        plugin: BasePlugin,
        hash_value: str,
        client: StorageClient,
    ) -> bool:
        """Check if an item is present in plugin cache

        Args:
            omni_item: omniverse item
            plugin: plugin
            hash_value (str): hash of the omniverse item

        Returns:
            bool: ``True`` if the item has already been processed, ``False`` otherwise.
        """

        # check correctness of data input
        assert hash_value is not None, "passed hash argument is None"
        # get plugin name
        p_name = plugin.plugin_name

        # check that the same item with the same hash is already processed
        if await self.check_plugin_cache(omni_item, plugin, hash_value):
            try:
                asset_status: PluginItemStatusHistory = await self.cache_client.get_asset_status(
                    p_name, uri=omni_item.uri
                )
                latest_status: PluginItemStatus = asset_status.item_status_history[0]
                if latest_status.status != GenericPluginStatus.ok:
                    logger.warning(
                        "Failed processing asset: '%s' during previous runs. Latest status: %s (processing date: %s).",
                        omni_item.uri,
                        latest_status.status,
                        date_from_timestamp(latest_status.processing_timestamp),
                    )
            except KeyError:
                pass
            return True

        # check if configuration flag to skip same hash is set
        if not self._monitor_config.skip_same_hash:
            return False

        # check if copy hash is required for the plugin
        if hasattr(plugin, "same_hash_copy") and not plugin.same_hash_copy:
            return False

        # get the path with the expected hash
        try:
            file = await self.cache_client.plugin_get(dest=f"{p_name}_hash_to_file", key=hash_value)
        except KeyError:
            return False

        # check if the path is still present in path_to_hash cache and if hash_to_file is up to date
        try:
            cached_hash = await self.cache_client.plugin_get_raw(dest=f"{p_name}_path_to_hash", key=file)
            if cached_hash != hash_value:
                await self.cache_client.plugin_del(dest=f"{p_name}_hash_to_file", keys=[hash_value])
                return False
        except KeyError:
            await self.cache_client.plugin_del(dest=f"{p_name}_hash_to_file", keys=[hash_value])
            return False

        # copy metadata for the plugin
        if hasattr(plugin, "copy_metadata"):
            # get the first item that was is not deleted
            try:
                await plugin.copy_metadata(
                    client=client,
                    source_path=file,
                    target_path=omni_item.uri,
                    storage_client=self._ngsearch_storage_client,
                )
                await self.update_item_cache(
                    p_name,
                    omni_item.uri,
                    get_hash(plugin.asset_state_hash(omni_item.get_hash())),
                )
            except BackendUnavailable:
                logger.warning("Backend not available")
                return False
            except KeyError:
                return False
            except Exception as e:
                logger.exception("Metadata copy exception: %s", str(e))
                return False

        return True

    async def update_item_cache(self, plugin_name: str, uri: str, hash_value: str) -> None:
        await self.cache_client.plugin_update_raw(
            dest=f"{plugin_name}_path_to_hash",
            content={uri: hash_value},
        )
        await self.cache_client.plugin_update(
            dest=f"{plugin_name}_hash_to_file",
            content={hash_value: uri},
            ttl_seconds=self._monitor_config.hash_to_file_cache_ttl_seconds,
        )

    async def process_deleted_item(self, omni_item: PathType, plugin: BasePlugin) -> None:  # type: ignore[no-any-unimported] # missing stubs
        # get plugin name
        p_name: str = plugin.plugin_name
        # get file extension
        ext = os.path.splitext(omni_item.uri)[1][1:]
        # if plugin cannot process this path - directly exit
        if not plugin.should_process(file_type=ext):
            return

        if hasattr(plugin, "delete_metadata"):
            try:
                await plugin.delete_metadata(path=omni_item.uri, storage_client=self._ngsearch_storage_client)
            except KeyError:
                pass

        # clear cached item
        await self.clear_cached_item(omni_item=omni_item, p_name=p_name)

    @property
    def queues_cleaned_event(self) -> asyncio.Event:
        return self._queues_cleaned_event

    async def cache_queues_cleanup(self) -> None:
        logger.info("Cleaning queues...")
        for plugin_name in Plugins.get_plugin_names():
            await self.cache_client.clean_plugin_queue(plugin_name)
        self._queues_cleaned_event.set()

    def prepare_tasks(self) -> MonitorServiceTasks:
        tasks = MonitorServiceTasks(
            storage_connection_init=self.initialize_storage_client(),
            process_queue=self.process_queue(),
            collect_system_metrics=None,
            collect_cache_metrics=None,
            initial_queues_cleanup=None,
        )
        # initialize metrics task
        if self._monitor_config.use_prom_metrics:
            if self._prom_metrics_dict is None:
                raise ValueError("metrics dictionary is not initialized")

            if self._prom_metrics_dict["redis_cache_metrics"] is None:
                raise ValueError("redis cache metrics are not initialized")

            tasks["collect_system_metrics"] = self._process_metrics_collector.collect_metrics()
            tasks["collect_cache_metrics"] = self._prom_metrics_dict["redis_cache_metrics"].collect_cache_metrics()

        if self._monitor_config.clean_queues:
            tasks["initial_queues_cleanup"] = self.cache_queues_cleanup()

        return tasks

    @property
    def tasks(self) -> MonitorServiceTasks:
        return self._tasks

    async def run(self) -> None:
        # wait for cache client to be initialized
        await self.cache_client.ready.wait()
        # run main task
        await asyncio.gather(*[task for task in self.tasks.values() if task is not None])  # type: ignore[call-overload] # call verified to be correct


def main() -> None:
    setup_logging()
    service = DeepSearchMonitorService()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(service.run())


if __name__ == "__main__":
    main()
