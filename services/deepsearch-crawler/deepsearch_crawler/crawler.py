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
from ast import literal_eval
from typing import Awaitable, Callable, Dict, List, Optional, Set, TypedDict

import yaml
from prometheus_client import Gauge
from redis.exceptions import ResponseError

from search_utils.misc_utils import load_yaml_file
from search_utils.prometheus_utils import (
    GaugeMetric,
    GenericPublisher,
    ProcessMetricsCollector,
)
from search_utils.storage_client import (
    AvailableStorageClients,
    FileTypeMapping,
    PathType,
    RemoteFileUri,
    StorageClient,
    TagResultField,
    get_client,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.streams import get_stream_worker
from search_utils.streams.redis import RedisStreamConfig, RedisStreamWorker

from .config import CrawlerConfig, ExtraCrawlerConfig
from .exceptions import SubscriptionTerminatedError
from .utils import exclude_items

logger = logging.getLogger(__name__)


class CrawlerPromMetrics(TypedDict):
    stream_length: Gauge
    group_read: Gauge
    group_processed: Gauge
    list_subscription: Gauge
    tag_subscription: Gauge
    mount_listing: Gauge


class CrawlerTasks(TypedDict):
    main_crawl: Optional[Awaitable[None]]
    mount_crawl: Optional[Awaitable[None]]
    tag_crawl: Optional[Awaitable[None]]
    stream_trim: Optional[Awaitable[None]]
    stream_preparation: Awaitable[None]
    collect_system_metrics: Optional[Awaitable[None]]
    collect_service_metrics: Optional[Awaitable[None]]


class DeepSearchCrawler:
    def __init__(  # type: ignore[no-any-unimported]  # missing stubs
        self,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        stream_config: Optional[RedisStreamConfig] = None,
        crawler_config: Optional[CrawlerConfig] = None,
    ) -> None:
        if storage_config is None:
            storage_config = StorageConfig()
        self._storage_config = storage_config

        if crawler_config is None:
            self._config = CrawlerConfig()
        else:
            self._config = crawler_config

        self._extra_config = None
        if self._config.extra_config_file is not None:
            self._extra_config = ExtraCrawlerConfig(**load_yaml_file(self._config.extra_config_file))

        if stream_config is None:
            self._stream_config = RedisStreamConfig(name=self._config.stream_name)
        else:
            self._stream_config = stream_config

        self._stream_groups: Optional[List[str]] = self.load_group_config()
        if self._stream_groups is not None and not isinstance(self._stream_groups, list):
            logger.warning("invalid stream group setup: %s", str(self._stream_groups))
            self._stream_groups = None

        # initialize storage client
        self._storage_client = get_client(
            client_type=self._storage_config.storage_backend_type,
            config=storage_client_config,
        )
        # initialize stream client
        self._stream_writer_client = get_stream_worker(self._config.stream_type, config=self._stream_config)
        # prepare stream
        self._stream_is_ready = asyncio.Event()
        # set of mount paths
        self._mount_set: Set[RemoteFileUri] = set([])  # type: ignore[no-any-unimported]  # missing stubs
        # tag subscription event
        self._tag_subscription_event: Optional[asyncio.Event] = None
        # prometheus metrics
        if self._config.use_prom_metrics:
            self._process_metrics_collector = ProcessMetricsCollector(prom_labels=self.prom_labels)
            self._prom_metrics = GenericPublisher(port=self._config.prom_metrics_port, labels=self.prom_labels)

            # prepare some metrics to measure service progress
            self._prom_metrics_dict = CrawlerPromMetrics(
                stream_length=self._prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_stream_length")),
                group_read=Gauge(
                    f"{self.prom_prefix}_group_read",
                    documentation=f"{self.prom_prefix}_group_read",
                    labelnames=list(self.prom_labels.keys()) + ["stream_group"],
                ),
                group_processed=Gauge(
                    f"{self.prom_prefix}_group_processed",
                    documentation=f"{self.prom_prefix}_group_processed",
                    labelnames=list(self.prom_labels.keys()) + ["stream_group"],
                ),
                list_subscription=self._prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_list_subscription")),
                tag_subscription=self._prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_tag_subscription")),
                mount_listing=self._prom_metrics.init_metric(GaugeMetric(f"{self.prom_prefix}_mount_listing")),
            )
            # set to 100 in the beginning
            self._prom_metrics_dict["stream_length"].set(0)
            self._prom_metrics_dict["list_subscription"].set(0)
            self._prom_metrics_dict["tag_subscription"].set(0)
            self._prom_metrics_dict["mount_listing"].set(0)
            # start prometheus server
            self._prom_metrics.start_server()

        # concurrent task list
        self._tasks: CrawlerTasks = self.prepare_tasks()

    async def _recreate_subscription_wrapper(self, subscription: Callable[[], Awaitable[None]]) -> None:
        while True:
            try:
                await subscription()
            except SubscriptionTerminatedError as exc:
                if self._config.recreate_subscription_on_error:
                    logger.warning("subscription recreated: %s", str(exc))
                else:
                    raise SubscriptionTerminatedError("subscription unexpectedly terminated") from exc
            finally:
                await asyncio.sleep(0.2)

    @property
    def stream_groups(self) -> List[str]:
        if self._stream_groups is None:
            return []
        return self._stream_groups

    @property
    def prom_labels(self) -> Dict[str, str]:
        return {
            "omni_service": self._config.omni_service,
            "omni_instance": self._config.omni_instance,
            "omni_host": "legacy (not used)",
            "omni_alert": "0",
        }

    @property
    def prom_prefix(self) -> str:
        return f"omnideepsearch_{self._config.metric_name}"

    @property
    def mount_set(self) -> Set[RemoteFileUri]:  # type: ignore[no-any-unimported,misc]  # missing stubs
        return self._mount_set

    def load_group_config(self) -> Optional[List[str]]:
        content: Optional[List[str]] = None
        if self._config.stream_group_str is not None:
            content = yaml.safe_load(self._config.stream_group_str)
        elif self._config.stream_group_file is not None:
            with open(self._config.stream_group_file, mode="r", encoding="utf-8") as stream_group_file:
                content = yaml.safe_load(stream_group_file)
        return content

    async def prepare_stream(self) -> None:
        if self._config.reset_on_startup and await self._stream_writer_client.stream_available():
            await self._stream_writer_client.reset_stream()

        if self._stream_groups is not None and len(self._stream_groups) > 0:
            for group in self._stream_groups:
                consumer_config = RedisStreamConfig.model_construct(**self._stream_config.model_dump())
                consumer_config.consumer_group = group
                stream_group_worker = get_stream_worker(self._config.stream_type, config=consumer_config)
                await stream_group_worker.connect_consumer()
        self._stream_is_ready.set()

    @property
    def ready(self) -> asyncio.Event:
        return self._stream_is_ready

    @property
    def config(self) -> CrawlerConfig:
        return self._config

    @property
    def stream_writer_client(self) -> RedisStreamWorker:  # type: ignore[no-any-unimported,misc]  # missing stubs
        return self._stream_writer_client

    async def mount_list(self) -> None:
        client: StorageClient  # type: ignore[no-any-unimported]  # missing stubs
        async with self._storage_client.connection_context() as client:
            item: PathType  # type: ignore[no-any-unimported]  # missing stubs
            async for item in client.list_items(
                path_list=list(self.mount_set),
                ignore_patterns=self.ignore_patterns,
                list_type=None,
            ):
                # check if items should be excluded
                if exclude_items(item=item, extra_config=self._extra_config):
                    continue
                # add item
                logger.info("Enqueuing mount item: %s", item.uri)
                await self._stream_writer_client.put(item=item.model_dump())
                # update metrics
                if self._config.use_prom_metrics:
                    self._prom_metrics_dict["mount_listing"].inc()

    async def crawl(self) -> None:
        # wait for stream to be ready
        logger.info("Waiting for queue stream to be ready...")
        await self.ready.wait()
        logger.info("Queue stream is ready")
        # run crawler
        client: StorageClient  # type: ignore[no-any-unimported]  # missing stubs
        async with self._storage_client.connection_context() as client:
            items: List[PathType]  # type: ignore[no-any-unimported]  # missing stubs
            logger.info("Starting main crawl for path: %s", self._config.path)
            async for items in client.list_items_and_subscribe(
                uri=self._config.path,
                ignore_patterns=self.ignore_patterns,
                batch_size=1,
                list_type=None,
            ):
                for item in items:
                    if client.get_file_type(item) == FileTypeMapping.mount:
                        self._mount_set.add(client.get_path_from_uri(item.uri))
                    # check if items should be excluded
                    if exclude_items(item=item, extra_config=self._extra_config):
                        continue
                    # add item
                    logger.info("Enqueuing item: %s", item.uri)
                    await self._stream_writer_client.put(item=item.model_dump())
                    # update metrics
                    if self._config.use_prom_metrics:
                        self._prom_metrics_dict["list_subscription"].inc()

        raise SubscriptionTerminatedError("main subscription terminated")

    async def crawl_mounts(self) -> None:
        # NOTE: mounts are only relevant for Nucleus storage backends

        if self._storage_config.storage_backend_type != AvailableStorageClients.nucleus:
            return

        await self.ready.wait()

        while True:
            # if mount set is empty - continue listening
            if len(self.mount_set) == 0:
                logger.debug("Empty mount set")
                await asyncio.sleep(self._config.mount_check_timeout)
                continue

            # if some mounts exist - list them
            await self.mount_list()
            # wait before starting the task
            await asyncio.sleep(self._config.mount_list_timeout)

    async def crawl_tags(self) -> None:
        if self._storage_config.storage_backend_type != AvailableStorageClients.nucleus:
            return

        await self.ready.wait()

        tag_result: Optional[TagResultField]  # type: ignore[no-any-unimported]  # missing stubs
        async with self._storage_client.connection_context_with_tagging() as client:
            async for tag_result in client.tag_subscription(
                uri=self._config.path, subscription_ready=self._tag_subscription_event
            ):
                if tag_result is None:
                    continue
                item_raw = await client.get_item(tag_result.uri)
                if item_raw is None:
                    continue
                item: PathType = PathType.model_construct(**item_raw)  # type: ignore[no-any-unimported] # missing stubs
                # check if items should be excluded
                if exclude_items(item=item, extra_config=self._extra_config):
                    continue
                logger.info("Enqueuing tag item: %s", item.uri)
                await self._stream_writer_client.put(item=item.model_dump())
                if self._config.use_prom_metrics:
                    self._prom_metrics_dict["tag_subscription"].inc()

        raise SubscriptionTerminatedError("tag subscription terminated")

    @property
    def ignore_patterns(self) -> List[str]:
        return [f".*{pattern}.*" for pattern in literal_eval(self._config.ignore_patterns)]

    @property
    def tasks(self) -> CrawlerTasks:
        return self._tasks

    async def terminate(self) -> None:
        # clean up the stream
        if await self._stream_writer_client.stream_available():
            await self._stream_writer_client.reset_stream()

    async def trim_tail_task(self) -> None:
        await self.ready.wait()
        while True:
            try:
                max_processed_id = await self._stream_writer_client.get_max_processed_id()
                logger.debug("trimming tail.. Max processed id: %s", max_processed_id)
                await self._stream_writer_client.trim_tail()
            except ResponseError as exc_info:
                logger.warning("Stream is not fully initialized: %s", str(exc_info))
            finally:
                await asyncio.sleep(self._config.trim_tail_timeout)

    async def stream_length(self) -> int:
        length: int = await self._stream_writer_client.stream_length()
        return length

    async def collect_service_metrics(self) -> None:
        await self.ready.wait()
        while True:
            if not await self._stream_writer_client.stream_available():
                await asyncio.sleep(self._config.metrics_collect_timeout)
                continue

            # get stream length
            self._prom_metrics_dict["stream_length"].set(await self.stream_length())
            # get total read metric
            total_read = await self.stream_writer_client.total_read()
            for group_name, read_amount in total_read.items():
                self._prom_metrics_dict["group_read"].labels(stream_group=group_name, **self.prom_labels).set(
                    read_amount
                )
            # get total processed metric
            total_processed = await self.stream_writer_client.total_processed()
            for group_name, processed_amount in total_processed.items():
                self._prom_metrics_dict["group_processed"].labels(stream_group=group_name, **self.prom_labels).set(
                    processed_amount
                )

            # wait for next collection
            await asyncio.sleep(self._config.metrics_collect_timeout)

    def prepare_tasks(self) -> CrawlerTasks:
        """Execute collection of asynchronous tasks"""

        tasks: CrawlerTasks = CrawlerTasks(
            main_crawl=self.crawl(),
            mount_crawl=None,
            stream_trim=self.trim_tail_task(),
            tag_crawl=None,
            stream_preparation=self.prepare_stream(),
            collect_system_metrics=None,
            collect_service_metrics=None,
        )

        # create crawl mount task
        if self._storage_config.storage_backend_type == AvailableStorageClients.nucleus:
            # create a task for crawling assets from mounts with certain periodicity
            tasks["mount_crawl"] = self.crawl_mounts()
            # create a task for listening to tag updates
            self._tag_subscription_event = asyncio.Event()
            tasks["tag_crawl"] = self._recreate_subscription_wrapper(self.crawl_tags)

        # initialize metrics task
        if self._config.use_prom_metrics:
            tasks["collect_system_metrics"] = self._process_metrics_collector.collect_metrics()
            tasks["collect_service_metrics"] = self.collect_service_metrics()

        return tasks
