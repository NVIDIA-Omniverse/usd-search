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
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Tuple,
)

from pydantic_settings.main import SettingsConfigDict
from redis.asyncio import Redis, ResponseError

from .base import (
    AnyDict,
    StreamConfig,
    StreamGroupStatistics,
    StreamItem,
    StreamUnavailable,
    StreamWorker,
)

logger = logging.getLogger(__name__)


class StreamCorruptionError(Exception):
    pass


class RedisStreamConfig(StreamConfig):
    name: str
    consumer_group: Optional[str] = None
    consumer_name: Optional[str] = None
    url: str = "redis://localhost:6379"
    approximate_tail_trim: bool = False
    autoclaim_min_idle_time: int = 60000  # in milliseconds (default: 1 min)
    autoclaim_n_retries: Optional[int] = None
    raise_on_stream_corruption: bool = False
    model_config = SettingsConfigDict(env_prefix="redis_stream_")


class RedisStreamWorker(StreamWorker):
    def __init__(
        self,
        config: RedisStreamConfig,
        retry_limit_reached_callback: Optional[Callable[[Any], Awaitable[None]]] = None,
    ) -> None:
        self._config = config
        self._connection = Redis.from_url(self._config.url)
        self._retry_limit_reached_callback = retry_limit_reached_callback
        logger.info("Connecting to Redis at: %s", self._config.url)

    @property
    def config(self) -> RedisStreamConfig:
        return self._config

    @property
    def stream_name(self) -> str:
        return self._config.name

    async def put(self, item: AnyDict) -> None:
        stream_item = StreamItem(content=self.serialize(item))
        logger.debug("Adding item to stream '%s': %s", self.stream_name, stream_item)
        await self._connection.xadd(name=self._config.name, fields=stream_item)

    async def acknowledge_items_with_too_many_attempts(self, pending, count: int) -> None:
        """Send acknowledge event to those items that have been failed to be processed for a large number of attempts.

        Args:
            pending (_type_): the response of the xpending call
            count (int): number of samples to read from the stream
        """
        if self._config.autoclaim_n_retries is None:
            return

        pending_range = await self._connection.xpending_range(
            name=self._config.name,
            groupname=self._config.consumer_group,
            min=pending["min"],
            max=pending["max"],
            count=count,
        )
        for item in pending_range:
            if item["times_delivered"] > self._config.autoclaim_n_retries:
                logger.warning(
                    "Message '%s' failed to be delivered: number of attempts: %d (allowed %d)",
                    item["message_id"],
                    item["times_delivered"],
                    self._config.autoclaim_n_retries,
                )
                if self._retry_limit_reached_callback is not None:
                    items = await self._connection.xautoclaim(
                        name=self._config.name,
                        groupname=self._config.consumer_group,
                        consumername=self._config.consumer_name,
                        min_idle_time=self._config.autoclaim_min_idle_time,
                        start_id=item["message_id"],
                        count=1,
                    )
                    await self._retry_limit_reached_callback(
                        [self.deserialize(item[1][b"content"]) for item in items[1]]
                    )
                await self._connection.xack(self._config.name, self._config.consumer_group, item["message_id"])

    @asynccontextmanager
    async def consume(self, count: int = 1) -> AsyncIterator[List[AnyDict]]:
        pending = await self._connection.xpending(name=self._config.name, groupname=self._config.consumer_group)
        items: Tuple[Tuple[str, List[Tuple[str, StreamItem]]]] = [(None, [])]
        if pending["pending"] > 0:
            if self._config.autoclaim_n_retries is not None:
                await self.acknowledge_items_with_too_many_attempts(pending=pending, count=count)

            items = [
                await self._connection.xautoclaim(
                    name=self._config.name,
                    groupname=self._config.consumer_group,
                    consumername=self._config.consumer_name,
                    min_idle_time=self._config.autoclaim_min_idle_time,
                    start_id="0-0",
                    count=count,
                )
            ]
            if items:
                logger.debug(
                    "Re-claimed %d items from the stream '%s': %s",
                    len(items[0][1]),
                    self.stream_name,
                    items,
                )

        # if nothing was re-claimed - read data from the stream
        if len(items[0][1]) == 0:
            # read item using group API
            items = await self._connection.xreadgroup(
                groupname=self._config.consumer_group,
                consumername=self._config.consumer_name,
                streams={self._config.name: ">"},
                count=count,
            )
            if items:
                logger.debug(
                    "Read %d items from the stream '%s': %s",
                    len(items[0][1]),
                    self.stream_name,
                    items,
                )
        # check if empty list is return - yield directly
        if len(items) == 0:
            yield []
        else:
            # return all items in the list
            yield [self.deserialize(item[1][b"content"]) for item in items[0][1]]
            # acknowledge receiving and processing of items
            await self._connection.xack(
                self._config.name,
                self._config.consumer_group,
                *[item[0] for item in items[0][1]],
            )

    async def reset_stream(self) -> None:
        response = await self._connection.delete(self._config.name)
        if response:
            logger.info("Stream '%s' is removed", self._config.name)
        else:
            logger.warning("Error removing Stream '%s'", self._config.name)

    async def get_groups(self) -> List[Dict[str, str]]:
        try:
            return await self._connection.xinfo_groups(self._config.name)
        except ResponseError as exc:
            raise StreamUnavailable(self._config.name) from exc

    async def stream_available(self) -> bool:
        try:
            await self.get_groups()
            return True
        except StreamUnavailable:
            return False

    async def connect_consumer(self) -> None:
        try:
            response = await self._connection.xgroup_create(
                self._config.name, self._config.consumer_group, id="0", mkstream=True
            )
            if response:
                logger.info(
                    "Consumer group '%s' is created for stream '%s'",
                    self._config.consumer_group,
                    self._config.name,
                )
            else:
                logger.warning(
                    "Consumer group '%s' is not created for stream '%s'",
                    self._config.consumer_group,
                    self._config.name,
                )
        except ResponseError:
            logger.info(
                "Consumer group '%s' already exists in stream '%s'",
                self._config.consumer_group,
                self._config.name,
            )

    async def stream_length(self) -> Coroutine[None, None, int]:
        return (await self._connection.xinfo_stream(self._config.name))["length"]

    @staticmethod
    def sort_redis_ids(id_list: List[bytes], reverse: bool = False) -> List[bytes]:
        """Sort redis IDs. [Redis ID](https://redis.io/docs/latest/develop/data-types/streams/#entry-ids)
        consist of two parts: milliseconds and sequenceNumber. So sorting Redis IDs correctly will require
        first sorting by the first and then by the second one.

        Args:
            id_list (List[bytes]): List of Redis Stream IDs.
            reverse (bool, optional): if ``True`` sorting in descending order will be used. Defaults to ``False``.

        Returns:
            List[bytes]: List of sorted Redis stream IDs.
        """
        split_id_list = [{"id": _id, "processed": [int(el) for el in _id.decode().split("-")]} for _id in id_list]
        sorted_id_dict = sorted(
            split_id_list,
            key=lambda x: (x["processed"][0], x["processed"][1]),
            reverse=reverse,
        )
        return [_id["id"] for _id in sorted_id_dict]

    async def get_max_processed_id(self) -> Optional[bytes]:
        """Retrieve the maximum ID that has already been processed by all the groups.

        Returns:
            Optional[bytes]: Redis stream ID or None, if no groups have been added to stream yet.
        """
        groups = await self.get_groups()
        if len(groups) > 0:
            min_ids: List[str] = []
            for g in groups:
                min_pending = (await self._connection.xpending(name=self._config.name, groupname=g["name"]))["min"]
                if min_pending is not None:
                    min_ids.append(min_pending)
                else:
                    min_ids.append(g["last-delivered-id"])

            # get the first element from the sorted list
            min_str: bytes = self.sort_redis_ids(min_ids)[0]
            return min_str
        return None

    async def get_all_unprocessed_items_length(self) -> Optional[Dict[str, int]]:
        """For each consumer group in a stream - get the number of items that are
        not yet processed. This is a sum of pending and lag items.

        Returns:
            Optional[Dict[str, int]]: Mapping between the group name and number of items that need processing
        """
        groups = await self.get_groups()
        if len(groups) > 0:
            group_items_count: Dict[str, int] = {}
            for g in groups:
                group_name: bytes = g["name"]
                n_pending = int(g["pending"]) if g["pending"] is not None else 0
                n_lag = int(g["lag"]) if g["lag"] is not None else 0
                group_items_count[group_name.decode()] = n_pending + n_lag
            return group_items_count
        return None

    async def get_unprocessed_items_length(self) -> Optional[int]:
        """Get the number of items that are not yet processed by a given consumer group.
        This is a sum of pending and lag items.

        Returns:
            Optional[int]: number of items that have not yet been processed.
        """
        if self._config.consumer_group is None:
            return None

        all_groups_info = await self.get_all_unprocessed_items_length()
        if all_groups_info is None:
            return None
        return all_groups_info.get(self.config.consumer_group, -1)

    async def trim_tail(self) -> None:
        """Clear those items that have already been processed by all the groups."""
        max_processed_id = await self.get_max_processed_id()
        if max_processed_id is None:
            return

        await self.check_stream_corruption()

        await self._connection.xtrim(
            name=self._config.name,
            minid=max_processed_id,
            approximate=self._config.approximate_tail_trim,
        )

    async def check_stream_corruption(self) -> None:
        """In rare cases it could happen that some items from the stream are remove before being processed. This could lead to a discrepancy between the actual number of assets reported in the stream and the number of unprocessed items reported. This function addresses this issue with a possibility of raising an exception when such situations occur.

        Raises:
            StreamCorruptionError: in case ``raise_on_stream_corruption`` is enabled and number of unprocessed items is larger than the stream length.
        """
        unprocessed_assets = max((await self.get_all_unprocessed_items_length()).values())
        stream_length = await self.stream_length()

        if stream_length >= unprocessed_assets:
            return

        if self.config.raise_on_stream_corruption:
            raise StreamCorruptionError(
                f"Stream corruption: stream length ({stream_length}); unprocessed assets length ({unprocessed_assets})"
            )
        else:
            logger.warning(
                "Stream corruption: stream length (%d); unprocessed assets length (%d)",
                stream_length,
                unprocessed_assets,
            )

    async def total_read(self) -> Dict[str, int]:
        """Total number of items that have been read from the stream per
            consumer group

        Returns:
            Dict[str, int]: Mapping between the consumer group name and the
                number of items that was read from the stream
        """
        groups = await self.get_groups()
        return {
            group["name"]: (group["entries-read"] if group.get("entries-read") is not None else 0) for group in groups
        }

    async def total_processed(self) -> Dict[str, int]:
        """Total number of items that have been read and successfully
            processed per consumer group

        Returns:
            Dict[str, int]: Mapping between a consumer group name and the
                number of items that was read from the stream and successfully
                processed
        """
        total_read = await self.total_read()
        return {
            key: value - (await self._connection.xpending(name=self._config.name, groupname=key))["pending"]
            for key, value in total_read.items()
        }

    async def get_group_statistics(self, group_name: str) -> StreamGroupStatistics:
        """Get read/processed statistics for a stream group

        Args:
            group_name (str): stream group name

        Returns:
            StreamGroupStatistics: stream group statistics
        """
        return StreamGroupStatistics(
            read=(await self.total_read())[group_name.encode()],
            processed=(await self.total_processed())[group_name.encode()],
        )
