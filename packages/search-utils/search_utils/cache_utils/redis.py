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

import abc
import logging
import os
import pickle
import queue
from time import time
from typing import Any, Iterator, List, MutableMapping, Optional, TypeVar

from redis import Redis
from redis.exceptions import RedisError

from search_utils.log_utils import set_simple_logger

logger = logging.getLogger(__name__)


_VT = TypeVar("_VT")  # value type


class BaseCacheDictRedis(abc.ABC, MutableMapping[str, _VT]):
    """A dictionary-like caching class with Redis backend"""

    def __init__(
        self,
        redis_url: str,
        database: Optional[int] = None,
        ttl_seconds: Optional[int] = None,
    ):
        url = f"{redis_url}/{database}" if database else redis_url
        self.client = Redis.from_url(url)
        self.ttl_seconds = ttl_seconds

    def is_ready(self) -> bool:
        try:
            self.client.ping()
        except RedisError as exc_info:
            logger.warning("Redis backend unavailable", exc_info=exc_info)
            return False
        return True

    def clean_cache(self) -> None:
        self.client.flushdb()

    @abc.abstractmethod
    def _serialize(self, value) -> bytes: ...

    @abc.abstractmethod
    def _deserialize(self, value: bytes) -> _VT: ...

    def keys(self) -> List[str]:
        """Get list of all keys that are in cache.

        Returns:
            list: list of keys in cache
        """
        return [k.decode("utf-8") for k in self.client.keys()]

    def iterkeys(self, reverse=False) -> Iterator[str]:
        """Iterate Cache keys in database sort order."""
        keys = self.keys()
        keys.sort(reverse=reverse)
        return iter(keys)

    def find(self, key: str, startswith: bool = False) -> List[str]:
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
        return [k.decode("utf-8") for k in self.client.keys(pattern)]

    def to_dict(self) -> dict:
        return {k: self[k] for k in self.keys()}

    def __len__(self) -> int:
        """Get the number of keys in the cache"""
        return self.client.dbsize()

    def __delitem__(self, key: str) -> None:
        self.client.delete(key)

    def __getitem__(self, key: str) -> _VT:
        value = self.client.get(key)
        if value is None:
            raise KeyError(f"{key} not found in the cache")
        return self._deserialize(value)

    def __setitem__(self, key: str, value: _VT) -> None:
        self.client.set(key, self._serialize(value), ex=self.ttl_seconds)

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())


class CacheDictRedis(BaseCacheDictRedis):
    def _serialize(self, value) -> bytes:
        return pickle.dumps(value)

    def _deserialize(self, value: bytes) -> _VT:
        return pickle.loads(value)


class RawCacheDictRedis(BaseCacheDictRedis[bytes]):
    """Redis cache dict class without serialization"""

    def _serialize(self, value) -> bytes:
        return value

    def _deserialize(self, value: bytes) -> bytes:
        return value


class CacheSetRedis(CacheDictRedis):
    # TODO: Replace with a proper, optimal queue
    def pop(self, key=None) -> Any:
        if key is None:
            if len(self) == 0:
                raise queue.Empty()
            # get item key
            for k in self.iterkeys():
                key = k
                break
        return super().pop(key)

    def insert(self, item: Any, key: str = None):
        # check if key is provided
        if key is None:
            key = str(time())
        # add item to cache
        self[key] = item

    def put(self, *args, **kwargs):
        self.insert(*args, **kwargs)


class RedisQueue:
    def __init__(
        self,
        redis_url: str,
        queue_name: str,
        database: Optional[int] = None,
    ):
        url = f"{redis_url}/{database}" if database else redis_url
        self.client = Redis.from_url(url)
        self.queue_name = queue_name

    def is_ready(self) -> bool:
        try:
            self.client.ping()
        except RedisError as exc_info:
            logger.warning("Redis backend unavailable", exc_info=exc_info)
            return False
        return True

    def clean_cache(self) -> None:
        self.client.delete(self.queue_name)

    def enqueue(self, *values):
        self.client.rpush(self.queue_name, *[pickle.dumps(v) for v in values])

    def dequeue(self, count: Optional[int] = None):
        value = self.client.lpop(self.queue_name, count=count)
        if value is None:
            raise queue.Empty()
        if isinstance(value, list):
            return [pickle.loads(v) for v in value]
        return pickle.loads(value)

    def __len__(self):
        return self.client.llen(self.queue_name)
