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

from prometheus_client import Counter
from pydantic import field_validator
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

#: Stream entry field holding the number of failed processing attempts.
ATTEMPTS_FIELD = b"attempts"

#: Entries taken out of a consumer's hands, by ``trigger`` (the consumer raised, or
#: it left the entry unacknowledged long enough to be reclaimed) and ``outcome`` (the
#: entry went back into the queue, or it ran out of attempts and was dropped).
REQUEUED_ITEMS = Counter(
    "omnideepsearch_stream_items_requeued_total",
    "Items acknowledged and re-added to the back of the stream for another attempt",
    labelnames=["stream", "trigger", "outcome"],
)


class StreamCorruptionError(Exception):
    pass


def get_entry_attempts(fields: Dict[bytes, bytes]) -> int:
    """Number of failed processing attempts recorded on a stream entry.

    An entry without a readable counter - one written before the field existed, for
    instance - counts as never having failed.

    Args:
        fields (Dict[bytes, bytes]): fields of a single stream entry.

    Returns:
        int: number of attempts already recorded for the entry.
    """
    try:
        return int(fields.get(ATTEMPTS_FIELD, 0))
    except (TypeError, ValueError):
        logger.warning("Unreadable '%s' field on a stream entry: %s", ATTEMPTS_FIELD, fields.get(ATTEMPTS_FIELD))
        return 0


