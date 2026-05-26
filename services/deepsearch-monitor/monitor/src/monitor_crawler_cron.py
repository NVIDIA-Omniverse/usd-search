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
import time
from typing import List

from cache.src.client.config import RedisCacheConfig
from monitor.src.config import DeepSearchMonitorConfig
from monitor.src.logging_utils import setup_logging
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.misc_utils import get_percentage_string
from search_utils.storage_client import PathType
from search_utils.storage_client.config import StorageClientConfig, StorageConfig

from . import logger
from .monitor_crawler import DeepSearchMonitorBase


class DeepSearchMonitorServiceCron(DeepSearchMonitorBase):
    def __init__(
        self,
        monitor_config: DeepSearchMonitorConfig | None = None,
        cache_config: RedisCacheConfig | None = None,
        search_backend_config: NGSearchStorageSearchBackendConfig | None = None,
        storage_config: StorageConfig | None = None,
        storage_client_config: StorageClientConfig | None = None,
    ) -> None:
        # NOTE: Disable Redis tail auto trimming in workers. Since it is already done in the Monitor Crawler
        if cache_config is None:
            cache_config = RedisCacheConfig(cache_auto_trim_timeout=-1)
        else:
            cache_config.auto_trim_timeout = -1
        super().__init__(
            monitor_config=monitor_config,
            cache_config=cache_config,
            search_backend_config=search_backend_config,
            storage_config=storage_config,
            storage_client_config=storage_client_config,
        )

    async def plugin_cache_actualization(
        self,
        p_name: str,
        log_timeout: float = 30,
        batch_size: int = 256,
    ) -> None:
        # iterate through all local cache keys and verify that they are relevant
        bg = time.time()
        removed_counter = 0

        if self._ngsearch_storage_client is None:
            raise ValueError("Storage client is not initialized")

        batch: List[str] = []
        counter = 0
        async for k in self._cache_client.plugin_iter_keys(dest=f"{p_name}_path_to_hash"):
            counter += 1
            batch.append(k)
            if len(batch) > batch_size:
                response = await self._ngsearch_storage_client.exists(keys=batch)

                for r, b in zip(response.exists, batch):
                    if not r:
                        await self.clear_cached_item(omni_item=PathType(uri=b), p_name=p_name)
                        removed_counter += 1
                batch = []

            if time.time() - bg > log_timeout:
                logger.info(
                    "removed: %s processed: %s (%s)",
                    p_name,
                    get_percentage_string(removed_counter, counter),
                    get_percentage_string(
                        counter,
                        removed_counter + (await self.cache_client.plugin_len(dest=f"{p_name}_path_to_hash")),
                    ),
                )
                bg = time.time()

        if len(batch) > 0:
            response = await self._ngsearch_storage_client.exists(keys=batch)

            for r, b in zip(response.exists, batch):
                if not r:
                    await self.clear_cached_item(omni_item=PathType(uri=b), p_name=p_name)
                    removed_counter += 1

        len_plugin_cache = await self.cache_client.plugin_len(dest=f"{p_name}_path_to_hash")
        logger.info(
            "%s removed (%s)",
            get_percentage_string(removed_counter, removed_counter + len_plugin_cache),
            p_name,
        )

    async def run(self) -> None:
        # wait for cache client to be initialized
        await self.cache_client.ready.wait()
        await self.initialize_storage_client()
        while True:
            await asyncio.gather(*[self.plugin_cache_actualization(p_name=p.plugin_name) for p in self.plugins])
            await asyncio.sleep(self._monitor_config.metadata_redis_check_timeout)


def main() -> None:
    setup_logging()
    service = DeepSearchMonitorServiceCron()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(service.run())


if __name__ == "__main__":
    main()
