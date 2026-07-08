#!/usr/bin/env python3.6
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
import logging
import signal
import socket
import time
from abc import ABC, abstractmethod
from ast import literal_eval
from contextlib import asynccontextmanager
from time import sleep
from typing import Any, Dict, List, MutableMapping, Optional, TypeVar, Union

from deepsearch_crawler.config import ConsumerConfig
from deepsearch_crawler.consumer import DeepSearchConsumer
from storage.src.client import (
    ExistsStatus,
    IncorrectItemKey,
    NGSearchStorageClient,
    NGSearchStorageHelper,
    StorageClientInput,
)
from storage.src.models import Status
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.cache_utils.redis import AsyncRawCacheDictRedis
from search_utils.hashing_utils import get_hash
from search_utils.log_utils import setup_logging_from_yaml as setup_logging
from search_utils.misc_utils import get_percentage, get_percentage_string
from search_utils.prometheus_utils import (
    GaugeMetric,
    GenericPublisher,
    ProcessMetricsCollector,
)
from search_utils.storage_client import (
    PathType,
    RemoteFileUri,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.storage_client.data import EventMapping
from search_utils.storage_client.utils import is_exclude_uri
from search_utils.streams.redis import RedisStreamConfig

from .config import DeepSearchCrawlerConfig
from .data import ActualizationStats, CrawlerPromMetrics, CrawlerServiceTasks

setup_logging()


logger = logging.getLogger(__name__)

signal.signal(signal.SIGINT, signal.SIG_DFL)

_VT = TypeVar("_VT")  # value type


class CrawlerService(DeepSearchConsumer, ABC):
    def __init__(
        self,
        stream_config: Optional[RedisStreamConfig] = None,
        consumer_config: Optional[ConsumerConfig] = None,
        crawler_config: Optional[DeepSearchCrawlerConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
        meta_data_cache: Optional[MutableMapping[str, _VT]] = None,
    ) -> None:
        # set crawler config
        self._crawler_config: DeepSearchCrawlerConfig = self.set_crawler_config(crawler_config)

        # initialize superclass
        if consumer_config is None:
            consumer_config = ConsumerConfig(
                stream_group_name=self._crawler_config.stream_group_name,
                stream_consumer_name=socket.gethostname(),
            )

        super().__init__(stream_config=stream_config, consumer_config=consumer_config)

        if storage_config is None:
            self._storage_config = StorageConfig()
        else:
            self._storage_config = storage_config

        self._storage_client_config = storage_client_config
        self._search_backend_config = search_backend_config

        # initialize fast cache
        if meta_data_cache is None:
            self.meta_data_cache = AsyncRawCacheDictRedis(
                self._crawler_config.redis_url,
                database=self._crawler_config.metadata_redis_dict_database,
            )
        else:
            self.meta_data_cache = meta_data_cache

        while not self.meta_data_cache.is_ready():
            sleep(1)

        # TODO: figure out why this is needed. For some reason the background task to check the
        # stream is failing with an error
        self._stream_is_connected.set()

        # storage backend client
        self._storage_client = get_client(
            client_type=self._storage_config.storage_backend_type,
            config=storage_client_config,
        )
        # ngsearch storage client
        self._ngsearch_storage_client: Optional[NGSearchStorageHelper] = None

        # set-up trigger to know that ES cache is initialized
        self.storage_initialized = asyncio.Event()

        # some additional args
        self.first_run = True

        self._prom_metrics_dict: Optional[CrawlerPromMetrics] = None
        # create prometheus metrics publisher
        if self._crawler_config.use_prom_metrics:
            self._process_metrics_collector = ProcessMetricsCollector(prom_labels=self.prom_labels)
            self.prom_metrics = GenericPublisher(port=self._crawler_config.prom_metrics_port, labels=self.prom_labels)

            # prepare some metrics to measure service progress
            self._prom_metrics_dict = CrawlerPromMetrics(
                progress_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_queue_progress")),
                queued_length_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_queued")),
                processed_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_processed")),
                cached_length_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_cached")),
                backlog_length_metric=self.prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_backlog")),
            )
            # set to 100 in the beginning
            self._prom_metrics_dict["progress_metric"].set(100)
            self._prom_metrics_dict["queued_length_metric"].set(0)
            self._prom_metrics_dict["processed_metric"].set(0)
            self._prom_metrics_dict["backlog_length_metric"].set(0)
            self._lc = len(self.meta_data_cache)
            self._prom_metrics_dict["cached_length_metric"].set(self._lc)
            # start prometheus server
            self.prom_metrics.start_server()

        # prepare concurrent tasks
        self._tasks: CrawlerServiceTasks = self.prepare_tasks()

    @property
    def prom_prefix(self) -> str:
        return f"omningsearch_{self._crawler_config.metric_name}"

    @abstractmethod
    def set_crawler_config(self, crawler_config: DeepSearchCrawlerConfig) -> DeepSearchCrawlerConfig: ...

    @property
    def prom_labels(self) -> Dict[str, Union[str, int]]:
        return dict(
            omni_service=self._crawler_config.omni_service,
            omni_instance=self._crawler_config.omni_instance,
            omni_host="legacy (not used)",
            stream_consumer_name=self._config.stream_consumer_name,
            stream_consumer_group=self._config.stream_group_name,
            omni_alert=0,
        )

    @staticmethod
    @abstractmethod
    async def prepare_meta_dict(client: StorageClient, r: PathType) -> Optional[Dict[str, Any]]: ...

    @asynccontextmanager
    async def client_context(self) -> StorageClient:
        yield self._storage_client

    @property
    def exclude_uri_substrings(self) -> List[str]:
        return literal_eval(self._crawler_config.exclude_uri_substrings)

    def get_backend_name_from_uri(self, uri: RemoteFileUri) -> Optional[str]:
        return None

    async def _process_queue_item(self, client: StorageClient) -> None:
        path_list: Optional[List[dict]]
        async with self.consume(count=1) as path_list:
            if path_list is None:
                await asyncio.sleep(self._crawler_config.idle_timeout)
                return

            item: PathType
            for item in [PathType.model_construct(**dict_item) for dict_item in path_list]:

                logger.debug("getting item: %s", str(item))

                if item.uri is None:
                    continue
                if is_exclude_uri(item.uri, self.exclude_uri_substrings):
                    continue
                if not client.is_supported_uri(item.uri):
                    continue

                # wait till es cache is initialized
                await self.storage_initialized.wait()
                if self._ngsearch_storage_client is None:
                    raise ValueError("NGSearch Storage client is not set")
                # process item
                if client.get_event_type(item) == EventMapping.delete:
                    # log that an items was deleted
                    logger.debug("detected removed uri: %s", item.uri)
                    # remove plugins metadata for this path
                    try:
                        response = await self._ngsearch_storage_client.remove_item(
                            StorageClientInput(key=item.uri),
                            backend_name=self.get_backend_name_from_uri(item.uri),
                        )
                        await self.meta_data_cache.adelete(item.uri)
                        assert response.status == Status.ok
                    except KeyError:
                        logger.info("%s already removed", client.get_path_from_uri(item.uri))

                # created or updated path
                else:
                    # if needed - check if asset exists on the server
                    if self._crawler_config.existence_check_before_metadata_extraction:
                        try:
                            exists, _ = await client.check_if_exists(uri=item.uri)
                        except ConnectionError as exc_info:
                            logger.warning(
                                "Error connecting to the storage backend: %s, skipping.. will be re-triggered on initial server re-scan",
                                exc_info,
                            )
                            continue

                        if not exists:
                            continue

                    # prepare item metadata dictionary
                    meta_dict = await self.prepare_meta_dict(client, item)
                    if meta_dict is None:
                        continue
                    meta_hash = get_hash(meta_dict)

                    if await self.meta_data_cache.aget(item.uri) != meta_hash:
                        # is verify existence is set - run asset verification against the storage backend
                        if (
                            self._crawler_config.verify_asset_existence
                            and not self._crawler_config.existence_check_before_metadata_extraction
                        ):
                            try:
                                exists, _ = await client.check_if_exists(uri=item.uri)
                            except ConnectionError as exc_info:
                                logger.warning(
                                    "Error connecting to the storage backend: %s, skipping.. will be re-triggered on initial server re-scan",
                                    exc_info,
                                )
                                continue
                            if not exists:
                                continue
                        logger.debug("updating item: %s", item.uri)
                        # add to update list
                        response = await self._ngsearch_storage_client.update_meta(
                            StorageClientInput(key=item.uri, meta=meta_dict),
                            backend_name=self.get_backend_name_from_uri(uri=item.uri),
                        )
                        assert response.status == Status.ok
                        logger.debug("update completed for item: %s", item.uri)
                        await self.meta_data_cache.aset(item.uri, meta_hash)

    async def process_queue(self) -> None:
        # run main loop
        last_prom_update = time.time()
        last_stats_log = time.time()
        await self.ready.wait()
        # NOTE: here nested loop is required, because storage clients can
        #       potentially be recreated
        while True:
            client: StorageClient
            async with self.client_context() as client:
                while True:
                    responses: List[Optional[Exception]] = await asyncio.gather(
                        *[
                            self._process_queue_item(client=client)
                            for _ in range(self._crawler_config.processing_batch_size)
                        ],
                        return_exceptions=True,
                    )

                    for response in responses:
                        if isinstance(response, IncorrectItemKey):
                            logger.warning(response)
                        elif isinstance(response, Exception):
                            # propagate exception further
                            raise response from response

                    # Computing statistics (and the cache size) costs extra
                    # Redis round trips, so only do it when a consumer is
                    # actually due: when the Prometheus gauges need refreshing,
                    # or when stats logging is enabled (INFO) and its log
                    # interval has elapsed. This keeps the per-item hot path
                    # free of bookkeeping round trips.
                    now = time.time()
                    prom_update_due = self._crawler_config.use_prom_metrics and (
                        now - last_prom_update >= self._crawler_config.prom_metrics_update_interval_seconds
                    )
                    stats_log_due = logger.isEnabledFor(logging.INFO) and (
                        now - last_stats_log >= self._crawler_config.stats_log_interval_seconds
                    )

                    if prom_update_due or stats_log_due:
                        stats = await self.statistics()
                        progress = get_percentage(stats["processed"], stats["read"])
                        self._lc = await self.meta_data_cache.alen()

                        if prom_update_due:
                            self._prom_metrics_dict["queued_length_metric"].set(stats["read"] - stats["processed"])
                            self._prom_metrics_dict["progress_metric"].set(progress)
                            self._prom_metrics_dict["processed_metric"].set(stats["processed"])
                            self._prom_metrics_dict["cached_length_metric"].set(self._lc)
                            last_prom_update = now

                        if stats_log_due:
                            logger.info(
                                "read: %s, cached: %s [%.2f %% done]",
                                stats["read"],
                                self._lc,
                                progress,
                            )
                            last_stats_log = now

    async def initialize_storage_client(self) -> None:
        self.storage_initialized.clear()
        initialized = False
        while not initialized:
            try:
                logger.info("Connecting to NGSearch Storage service...")
                self._ngsearch_storage_client = await NGSearchStorageClient.get_service(
                    search_backend_config=self._search_backend_config,
                    storage_config=self._storage_config,
                    storage_client_config=self._storage_client_config,
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

    def prepare_tasks(self) -> CrawlerServiceTasks:
        tasks = CrawlerServiceTasks(
            storage_connection_init=self.initialize_storage_client(),
            process_queue=self.process_queue(),
            collect_system_metrics=None,
        )
        # initialize metrics task
        if self._crawler_config.use_prom_metrics:
            tasks["collect_system_metrics"] = self._process_metrics_collector.collect_metrics()

        return tasks

    @property
    def tasks(self) -> CrawlerServiceTasks:
        return self._tasks

    async def run(self) -> None:
        # run main task
        await asyncio.gather(*[task for task in self.tasks.values() if task is not None])


class CrawlerServiceCron(ABC):
    def __init__(
        self,
        crawler_config: Optional[DeepSearchCrawlerConfig] = None,
        meta_data_cache: Optional[MutableMapping[str, _VT]] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
    ) -> None:

        self._crawler_config: DeepSearchCrawlerConfig = self.set_crawler_config(crawler_config)
        self._search_backend_config = search_backend_config

        # initialize fast cache
        if meta_data_cache is None:
            self.meta_data_cache = AsyncRawCacheDictRedis(
                self._crawler_config.redis_url,
                database=self._crawler_config.metadata_redis_dict_database,
            )
        else:
            self.meta_data_cache = meta_data_cache

        while not self.meta_data_cache.is_ready():
            sleep(1)

        self._storage_config = storage_config if storage_config is not None else StorageConfig()
        self._storage_client_config = storage_client_config

        # ngsearch storage client
        self._ngsearch_storage_client: Optional[NGSearchStorageHelper] = None

    async def check_existence(
        self, batch: List[RemoteFileUri], client: NGSearchStorageHelper
    ) -> Dict[RemoteFileUri, bool]:
        """For each URI in a batch - get the respective storage backend.
        Split the whole batch into a smaller chunks, each for the respective backend.
        For each backend - check the existence of respective chunks of URLs.

        Args:
            batch (List[RemoteFileUri]): Input list of URLs
            client (NGSearchStorageHelper): NGSearch storage client

        Returns:
            Dict[RemoteFileUri, bool]: URL to existence value mapping
        """
        try:
            response: ExistsStatus = await client.exists(keys=batch)
            return {uri: exists for uri, exists in zip(batch, response.exists)}
        except Exception as exc_info:
            logger.exception(exc_info)
            raise Exception from exc_info

    @abstractmethod
    def set_crawler_config(self, crawler_config: DeepSearchCrawlerConfig) -> DeepSearchCrawlerConfig: ...

    async def initialize_storage_client(self) -> None:
        initialized = False
        while not initialized:
            try:
                logger.info("Connecting to NGSearch Storage service...")
                self._ngsearch_storage_client = await NGSearchStorageClient.get_service(
                    search_backend_config=self._search_backend_config,
                    storage_config=self._storage_config,
                    storage_client_config=self._storage_client_config,
                )
                initialized = True
            except ConnectionError as e:
                logger.warning(str(e))
                await asyncio.sleep(5)
            except Exception as e:
                logger.exception(e)
                await asyncio.sleep(5)

    async def local_cache_actualization(
        self,
        log_timeout: float = 30,
        batch_size: int = 256,
    ):
        if self._ngsearch_storage_client is None:
            raise ValueError("NGSearch storage client connection is not initialized")
        # iterate through all local cache keys and verify that they are relevant
        bg = time.time()
        removed_counter = 0

        async with self._ngsearch_storage_client as client:
            batch: List[str] = []
            for it, k in enumerate(await self.meta_data_cache.akeys()):
                batch.append(k)
                if len(batch) > batch_size:
                    # get results from the storage service
                    uri_existence_mapping: Dict[RemoteFileUri, bool] = await self.check_existence(
                        batch=batch, client=client
                    )

                    for uri, exists in uri_existence_mapping.items():
                        logger.debug("existence check '%s': %s", uri, exists)
                        if not exists:
                            await self.meta_data_cache.adelete(uri)
                            removed_counter += 1
                    batch = []

                if time.time() - bg > log_timeout:
                    logger.info(
                        "removed: %s processed: %s",
                        get_percentage_string(removed_counter, it + 1),
                        get_percentage_string(it + 1, removed_counter + await self.meta_data_cache.alen()),
                    )
                    bg = time.time()

            uri_existence_mapping: Dict[RemoteFileUri, bool] = await self.check_existence(batch=batch, client=client)
            for uri, exists in uri_existence_mapping.items():
                logger.debug("existence check '%s': %s", uri, exists)
                if not exists:
                    await self.meta_data_cache.adelete(uri)
                    removed_counter += 1

        cache_size = await self.meta_data_cache.alen()
        logger.info(
            ActualizationStats(
                removed=get_percentage_string(removed_counter, removed_counter + cache_size),
                cache_size=cache_size,
            )
        )

    async def run(self):
        await self.initialize_storage_client()

        while True:
            await self.local_cache_actualization()
            await asyncio.sleep(self._crawler_config.metadata_redis_check_timeout)
