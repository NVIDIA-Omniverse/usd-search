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

# standard modules
import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache, partial
from queue import Empty
from typing import Any, AsyncIterator, Dict, List, Optional, TypedDict, Union

# third party modules
import orjson
import redis.asyncio as redis
import xxhash

# local/proprietary modules
from deepsearch_utils import secure_pickle
from plugins import Plugins
from redis.asyncio import Redis

from search_utils.hashing_utils import get_hash
from search_utils.log_utils import set_simple_logger
from search_utils.streams.redis import (
    RedisStreamConfig,
    RedisStreamWorker,
    StreamCorruptionError,
)

from .. import (
    GenericPluginStatus,
    JobItem,
    PluginItemStatus,
    PluginItemStatusHistory,
    ResultItem,
)
from .base import CacheClient
from .config import RedisCacheConfig

logger = set_simple_logger(logger_name="redis cache", loglevel=os.getenv("REDIS_CACHE_LOG_LEVEL", "INFO"))


@lru_cache(maxsize=1024)
def get_short_hash(input_: str) -> bytes:
    return xxhash.xxh32(input_).digest()


class RedisCacheStreamWorker(RedisStreamWorker):
    def serialize(self, item: bytes) -> bytes:
        return item

    def deserialize(self, item: bytes) -> bytes:
        return item


class RedisCacheStreams(TypedDict):
    results: RedisCacheStreamWorker