class RedisStreamConfig(StreamConfig):
    name: str
    consumer_group: Optional[str] = None
    consumer_name: Optional[str] = None
    url: str = "redis://localhost:6379"
    approximate_tail_trim: bool = False
    #: How long an entry may stay unacknowledged before another consumer moves it
    #: back into the queue. This is the recovery path for a consumer that *died*
    #: holding an entry, so it has to exceed the longest a healthy consumer can
    #: legitimately take over one item.
    autoclaim_min_idle_time: int = 60000  # in milliseconds (default: 1 min)
    raise_on_stream_corruption: bool = False
    #: If ``True`` - an entry whose processing raised is acknowledged straight away
    #: and re-added to the back of the stream. Without this a failed entry stays
    #: pending until it has been idle for ``autoclaim_min_idle_time``, and because
    #: the trim point is the oldest pending id it blocks
    #: :meth:`RedisStreamWorker.trim_tail` for the *whole* stream until then.
    requeue_failed_items: bool = True
    #: Number of times an entry may be moved back into the queue - after a failure
    #: or after being reclaimed from a dead consumer - before it is reported through
    #: ``retry_limit_reached_callback`` and dropped from the stream. ``None``, or
    #: ``-1`` for settings that have to travel through an environment variable,
    #: means an entry is retried forever: that never blocks trimming, but it does
    #: keep reprocessing an item that cannot succeed.
    max_attempts: Optional[int] = None
    model_config = SettingsConfigDict(env_prefix="redis_stream_")

    @field_validator("max_attempts", mode="after")
    @classmethod
    def unlimited_attempts_when_negative(cls, value: Optional[int]) -> Optional[int]:
        """Accept a negative budget as "retry forever", which an env var cannot express as ``None``."""
        return None if value is not None and value < 0 else value


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
        stream_item = StreamItem(content=self.serialize(item), attempts=0)
        logger.debug("Adding item to stream '%s': %s", self.stream_name, stream_item)
        await self._connection.xadd(name=self._config.name, fields=stream_item)

    async def requeue_stale_entries(self, count: int) -> None:
        """Move entries left behind by a dead consumer back into the queue.

        An entry unacknowledged for ``autoclaim_min_idle_time`` is claimed and re-added
        at the end of the stream rather than handed to this consumer: a stream entry
        cannot be modified in place, so re-adding it is what carries the attempt counter
        (see :meth:`requeue_entries`) across both ways an item can fail.

        Args:
            count (int): maximum number of entries to reclaim in one call.
        """
        # the response is (next cursor, entries) and, since Redis 7, a third element
        # listing ids that no longer exist - index rather than unpack to support both
        response = await self._connection.xautoclaim(
            name=self._config.name,
            groupname=self._config.consumer_group,
            consumername=self._config.consumer_name,
            min_idle_time=self._config.autoclaim_min_idle_time,
            start_id="0-0",
            count=count,
        )
        entries: List[Tuple[bytes, Dict[bytes, bytes]]] = response[1]
        if len(entries) == 0:
            return

        logger.warning(
            "Re-claimed %d entries of stream '%s' left unacknowledged for over %dms",
            len(entries),
            self.stream_name,
            self._config.autoclaim_min_idle_time,
        )
        await self.requeue_entries(entries, trigger="reclaimed")

    @asynccontextmanager
    async def consume(self, count: int = 1) -> AsyncIterator[List[AnyDict]]:
        pending = await self._connection.xpending(name=self._config.name, groupname=self._config.consumer_group)
        if pending["pending"] > 0:
            # entries abandoned by a dead consumer go back into the queue before
            # anything is read, so that they stop holding back the trim point
            await self.requeue_stale_entries(count=count)

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
            return

        entries: List[Tuple[bytes, Dict[bytes, bytes]]] = items[0][1]
        try:
            # return all items in the list
            yield [self.deserialize(entry[1][b"content"]) for entry in entries]
        except Exception:
            # The consumer failed to process the batch, so it is never acknowledged
            # and stays pending. Pending entries hold back the trim point of the
            # whole stream, so move them to the back of it instead - see
            # :meth:`requeue_entries`.
            if self._config.requeue_failed_items and len(entries) > 0:
                try:
                    await self.requeue_entries(entries, trigger="failed")
                except Exception:
                    # Never mask the failure the consumer is reporting. The entries
                    # stay pending and are requeued by :meth:`requeue_stale_entries`
                    # once they have been idle long enough.
                    logger.exception("Failed to requeue entries of stream '%s'", self.stream_name)
            raise
        # acknowledge receiving and processing of items
        await self._connection.xack(
            self._config.name,
            self._config.consumer_group,
            *[entry[0] for entry in entries],
        )

    async def requeue_entries(self, entries: List[Tuple[bytes, Dict[bytes, bytes]]], trigger: str) -> None:
        """Acknowledge entries and re-add them to the back of the stream for another attempt.

        A pending entry holds back the trim point of the whole stream (see
        :meth:`get_max_processed_id`), so a failing item is moved rather than left in
        place. The attempt counter travels with the entry (:data:`ATTEMPTS_FIELD`),
        which is what lets one ``max_attempts`` budget cover both ways an item can
        fail; past that budget the entry is reported through
        ``retry_limit_reached_callback`` and dropped instead of requeued. Delivery is
        at-least-once, so consumers have to be idempotent.

        Args:
            entries (List[Tuple[bytes, Dict[bytes, bytes]]]): raw stream entries (id and fields) to requeue.
            trigger (str): what put the entry here - ``failed`` (the consumer raised) or ``reclaimed`` (left unacknowledged). Reported as a metric label.
        """
        max_attempts = self._config.max_attempts
        for entry_id, fields in entries:
            attempts = get_entry_attempts(fields) + 1
            content = fields[b"content"]

            if max_attempts is not None and attempts > max_attempts:
                logger.error(
                    "Entry '%s' of stream '%s' has been %s %d times (allowed %d) - dropping it from the stream",
                    entry_id,
                    self.stream_name,
                    trigger,
                    attempts - 1,
                    max_attempts,
                )
                if self._retry_limit_reached_callback is not None:
                    await self._retry_limit_reached_callback([self.deserialize(content)])
                await self._connection.xack(self._config.name, self._config.consumer_group, entry_id)
                REQUEUED_ITEMS.labels(self.stream_name, trigger, "dropped").inc()
                continue

            # Add first, acknowledge second: should the transaction not go through,
            # the item is processed twice rather than lost.
            pipeline = self._connection.pipeline(transaction=True)
            pipeline.xadd(name=self._config.name, fields=StreamItem(content=content, attempts=attempts))
            pipeline.xack(self._config.name, self._config.consumer_group, entry_id)
            await pipeline.execute()

            logger.warning(
                "Entry '%s' of stream '%s' %s - requeued at the back of the stream (attempt %d of %s)",
                entry_id,
                self.stream_name,
                trigger,
                attempts,
                max_attempts if max_attempts is not None else "unlimited",
            )
            REQUEUED_ITEMS.labels(self.stream_name, trigger, "requeued").inc()

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

    async def get_oldest_pending_ages(self) -> Dict[str, float]:
        """For each consumer group - how long its oldest unacknowledged entry has been pending.

        This is the entry that holds back :meth:`trim_tail`; an age that grows past
        ``autoclaim_min_idle_time`` means it is stuck rather than being worked on. It is
        measured against Redis' own clock, not the caller's.

        Returns:
            Dict[str, float]: mapping between the group name and the age, in seconds, of its oldest pending entry (``0`` for a group with nothing pending).
        """
        groups = await self.get_groups()
        if len(groups) == 0:
            return {}

        seconds, microseconds = await self._connection.time()
        now_ms = seconds * 1000 + microseconds // 1000

        ages: Dict[str, float] = {}
        for g in groups:
            group_name: str = g["name"].decode()
            min_pending = (await self._connection.xpending(name=self._config.name, groupname=g["name"]))["min"]
            if min_pending is None:
                ages[group_name] = 0.0
                continue
            entry_ms = int(min_pending.decode().split("-")[0])
            ages[group_name] = max(0.0, (now_ms - entry_ms) / 1000)
        return ages

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
