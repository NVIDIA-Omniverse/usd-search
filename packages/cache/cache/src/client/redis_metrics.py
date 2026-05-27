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
import os
from typing import Dict, TypedDict

from plugins import BasePlugin
from prometheus_client import Gauge

from search_utils.log_utils import set_simple_logger
from search_utils.storage_client.utils import task_wrapper
from search_utils.streams.base import StreamUnavailable

from . import CacheClientRedis

logger = set_simple_logger("redis cache metrics", os.getenv("REDIS_CACHE_METRICS_LOGLEVEL", "INFO"))


class RedisPromMetrics(TypedDict):
    plugin_total_len_metric: Gauge
    plugin_unique_len_metric: Gauge
    results_queue_metric: Gauge
    plugin_tasks_count_metric: Gauge


class RedisCacheMetrics:
    def __init__(  # type: ignore[no-any-unimported] # missing stubs
        self,
        cache_client: CacheClientRedis,
        common_labels: Dict[str, str],
        plugins: list[BasePlugin],
        refresh_interval_seconds: float = 10.0,
    ):
        self.cache_client = cache_client
        self.plugins = plugins
        self.common_labels = common_labels
        self.refresh_interval_seconds = refresh_interval_seconds

        self._metrics = RedisPromMetrics(
            plugin_total_len_metric=Gauge(
                "omnideepsearch_plugin_items_processed",
                "Total count of files processed by a given plugin",
                labelnames=list(self.common_labels.keys()) + ["plugin_name"],
            ),
            plugin_unique_len_metric=Gauge(
                "omnideepsearch_plugin_unique_items_processed",
                "Count of unique files processed by a given plugin",
                labelnames=list(self.common_labels.keys()) + ["plugin_name"],
            ),
            results_queue_metric=Gauge(
                "omnideepsearch_results_queue_size",
                "Count of results queued for processing",
                labelnames=list(self.common_labels.keys()),
            ),
            plugin_tasks_count_metric=Gauge(
                "omnideepsearch_plugin_tasks_queue_size",
                "Count of tasks for plugin queued for processing",
                labelnames=list(self.common_labels.keys()) + ["plugin_name"],
            ),
        )

    @property
    def metrics(self) -> RedisPromMetrics:
        return self._metrics

    def init_metric_collection_task(self) -> None:
        loop = asyncio.get_event_loop()
        loop.create_task(task_wrapper(self.collect_cache_metrics, name="Collect cache metrics"))

    async def collect_cache_metrics(self) -> None:
        while True:
            try:
                results_queue_len = await self.cache_client.result_queue_len()

                plugin_processed_total_len = {
                    p.plugin_name: await self.cache_client.plugin_len(f"{p.plugin_name}_path_to_hash")
                    for p in self.plugins
                }
                # Note: The following metric counts also deleted items (as long as their cache keys don't expire)
                plugin_processed_unique_len = {
                    p.plugin_name: await self.cache_client.plugin_len(f"{p.plugin_name}_hash_to_file")
                    for p in self.plugins
                }

                logger.debug(
                    "%s %s %s",
                    results_queue_len,
                    plugin_processed_total_len,
                    plugin_processed_unique_len,
                )

                self.metrics["results_queue_metric"].labels(*self.common_labels.values()).set(results_queue_len)

                for plugin in self.plugins:
                    try:
                        self._metrics["plugin_tasks_count_metric"].labels(
                            *self.common_labels.values(), plugin.plugin_name
                        ).set(await self.cache_client.plugin_queue_len(plugin_name=plugin.plugin_name))
                    except StreamUnavailable as exc_info:
                        logger.warning(str(exc_info))

                for plugin_name, length in plugin_processed_total_len.items():
                    self.metrics["plugin_total_len_metric"].labels(*self.common_labels.values(), plugin_name).set(
                        length
                    )
                for plugin_name, length in plugin_processed_unique_len.items():
                    self.metrics["plugin_unique_len_metric"].labels(*self.common_labels.values(), plugin_name).set(
                        length
                    )

            except Exception as exc_info:
                logger.exception(
                    "Error collecting Redis cache metrics: %s",
                    exc_info,
                    exc_info=exc_info,
                )

            await asyncio.sleep(self.refresh_interval_seconds)
