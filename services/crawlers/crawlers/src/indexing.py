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
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from search_utils.storage_client import PathType, StorageClient
from search_utils.storage_client.exceptions import AccessDeniedError, TokenExpired

from .base import CrawlerService
from .config import DeepSearchCrawlerConfig, DeepSearchIndexingConfig
from .data import PathMetaData

logger = logging.getLogger(__name__)


class IndexingService(CrawlerService):
    def set_crawler_config(self, crawler_config: Optional[DeepSearchCrawlerConfig]) -> DeepSearchCrawlerConfig:
        if crawler_config is None:
            return DeepSearchIndexingConfig()
        return crawler_config

    @asynccontextmanager
    async def client_context(self) -> StorageClient:
        storage_client: StorageClient
        try:
            async with self._storage_client.connection_context() as storage_client:
                self._storage_client_instance = storage_client
                yield storage_client
        except TokenExpired as exc_info:
            logger.warning("Token expired - recreating connection", exc_info=exc_info)
        except AccessDeniedError as exc_info:
            logger.warning("Access Denied - recreating connection", exc_info=exc_info)
        await asyncio.sleep(0.1)

    @staticmethod
    def ts_fn(input: float) -> datetime:
        return datetime.fromtimestamp(input) if input is not None else None

    @staticmethod
    async def prepare_meta_dict(client: StorageClient, r: PathType) -> Optional[Dict[str, Any]]:

        # get file extension
        ext = os.path.splitext(r.uri)[1][1:]
        result = PathMetaData.model_construct(
            path=client.get_path_from_uri(r.uri),
            name=os.path.basename(r.uri.rstrip("/")),
            ext=ext,
            pathType=str(client.get_file_type(r).value),
            created_by=r.created_by,
            modified_by=r.modified_by,
            created_timestamp=IndexingService.ts_fn(r.created_date_seconds),
            modified_timestamp=IndexingService.ts_fn(r.modified_date_seconds),
            empty=bool(r.empty),
            etag=r.etag,
            hash_type=r.hash_type,
            hash_value=r.hash_value,
            hash_block_size=r.hash_bsize,
            on_mount=bool(r.mounted),
            size=r.size,
            status=str(r.status),
            is_deleted=r.is_deleted,
            deleted_by=r.deleted_by,
            deleted_timestamp=IndexingService.ts_fn(r.deleted_date_seconds),
        )

        return result.model_dump(exclude_none=True)


def main():
    service = IndexingService()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(service.run())


if __name__ == "__main__":
    main()
