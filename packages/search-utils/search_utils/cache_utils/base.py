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
import hashlib

# standard modules
import os
import pickle
import queue
import time
from collections import OrderedDict
from typing import Any, Optional, Union

# third party modules
from prometheus_client import Gauge

# local / proprietary modules
from search_utils import database_utils as du
from search_utils.log_utils import print_wrapper
from search_utils.misc_utils import (
    any_from_string,
    any_to_string,
    clean_output_directory,
    compress_data,
    decompress_data,
)

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


class CacheDict:
    """Dictionary like caching class

    Args:
        path (str): path where data will be stored
        limit (int, optional): maximum number of samples in cache. Defaults to ``-1``.
    """

    def __init__(
        self,
        path: str,
        limit: int = -1,
        prom_metric: Gauge = None,
        serializer: callable = any_to_string,
        deserializer: callable = any_from_string,
        in_memory: bool = False,
        in_memory_limit: int = 2048,
    ):
        self.serializer = serializer
        self.deserializer = deserializer
        self.in_memory = in_memory
        self.in_memory_limit = in_memory_limit

        # create directory for cache
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # set the cache size limit
        self.limit = limit
        # initialize SQLite DB
        self.path = path
        self.sql_db = self.create_cache_db()
        self.prom_metric = prom_metric
        self.context = None
        self.cached_length = 0

        cache_utils_logger.debug(f"Cache dictionary initialized at: {path}")
        # initialized last accessed with 0
        if self.limit > 0:
            self.last_accessed = {k: 0 for k in self.keys()}
            # make sure that limit is respected
            self.check_limit()

        # set prometheus metrics
        self.reset_prom_metric()

        # define in memory cache
        if self.in_memory:
            self.in_memory_cache = InMemoryCache(self.in_memory_limit)
            # warm up cache
            self.in_memory_cache.update(self.to_dict(limit=self.in_memory_limit))
        self._len = self.get_len()

    def open_context(self):
        self.context = du.SQLContext(self.sql_db, multithreaded=True).__enter__()

    def close_context(self):
        if self.context is not None:
            self.context.__exit__()
            self.context = None

    def commit(self):
        if self.context is not None:
            self.context.commit()

    def create_cache_db(self):
        return du.AssetDB(
            db_path=self.path,
            tables=["cache"],
            list_keys=[["key", "content"]],
            list_key_types=[["TEXT PRIMARY KEY", "TEXT"]],
        )

    def reset_prom_metric(self):
        # set prometheus metrics
        if self.prom_metric:
            self.prom_metric.set(self.__len__())

    def clean_cache(self):
        self.sql_db.drop_table("cache")
        self.sql_db = self.create_cache_db()
        # define in memory cache
        if self.in_memory:
            self.in_memory_cache = InMemoryCache(self.in_memory_limit)
        # set prometheus metrics
        self.reset_prom_metric()
        self._len = 0

    def keys(self) -> list:
        """Get list of all keys that are in cache.

        Returns:
            list: list of keys in cache
        """
        if self.context is None:
            keys = self.sql_db.get_all("cache", col_name="key")
        else:
            keys = self.context.get_all_conn("cache", col_name="key")
        return [k[0] for k in keys]

    def find(self, key, startswith: bool = False) -> list:
        """Get list of all keys that are in cache.

        Returns:
            list: list of keys in cache
        """

        pattern = f"%{key}%"
        if startswith:
            pattern = pattern[1:]

        if self.context is None:
            keys = self.sql_db.get_all("cache", col_name="key", filter_field="key", filter_by=pattern)
        else:
            keys = self.context.get_all_conn("cache", col_name="key", filter_field="key", filter_by=pattern)
        return [k[0] for k in keys]

    def get_len(self) -> int:
        if self.context is None:
            count = self.sql_db.count_all("cache")
        else:
            count = self.context.get_all_conn("cache", "COUNT()")

        if len(count) > 0:
            self.cached_length = count[0][0]
        return self.cached_length

    def __len__(self) -> int:
        return self._len

    def items(
        self,
    ) -> tuple:
        """Generator for getting items and keys

        Yields:
            tuple: key and value
        """

        for k in self.keys():
            yield (k, self[k])

    def __getitem__(self, item: Any) -> Any:
        """Get item from cache.

        Args:
            item (Any): item key

        Raises:
            KeyError: if item is not present in cache

        Returns:
            Any: return item content
        """
        if self.in_memory and item in self.in_memory_cache.keys():
            return self.in_memory_cache[item]

        if self.context is None:
            raw_content = self.sql_db.get_row(str(item), "cache", "key", column="content")
        else:
            raw_content = self.context.get_row_conn(str(item), "cache", "key", column="content")
        if raw_content is None:
            raise KeyError(f"item {item} not found in cache")
        result = self.deserializer(raw_content[0])
        # update in memory cache
        if self.in_memory:
            self.in_memory_cache[item] = result
        # return item
        return result

    def __setitem__(self, item: Any, value: Any):
        self.update({item: value})

    def __delitem__(self, item: Any):
        if self.context is None:
            self.sql_db.remove(item, "cache", "key")
        else:
            self.context.remove_rows(item, "cache", "key")
        # refresh in memory cache
        if self.in_memory and item in self.in_memory_cache:
            del self.in_memory_cache[item]
        # clean the item from the last accessed ones
        if self.limit > 0 and item in self.last_accessed.keys():
            del self.last_accessed[item]
        # update prometheus metric
        self.reset_prom_metric()
        self._len = self.get_len()

    def update(self, input: dict):
        """Bulk update cache"""
        with print_wrapper(f"updating {len(input)} in cache", logger=cache_utils_logger.debug):
            update_list = [(str(k), self.serializer(v)) for k, v in input.items()]
            if self.context is None:
                with du.SQLContext(self.sql_db) as context:
                    context.insert_rows("cache", update_list, replace=True)
            else:
                self.context.insert_rows("cache", update_list, replace=True)

            # update prometheus metric
            self.reset_prom_metric()

            # update last accessed time
            if self.limit > 0:
                for k in input:
                    self.last_accessed[k] = time.time()
                # make sure limit is respected
                self.check_limit()
        # update in memory cache
        if self.in_memory:
            self.in_memory_cache.update(input)

        self._len = self.get_len()

    def check_limit(self, *args, **kwargs):
        """Make sure the cache size is less or equals to the limit."""
        if self.limit > 0:
            s = sorted(self.last_accessed.items(), key=lambda item: item[1])[::-1]
            keys_to_del = [it[0] for it in s[self.limit :]]

            for k in keys_to_del:
                del self[k]

    def get(self, item: Any, default: Any = None) -> Any:
        try:
            return self.__getitem__(item)
        except KeyError:
            return default

    def get_and_remove_next(self) -> Any:
        # get item key
        item_key = self.keys()[0]

        if self.in_memory and item_key in self.in_memory_cache:
            item = self.in_memory_cache[item_key]
            del self.in_memory_cache[item_key]
        else:
            item = self[item_key]

        del self[item_key]

        return item

    def to_dict(self, limit: int = None):
        # read all data
        content = self.sql_db.get_all("cache", limit=limit)
        # decode content
        return {k: self.deserializer(v) for k, v in content}


