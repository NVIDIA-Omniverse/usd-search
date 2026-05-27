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
import os
import time

# standard modules
from contextlib import contextmanager

# local / proprietary modules
from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Dict, Generator, List, Optional, TypedDict, TypeVar

import opentelemetry.trace as trace
import orjson
from typing_extensions import NotRequired

from search_utils.cache_utils.base import CacheDict
from search_utils.log_utils import set_simple_logger, set_telemetry_logger
from search_utils.misc_utils import str2bool

USE_SEARCH_TELEMETRY = str2bool(os.getenv("USE_SEARCH_TELEMETRY", "False"))
SEARCH_TELEMETRY_STDOUT = str2bool(os.getenv("SEARCH_TELEMETRY_STDOUT", "False"))
SEARCH_TELEMETRY_DIR = os.getenv("SEARCH_TELEMETRY_DIR", "/tmp/deepsearch/telemetry/search")
telemetry_utils_logger = logging.getLogger(__name__)
telemetry_logger = set_telemetry_logger("telemetry")

tracer = trace.get_tracer(__name__)
T = TypeVar("T")


class TelemetryEventTypes(str, Enum):
    query = "query"
    hierarchically_clustered_projections = "hierarchically_clustered_projections"


class EventType(TypedDict):
    event_type: NotRequired[TelemetryEventTypes]
    query: NotRequired[str]
    N_results: NotRequired[List[int]]
    N_results_total: NotRequired[int]
    N_pages: NotRequired[int]
    time_to_present: NotRequired[float]
    time_to_click: NotRequired[float]
    time_total: NotRequired[float]


def get_telemetry_token() -> str:
    return datetime.now().isoformat()


class BaseTelemetry(dict):
    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def add(self, update_dict: Optional[EventType] = None, key: Optional[str] = None) -> None:
        if not self.enabled:
            return

        # if None is provided - initialize with empty dictionaries
        if update_dict is None:
            update_dict = {}

        if key is None:
            key = get_telemetry_token()

        # get existing key
        v = self.get(key, {})
        # update key with new fields (overwrite if needed)
        v.update(**update_dict)
        # update the dictionary with the new keys
        self.update({key: {**v}})

    def append(self, item_key: str, value: EventType, key: Optional[str] = None) -> None:
        if not self.enabled:
            return
        if key is None:
            key = get_telemetry_token()
        v = self.get(key, {})
        item_value = v.get(item_key, [])
        if not isinstance(item_value, list):
            raise ValueError(f"{item_key} in {key} is not a list")
        item_value.append(value)
        self.update({key: {**v, item_key: item_value}})

    @contextmanager
    def time_context(
        self, name: str = "operation", key: Optional[str] = None
    ) -> Generator["BaseTelemetry", None, None]:
        if self.enabled:
            start_time = time.time()
        try:
            yield self
        finally:
            if self.enabled:
                if key is None:
                    key = get_telemetry_token()
                content = EventType()
                content.update({name: time.time() - start_time})
                self.add(content, key=key)


class Telemetry(CacheDict, BaseTelemetry):
    def __init__(self, path: str, enabled: bool = True):
        self.enabled = enabled
        if self.enabled:
            super().__init__(
                path=path,
                serializer=lambda x: orjson.dumps(x).decode("utf-8"),
                deserializer=orjson.loads,
            )

    @contextmanager
    def memory_context(self, use_telemetry: bool = True) -> Generator[BaseTelemetry, None, None]:
        if use_telemetry:
            in_memory_cache = BaseTelemetry()
            try:
                yield in_memory_cache
            finally:
                try:
                    self.update(in_memory_cache)
                    self.flush(in_memory_cache)
                except Exception as exc_info:
                    telemetry_utils_logger.warning("failed writing to telemetry cache DB due to; %s", str(exc_info))
        else:
            yield self

    def flush(self, d: Dict[str, EventType]) -> None:
        pass


class JSONStdoutTelemetry(Telemetry):
    """A telemetry class that outputs events to stdout in a JSON format for collection and further processing"""

    def flush(self, d: Dict[str, EventType]) -> None:
        for key, value in d.items():
            event = self.process_event(value)
            try:
                datetime.fromisoformat(key)
                timestamp = key
            except (ValueError, TypeError):
                timestamp = get_telemetry_token()
            telemetry_logger.info(orjson.dumps({"telemetry_key": key, "time": timestamp, **event}).decode("utf-8"))

    @staticmethod
    def process_event(event: EventType) -> EventType:
        if event.get("event_type") == TelemetryEventTypes.query:
            event["N_results_total"] = sum(event.get("N_results", [0]))
            event["N_pages"] = len(event.get("N_results", []))
        if "time_to_present" in event and "time_to_click" in event:
            event["time_total"] = event["time_to_present"] + event["time_to_click"]
        # Trim query to 256 characters
        query: str = event.get("query", "")
        if query is not None and len(query) > 256:
            event["query"] = query[:256] + "..."
        return event


# search telemetry class
telemetry_class = JSONStdoutTelemetry if SEARCH_TELEMETRY_STDOUT else Telemetry
SearchTelemetry = telemetry_class(path=f"{SEARCH_TELEMETRY_DIR}/search_telemetry.db", enabled=USE_SEARCH_TELEMETRY)


class AsyncIteratorWrapper:
    def __init__(self, iterator: AsyncIterator[T], span_name: str):
        self.generator = iterator
        self.span_name = span_name

    def __aiter__(self) -> "AsyncIteratorWrapper":
        return self

    async def __anext__(self) -> T:
        end = False
        with tracer.start_as_current_span(self.span_name):
            try:
                res = await self.generator.__anext__()
            except StopAsyncIteration:
                end = True
        if end:
            raise StopAsyncIteration
        return res
