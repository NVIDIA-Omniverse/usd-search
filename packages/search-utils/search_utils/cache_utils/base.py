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

# standard modules
import queue
import time
from collections import OrderedDict
from typing import Any, Optional, Union

from . import cache_utils_logger


class SharedDictCounter:
    def __init__(self) -> None:
        self.content_dict = {}
        self.counter_dict = {}

    def __setitem__(self, key, value):
        self.content_dict[key] = value

    def inc(self, key):
        self.counter_dict[key] = self.counter_dict.get(key, 0) + 1

    def __len__(self):
        return len(self.content_dict)

    def keys(self):
        return self.content_dict.keys()

    def __getitem__(self, key):
        if key not in self.content_dict:
            raise KeyError(key)

        if key not in self.counter_dict:
            if key in self.content_dict:
                del self.content_dict[key]
            raise KeyError(key)

        self.counter_dict[key] -= 1
        result = self.content_dict[key]
        if self.counter_dict[key] == 0:
            del self.content_dict[key]
            del self.counter_dict[key]
        return result


class CacheContext:
    def __init__(self, caches: Union[list, Any], commit_delay: float = 30):
        if not isinstance(caches, list):
            caches = [caches]
        self.caches = caches
        self.last_commit = time.time()
        self.commit_delay = commit_delay

    def __enter__(self):
        for cache in self.caches:
            if hasattr(cache, "open_context"):
                cache.open_context()
        return self

    def __exit__(self, *args, **kwargs):
        for cache in self.caches:
            if hasattr(cache, "close_context"):
                cache.close_context()

    def commit(
        self,
    ):
        for c in self.caches:
            if hasattr(c, "commit"):
                c.commit()

    async def background_commit_task(self):
        while True:
            try:
                self.commit()
                self.last_commit = time.time()
            except Exception as e:
                cache_utils_logger.warning(f"Background commit error {str(e)}")

            await asyncio.sleep(self.commit_delay)


class InMemoryCache(dict):
    def __init__(self, limit: int = -1):
        self.limit = limit
        self.last_accessed = OrderedDict()
        self.last_accessed.update({k: 0 for k in self.keys()})
        if self.limit > 0:
            # make sure that limit is respected
            self.check_limit()

    def __setitem__(self, k, v) -> None:
        super().__setitem__(k, v)
        if k in self.last_accessed:
            self.last_accessed.pop(k)
        self.last_accessed[k] = time.time()
        if self.limit > 0:
            # make sure limit is respected
            self.check_limit()

    def __delitem__(self, __v) -> None:
        super().__delitem__(__v)
        if __v in self.last_accessed.keys():
            del self.last_accessed[__v]

    def update(self, input: dict):
        super().update(input)
        for k in input:
            if k in self.last_accessed:
                self.last_accessed.pop(k)
            self.last_accessed[k] = time.time()
        if self.limit > 0:
            # make sure limit is respected
            self.check_limit()

    def check_limit(
        self,
    ):
        """Make sure the cache size is less or equals to the limit."""
        if self.limit > 0:
            keys = list(self.last_accessed.keys())
            keys_to_del = keys[: (len(self.last_accessed) - self.limit)]
            # s = sorted(self.last_accessed.items(), key=lambda item: item[1])[::-1]
            # keys_to_del = [it[0] for it in s[self.limit :]]

            for k in keys_to_del:
                try:
                    del self[k]
                except KeyError:
                    cache_utils_logger.warning(f"'{k}' not found")

    def clean_cache(self):
        keys_to_del = list(self.keys())
        for k in keys_to_del:
            del self[k]
        self.last_accessed = {}


class InMemoryCacheQueue(InMemoryCache):
    counter = 0

    def task_done(self):
        pass

    def put_nowait(self, item, key: Optional[str] = None) -> None:
        if key is None:
            key = str(self.counter)
            self.counter += 1
        # add item to cache
        self[key] = item

    def get_nowait(self):
        if len(self) == 0:
            raise queue.Empty()

        # get item key
        item_key = list(self.keys())[0]
        item = self[item_key]
        del self[item_key]
        return item

    async def get(self):
        while len(self) == 0:
            await asyncio.sleep(1)

        return self.get_nowait()

    async def put(self, item: Any, key: Optional[str] = None) -> None:
        while self.limit > 0 and len(self) >= self.limit:
            await asyncio.sleep(1)

        self.put_nowait(item, key)