class CacheClientRedis(CacheClient):
    """Redis cache client class.

    Args:
        config (Optional[RedisCacheConfig], optional): Redis cache configuration. Defaults to None.
        skip_worker_streams_initialization (bool, optional): if ``True`` - worker configuration is not initialized, which may be needed in some cases (e.g. for the omni writer service). Defaults to False.
        active_plugins (Optional[List[str]], optional): Optionally specify list of required plugins to avoid connecting to those worker streams that are not needed. Defaults to None.
    """

    def __init__(
        self,
        config: Optional[RedisCacheConfig] = None,
        skip_worker_streams_initialization: bool = False,
        active_plugins: Optional[List[str]] = None,
    ) -> None:
        if config is None:
            self._config = RedisCacheConfig()
        else:
            self._config = config

        # initialize Redis connection
        self._connection = redis.Redis.from_url(url=self.config.url)
        self._skip_worker_streams_initialization = skip_worker_streams_initialization
        self._active_plugins = active_plugins

        # define some common kwargs for cache streams
        stream_common_kwargs = dict(
            url=self.config.url,
            consumer_name=self.consumer_name,
            raise_on_stream_corruption=True,
        )

        self._ready = asyncio.Event()

        # create streams for different instances
        self._streams = RedisCacheStreams(
            results=RedisCacheStreamWorker(
                RedisStreamConfig(
                    name=f"{self.config.stream_name_prefix}_results",
                    autoclaim_min_idle_time=self.config.results_autoclaim_min_idle_time,
                    consumer_group=self.config.results_consumer_group,
                    **stream_common_kwargs,
                )
            ),
        )
        if not self._skip_worker_streams_initialization:
            for plugin in Plugins.get_all_plugins():
                # skip connection to those worker streams that are not needed
                if self._active_plugins is not None and plugin.plugin_name not in self._active_plugins:
                    continue

                autoclaim_min_idle_time = self.config.non_farm_job_autoclaim_min_idle_time
                if plugin.render:
                    autoclaim_min_idle_time = self.config.farm_job_autoclaim_min_idle_time

                self._streams[f"{plugin.plugin_name}_jobs"] = RedisCacheStreamWorker(
                    RedisStreamConfig(
                        name=f"{self.config.stream_name_prefix}_{plugin.plugin_name}_jobs",
                        autoclaim_min_idle_time=autoclaim_min_idle_time,
                        autoclaim_n_retries=self.config.job_autoclaim_n_retries,
                        consumer_group=self.config.consumer_group,
                        **stream_common_kwargs,
                    ),
                    retry_limit_reached_callback=partial(
                        self.retry_limit_reached_callback,
                        plugin_name=plugin.plugin_name,
                    ),
                )

            self.check_all_plugins_initialization()

        # create auto_trim_task
        loop = asyncio.get_event_loop()
        self.auto_trim_task: asyncio.Task[None] = loop.create_task(self._auto_trim_task())
        self.connect_consumers_task = loop.create_task(self._connect_consumers())

    async def retry_limit_reached_callback(self, item_list: List[bytes], plugin_name: str) -> None:
        for serialized_item in item_list:
            item: JobItem = self._deserialize_item_or_list(serialized_item)
            logger.warning(
                "Maximum number of retries [%d] for file %s reached. Will attempt reindex only on hash change or manual reindex request.",
                self.config.job_autoclaim_n_retries,
                item["uri"],
            )
            await self.add_asset_status(
                plugin_name=plugin_name,
                uri=item["uri"],
                hash_value=item.get("hash_value"),
                status=GenericPluginStatus.failed_retries_exhausted,
                exception=f"Processing exception: maximum number of attempts reached [{self.config.job_autoclaim_n_retries}]",
            )
            await self.set_plugin_path_to_hash(
                plugin_name=plugin_name,
                uri=item["uri"],
                hash_value=item.get("hash_value"),
            )

    def check_all_plugins_initialization(self) -> None:
        for plugin_name in Plugins.get_plugin_names():
            if self._active_plugins is not None and plugin_name not in self._active_plugins:
                continue
            if f"{plugin_name}_jobs" not in self.streams:
                raise ValueError(f"Plugin {plugin_name} not found")

    @property
    def consumer_name(self) -> str:
        return self.config.consumer_name_prefix + "_" + str(uuid.uuid4().hex[:8]) + "_" + os.getenv("HOSTNAME", "")

    async def _terminate(self) -> None:
        self.auto_trim_task.cancel()
        await asyncio.wait({self.auto_trim_task}, timeout=1)
        if not self._skip_worker_streams_initialization:
            for plugin_name in Plugins.get_plugin_names():
                if self._active_plugins is not None and plugin_name not in self._active_plugins:
                    continue
                await self.clean_plugin_queue(plugin_name)
        await self.clean_results_queue()

    async def _auto_trim_task(self) -> None:
        if self.config.auto_trim_timeout < 0:
            logger.warning("Tail trimming is disabled. To enable - set CACHE_AUTO_TRIM_TIMEOUT value >=0")
            return

        while True:
            stream: RedisCacheStreamWorker
            for stream in self.streams.values():
                try:
                    await stream.trim_tail()
                except StreamCorruptionError as exc_info:
                    logger.warning(str(exc_info))
                    if self.config.reset_stream_on_corruption:
                        await self._clean_stream(stream_worker=stream)
                except Exception as exc_info:
                    logger.warning("Tail trim failure: %s", str(exc_info))
            await asyncio.sleep(self.config.auto_trim_timeout)

    async def _connect_consumers(self) -> None:
        while True:
            try:
                stream: RedisCacheStreamWorker
                for stream in self.streams.values():
                    await stream.connect_consumer()
                self._ready.set()
                break
            except Exception as exc_info:
                logger.warning(exc_info)
                await asyncio.sleep(0.1)

    @property
    def ready(self) -> asyncio.Event:
        return self._ready

    def is_ready(self) -> bool:
        return self.ready.is_set()

    @property
    def connection(self) -> Redis:
        return self._connection

    @property
    def config(self) -> RedisCacheConfig:
        return self._config

    @property
    def streams(self) -> RedisCacheStreams:
        return self._streams

    async def _flush_db(self) -> None:
        await self.connection.flushdb()

    async def _put(self, stream_worker: RedisStreamWorker, content: Union[bytes, List[bytes]]) -> None:
        """Add item to a Redis Stream

        Args:
            stream_worker (RedisStreamWorker): redis stream worker
            content (Union[bytes, List[bytes]]): item content or a list of contents
        """
        if not isinstance(content, list):
            content = [content]

        for item in content:
            await stream_worker.put(item)

    @staticmethod
    def _validate_job(content: Union[JobItem, List[JobItem]]) -> List[JobItem]:
        if not isinstance(content, list):
            content = [content]
        return content

    @asynccontextmanager
    async def _get(self, stream_worker: RedisStreamWorker, count: Optional[int] = None) -> Any:
        if count is None:
            count = 1

        async with stream_worker.consume(count=count) as items:
            if len(items) == 0:
                raise Empty

            yield self._deserialize_item_or_list(items)

    async def _stream_len(self, stream_worker: RedisStreamWorker) -> int:
        return int(await stream_worker.stream_length())

    async def _total_unprocessed(self, stream_worker: RedisStreamWorker) -> int:
        result = await stream_worker.get_unprocessed_items_length()
        if result is None:
            return 0
        return result

    async def _clean_stream(self, stream_worker: RedisStreamWorker) -> None:
        await stream_worker.reset_stream()
        await stream_worker.connect_consumer()

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[Redis]:
        yield self.connection

    async def plugin_queue_push_raw(self, dest: str, content: Dict[Union[str, bytes], bytes]) -> None:
        for base_key, value in content.items():
            base_key = base_key.encode("utf-8") if isinstance(base_key, str) else base_key
            key = self.config.plugin_prefix + get_short_hash(dest) + base_key
            await self.connection.lpush(key, value)

    async def plugin_queue_push(self, dest: str, content: Dict[Union[str, bytes], bytes]) -> None:
        await asyncio.gather(
            *[
                self.plugin_queue_push_raw(dest, {base_key: secure_pickle.dumps(value)})
                for base_key, value in content.items()
            ]
        )

    async def plugin_queue_trim(self, dest: str, base_key: Union[str, bytes], start: int, end: int) -> None:
        base_key = base_key.encode("utf-8") if isinstance(base_key, str) else base_key
        key = self.config.plugin_prefix + get_short_hash(dest) + base_key
        await self.connection.ltrim(name=key, start=start, end=end)

    async def plugin_queue_get_raw(self, dest: str, base_key: Union[str, bytes], start: int, end: int) -> list:
        base_key = base_key.encode("utf-8") if isinstance(base_key, str) else base_key
        key = self.config.plugin_prefix + get_short_hash(dest) + base_key
        list_of_items = await self.connection.lrange(name=key, start=start, end=end)
        if list_of_items is None:
            raise KeyError
        return list_of_items

    async def plugin_queue_get(self, dest: str, base_key: str, start: int, end: int) -> list:
        serialized_list = await self.plugin_queue_get_raw(dest=dest, base_key=base_key, start=start, end=end)
        return [
            secure_pickle.loads(serialized_item, approved_imports=secure_pickle.CACHE_CLASSES)
            for serialized_item in serialized_list
        ]

    async def plugin_update(
        self,
        dest: str,
        content: Dict[Union[str, bytes], bytes],
        ttl_seconds: Optional[int] = None,
    ) -> None:
        await asyncio.gather(
            *[
                self.plugin_update_raw(
                    dest,
                    {base_key: secure_pickle.dumps(value)},
                    ttl_seconds=ttl_seconds,
                )
                for base_key, value in content.items()
            ]
        )

    async def plugin_update_raw(
        self,
        dest: str,
        content: Dict[Union[str, bytes], bytes],
        ttl_seconds: Optional[int] = None,
    ) -> None:
        for base_key, value in content.items():
            base_key = base_key.encode("utf-8") if isinstance(base_key, str) else base_key
            key = self.config.plugin_prefix + get_short_hash(dest) + base_key
            await self.connection.set(key, value, ex=ttl_seconds)

    async def plugin_get(self, dest: str, key: Union[str, bytes]) -> Any:
        key = key.encode("utf-8") if isinstance(key, str) else key
        redis_key = self.config.plugin_prefix + get_short_hash(dest) + key
        item = await self.connection.get(redis_key)
        if item is None:
            raise KeyError
        return secure_pickle.loads(item, approved_imports=secure_pickle.CACHE_CLASSES)

    async def plugin_get_raw(self, dest: str, key: Union[bytes, str]) -> bytes:
        key = key.encode("utf-8") if isinstance(key, str) else key
        redis_key = self.config.plugin_prefix + get_short_hash(dest) + key
        item: Optional[bytes] = await self.connection.get(redis_key)
        if item is None:
            raise KeyError
        return item

    async def plugin_len(self, dest: str) -> int:
        # TODO: Rewrite to avoid fetching all keys
        return len(await self.plugin_keys_raw(dest))

    async def plugin_del(self, dest: str, keys: List[Union[str, bytes]]) -> None:
        for key in keys:
            key = key.encode("utf-8") if isinstance(key, str) else key
            redis_key = self.config.plugin_prefix + get_short_hash(dest) + key
            await self.connection.delete(redis_key)

    async def plugin_keys(self, dest: str) -> List[str]:
        # Note: this method is of O(n) complexity
        return [k.decode("utf-8") for k in await self.plugin_keys_raw(dest)]

    async def plugin_keys_raw(self, dest: str) -> List[bytes]:
        # Note: this method is of O(n) complexity
        redis_key = self.config.plugin_prefix + get_short_hash(dest)
        keys: List[bytes] = await self.connection.keys(redis_key + b"*")

        prefix_len = len(redis_key)
        # We need to return only the key suffixes
        return [k[prefix_len:] for k in keys]

    async def plugin_key_exists(self, dest: str, key: Union[str, bytes]) -> bool:
        key = key.encode("utf-8") if isinstance(key, str) else key
        redis_key = self.config.plugin_prefix + get_short_hash(dest) + key
        return await self.connection.get(redis_key) is not None

    async def plugin_find(self, dest: str, key: Union[str, bytes]) -> List[str]:
        # Note: this method is of O(n) complexity
        key = key.encode("utf-8") if isinstance(key, str) else key
        prefix = self.config.plugin_prefix + get_short_hash(dest)
        keys: List[bytes] = await self.connection.keys(prefix + key + b"*")

        prefix_len = len(prefix)
        return [k[prefix_len:].decode("utf-8") for k in keys]

    async def plugin_clean(self, dest: str) -> None:
        # Note: this method is of O(n) complexity

        redis_key = self.config.plugin_prefix + get_short_hash(dest)
        keys = await self.connection.keys(redis_key + b"*")
        if keys:
            await self.connection.delete(*keys)

    @staticmethod
    def _serialize_item_or_list(
        content: Union[List[Any], Any],
    ) -> Union[bytes, List[bytes]]:
        """Serialize input using ORJSON library. In case objects do not support serialization
        (e.g. pydantic classes) - the default serialization mechanism will be used, which calls the
        dict() method from the class.

        Args:
            content (Union[List[Any], Any]): Input that requires serialziation.

        Returns:
            Union[bytes, List[bytes]]: serialized output
        """
        if isinstance(content, list):
            return [
                orjson.dumps(
                    elem,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                    default=lambda x: x.model_dump(),
                )
                for elem in content
            ]
        return orjson.dumps(content, option=orjson.OPT_SERIALIZE_NUMPY, default=lambda x: x.model_dump())

    @staticmethod
    def _deserialize_item_or_list(
        content: Union[bytes, List[bytes]],
    ) -> Union[List[Any], Any]:
        if isinstance(content, list):
            return [orjson.loads(elem) for elem in content]
        return orjson.loads(content)

    async def enqueue_plugin_job(self, plugin_name: str, content: Union[List[JobItem], JobItem]) -> None:
        self._validate_job(content)
        await self._put(self.streams[f"{plugin_name}_jobs"], self._serialize_item_or_list(content))

    async def enqueue_result(self, content: ResultItem) -> None:
        await self._put(self.streams["results"], self._serialize_item_or_list(content))

    @asynccontextmanager
    async def get_plugin_job(self, plugin_name: str, count: Optional[int] = None) -> AsyncIterator[List[JobItem]]:
        async with self._get(self.streams[f"{plugin_name}_jobs"], count) as jobs:
            yield jobs

    @asynccontextmanager
    async def get_result(self, count: Optional[int] = None) -> AsyncIterator[List[ResultItem]]:
        async with self._get(self.streams["results"], count) as results:
            yield results

    async def plugin_queue_len(self, plugin_name: str) -> int:
        return await self._total_unprocessed(self.streams[f"{plugin_name}_jobs"])

    async def result_queue_len(self) -> int:
        return await self._total_unprocessed(self.streams["results"])

    async def clean_plugin_queue(self, plugin_name: str) -> None:
        await self._clean_stream(self.streams[f"{plugin_name}_jobs"])

    async def clean_results_queue(self) -> None:
        await self._clean_stream(self.streams["results"])

    async def plugin_iter_keys(self, dest: str) -> AsyncIterator[str]:
        # TODO: Rewrite to avoid fetching all keys at once
        results = await self.plugin_keys(dest)
        for res in results:
            yield res

    async def get_asset_status(
        self, plugin_name: str, uri: str, start: int = 0, end: int = -1
    ) -> PluginItemStatusHistory:
        return PluginItemStatusHistory(
            item_status_history=[
                PluginItemStatus(**status_item)
                for status_item in self._deserialize_item_or_list(
                    await self.plugin_queue_get_raw(
                        f"{plugin_name}_path_to_status_list",
                        base_key=uri,
                        start=start,
                        end=end,
                    )
                )
            ]
        )

    async def add_asset_status(
        self,
        plugin_name: str,
        uri: str,
        hash_value: Optional[str],
        status: GenericPluginStatus = GenericPluginStatus.ok,
        exception: Optional[str] = None,
    ) -> None:
        new_status = PluginItemStatus(
            status=status,
            hash_value=hash_value,
            processing_timestamp=time.time(),
            exception=exception,
        )
        await self.plugin_queue_push_raw(
            dest=f"{plugin_name}_path_to_status_list",
            content={uri: self._serialize_item_or_list(new_status)},
        )
        await self.plugin_queue_trim(
            dest=f"{plugin_name}_path_to_status_list",
            base_key=uri,
            start=0,
            end=PluginItemStatusHistory.Config.history_length - 1,
        )

    async def set_plugin_path_to_hash(self, plugin_name: str, uri: str, hash_value: Optional[str]) -> None:
        hashed_hash_value = get_hash(hash_value)
        await self.plugin_update_raw(dest=f"{plugin_name}_path_to_hash", content={uri: hashed_hash_value})

    async def set_plugin_hash_to_file(
        self,
        plugin_name: str,
        uri: str,
        hash_value: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        hashed_hash_value = get_hash(hash_value)
        await self.plugin_update(
            dest=f"{plugin_name}_hash_to_file",
            content={hashed_hash_value: uri},
            ttl_seconds=ttl_seconds,
        )