class FileCache(CacheDict):
    def __init__(self, cache_folder: str, compression: str = None, limit: int = -1):
        self.cache_folder = cache_folder
        self.compression = compression
        os.makedirs(self.cache_folder, exist_ok=True)
        super().__init__(
            f"{self.cache_folder}/cache.db",
            serializer=lambda x: x,
            deserializer=lambda x: x,
            limit=limit,
        )

    def __delitem__(self, name: str):
        fname = self.get_fname(name)
        try:
            os.remove(fname)
        except Exception as e:
            cache_utils_logger.warning(f"FileCache item removal exception as warning: {str(e)}")
        return super().__delitem__(name)

    def clean_cache(self):
        clean_output_directory(self.cache_folder)
        self.sql_db = self.create_cache_db()
        self._len = 0

    def get_fname(self, name: Any) -> str:
        return f"{self.cache_folder}/{hashlib.sha256(str(name).encode()).hexdigest()}.pkl"

    def compress_data(self, input_data):
        if self.compression is None:
            return input_data
        return compress_data(input_data, compression_type=self.compression)

    def decompress_data(self, input_data):
        if self.compression is None:
            return input_data
        return decompress_data(input_data, compression_type=self.compression)

    def update(self, input: dict):
        """Bulk update cache"""
        update_dict = {}
        for name, val in input.items():
            # convert input name to hash
            fname = self.get_fname(name)
            with open(fname, "wb") as file:
                pickle.dump(self.compress_data(val), file)

            update_dict[name] = fname

        # update SQL cache dict
        super().update(update_dict)
        # update length
        self._len = self.get_len()

    def __getitem__(self, name: str) -> Any:
        fname = self.get_fname(name)
        if not os.path.exists(fname):
            raise KeyError(f"item {name} not found in cache")

        with open(fname, "rb") as file:
            val = pickle.load(file)

        return self.decompress_data(val)

    def get(self, item: Any, default: Any = None) -> Any:
        try:
            return self[item]
        except KeyError:
            return default


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
