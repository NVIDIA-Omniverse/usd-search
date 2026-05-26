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
from contextlib import asynccontextmanager
from typing import MutableMapping, Optional

from deepsearch_crawler.config import ConsumerConfig
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.storage_client import (
    AvailableStorageClients,
    PathType,
    StorageClient,
    TagResultField,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig
from search_utils.storage_client.exceptions import AccessDeniedError, TokenExpired
from search_utils.streams.redis import RedisStreamConfig

from .base import _VT, CrawlerService
from .config import DeepSearchCrawlerConfig, DeepSearchTagCrawlerConfig
from .data import TagContent, TagDataContent
from .exceptions import NotSupportedForStorageClient

logger = logging.getLogger(__name__)


class TagCrawlerService(CrawlerService):
    def __init__(
        self,
        stream_config: Optional[RedisStreamConfig] = None,
        consumer_config: Optional[ConsumerConfig] = None,
        crawler_config: Optional[DeepSearchCrawlerConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        meta_data_cache: Optional[MutableMapping[str, _VT]] = None,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
    ) -> None:
        if storage_config is None:
            _storage_config = StorageConfig()
        else:
            _storage_config = storage_config

        if _storage_config.storage_backend_type in [AvailableStorageClients.s3]:
            raise NotSupportedForStorageClient(_storage_config.storage_backend_type)

        super().__init__(
            stream_config=stream_config,
            consumer_config=consumer_config,
            crawler_config=crawler_config,
            storage_config=storage_config,
            storage_client_config=storage_client_config,
            meta_data_cache=meta_data_cache,
            search_backend_config=search_backend_config,
        )

        # instance of the storage client
        self._storage_client_instance: Optional[StorageClient] = None

    @asynccontextmanager
    async def client_context(self) -> StorageClient:
        storage_client: StorageClient
        try:
            async with self._storage_client.connection_context_with_tagging() as storage_client:
                self._storage_client_instance = storage_client
                yield storage_client
        except TokenExpired as exc_info:
            logger.warning("Token expired - recreating connection", exc_info=exc_info)
        except AccessDeniedError as exc_info:
            logger.warning("Access Denied - recreating connection", exc_info=exc_info)
        await asyncio.sleep(0.1)

    @property
    def storage_client_instance(self) -> Optional[StorageClient]:
        return self._storage_client_instance

    def set_crawler_config(self, crawler_config: Optional[DeepSearchCrawlerConfig]) -> DeepSearchCrawlerConfig:
        if crawler_config is None:
            return DeepSearchTagCrawlerConfig()
        return crawler_config

    @staticmethod
    async def prepare_meta_dict(client: StorageClient, r: PathType) -> Optional[TagDataContent]:
        try:
            tag_result: TagResultField = await client.get_tags(path=r.uri)
        except FileNotFoundError:
            logger.warning("%s not found on the server", r.uri)
            return None
        except NotImplementedError:
            logger.debug("tag retrieval is not supported for backend with this URL: %s", r.uri)
            return None

        return TagDataContent(
            tags=[
                TagContent(
                    tag=t.name,
                    namespace=t.tag_namespace,
                    value="" if t.value is None else t.value,
                )
                for t in tag_result.tags
            ]
        )


def main() -> None:
    service = TagCrawlerService()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(service.run())


if __name__ == "__main__":
    main()
