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

import logging
from typing import Any, List, Optional

from redis.asyncio import Redis
from redis.exceptions import RedisError

from search_utils import secure_pickle
from search_utils.secure_pickle import CACHE_APPROVED_CLASSES

logger = logging.getLogger(__name__)


class AsyncCacheRedis:
    """An async caching class with Redis backend"""

    def __init__(
        self,
        redis_url: str,
        database: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ):
        url = f"{redis_url}/{database}" if database else redis_url
        self.client = Redis.from_url(url)
        self.ttl_seconds = ttl_seconds

    async def is_ready(self) -> bool:
        try:
            await self.client.ping()
        except RedisError as exc_info:
            logger.warning("Redis backend unavailable", exc_info=exc_info)
            return False
        return True

    async def clean_cache(self) -> None:
        await self.client.flushdb()

    async def keys(self) -> List[str]:
        """Get list of all keys that are in cache.

        Returns:
            list: list of keys in cache
        """
        return [k.decode("utf-8") for k in await self.client.keys()]

    async def find(self, key: str, startswith: bool = False) -> List[str]:
        """Get list of all keys that are in cache.
        NOTE: This method has a time complexity of O(N) with N being the number of keys in the database, under the
        assumption that the key names in the database and the given pattern have limited length.

        Returns:
            list: list of keys in cache
        """
        if startswith:
            pattern = f"{key}*"
        else:
            pattern = f"*{key}*"
        return [k.decode("utf-8") for k in await self.client.keys(pattern)]

    async def to_dict(self) -> dict:
        return {k: await self.get(k) for k in await self.keys()}

    async def len(self) -> int:
        """Get the number of keys in the cache"""
        return await self.client.dbsize()

    async def delete(self, key: str) -> None:
        await self.client.delete(key)

    async def get(self, key: str) -> Any:
        value = await self.client.get(key)
        if value is None:
            raise KeyError(f"{key} not found in the cache")
        return secure_pickle.loads(value, approved_imports=CACHE_APPROVED_CLASSES)

    async def set(self, key: str, value: Any) -> None:
        await self.client.set(key, secure_pickle.dumps(value), ex=self.ttl_seconds)
