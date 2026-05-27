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

from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from enum import Enum
from typing import AsyncIterator, Dict, List, TypedDict, Union

import orjson
from pydantic_settings.main import BaseSettings


class StreamGroupStatistics(TypedDict):
    read: int
    processed: int


class StreamUnavailable(ValueError):
    pass


class AvailableStreamTypes(str, Enum):
    redis = "redis"


class StreamConfig(BaseSettings):
    stream_type: AvailableStreamTypes = AvailableStreamTypes.redis


class StreamItem(TypedDict):
    content: Union[str, bytes]


class AnyDict(TypedDict): ...


class StreamWorker(ABC):
    @abstractmethod
    async def put(self, item: AnyDict) -> None: ...

    def serialize(self, item: AnyDict) -> bytes:
        return orjson.dumps(item)

    def deserialize(self, item: bytes) -> AnyDict:
        return orjson.loads(item)

    @abstractmethod
    @asynccontextmanager
    async def consume(self, count: int = 1) -> AsyncIterator[List[AnyDict]]:
        yield [AnyDict()]

    @abstractmethod
    async def reset_stream(self) -> None: ...

    @abstractmethod
    async def stream_available(self) -> bool: ...

    @abstractmethod
    async def get_groups(self) -> List[Dict[str, str]]: ...

    @abstractmethod
    async def connect_consumer(self) -> None: ...

    @abstractmethod
    async def stream_length(self) -> int: ...

    @abstractmethod
    async def trim_tail(self) -> None:
        """Clear those items that have already been processed."""

    @abstractmethod
    async def total_read(self) -> Dict[str, int]: ...

    @abstractmethod
    async def total_processed(self) -> Dict[str, int]: ...

    @abstractmethod
    async def get_group_statistics(self, group_name: str) -> StreamGroupStatistics: ...
