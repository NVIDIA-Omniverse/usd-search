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
from typing import AsyncIterator, List, Optional

import redis

from search_utils.storage_client import PathType
from search_utils.streams import get_stream_worker
from search_utils.streams.base import StreamGroupStatistics
from search_utils.streams.redis import RedisStreamConfig

from .config import ConsumerConfig
from .exceptions import StreamBackendUnavailable

logger = logging.getLogger(__name__)


class DeepSearchConsumer:
    def __init__(  # type: ignore[no-any-unimported]  # missing stubs
        self,
        stream_config: Optional[RedisStreamConfig] = None,
        consumer_config: Optional[ConsumerConfig] = None,
    ) -> None:

        if consumer_config is None:
            self._config = ConsumerConfig()
        else:
            self._config = consumer_config

        if stream_config is None:
            self._stream_config = RedisStreamConfig(
                name=self.config.stream_name,
                consumer_group=self.config.stream_group_name,
                consumer_name=self.config.stream_consumer_name,
            )
        else:
            self._stream_config = stream_config

        # initialize stream client
        logger.info(self._stream_config.model_dump())
        self._stream_client = get_stream_worker(self.config.stream_type, config=self._stream_config)
        # prepare stream
        self._stream_is_connected = asyncio.Event()
        loop = asyncio.get_event_loop()
        self._connection_task = loop.create_task(self._connect())

    async def statistics(self) -> StreamGroupStatistics:  # type: ignore[no-any-unimported]  # missing stubs
        return await self._stream_client.get_group_statistics(self.config.stream_group_name)

    @property
    def ready(self) -> asyncio.Event:
        return self._stream_is_connected

    @property
    def config(self) -> ConsumerConfig:
        return self._config

    async def _connect(self) -> None:
        while True:
            try:
                await self._stream_client.connect_consumer()
                self._stream_is_connected.set()
                return
            except (
                ConnectionRefusedError,
                redis.exceptions.ConnectionError,
            ) as exc_info:
                logger.warning("Error connecting to the stream backend %s", str(exc_info))
            except (
                Exception
            ) as exc_info:  # pylint: disable=broad-except # reason - here we don't know in advance error will be thrown
                logger.exception(exc_info)
            await asyncio.sleep(0.5)

    async def close(self) -> None:
        self._connection_task.cancel()
        try:
            await self._connection_task
        except asyncio.CancelledError:
            pass

    @asynccontextmanager
    async def consume(  # type: ignore[misc,no-any-unimported]  # allow not found PathType
        self, count: int = 1
    ) -> AsyncIterator[Optional[List[PathType]]]:
        try:
            await asyncio.wait_for(
                self._stream_is_connected.wait(),
                timeout=self.config.stream_connection_timeout,
            )
        except asyncio.TimeoutError as exc_info:
            if not await self._stream_client.stream_available():
                raise StreamBackendUnavailable(exc_info) from exc_info
            raise asyncio.TimeoutError from exc_info

        items: List[PathType]  # type: ignore[no-any-unimported]  # allow not found PathType
        async with self._stream_client.consume(count=count) as items:
            if len(items) > 0:
                yield items
            else:
                yield None
