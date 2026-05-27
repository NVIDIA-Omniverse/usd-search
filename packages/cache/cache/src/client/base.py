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
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Union

# local/proprietary modules
from .. import JobItem, ResultItem


class CacheClient(ABC):
    @staticmethod
    def job_repr(item: JobItem) -> str:
        return f"{item['uri']}_{item['plugin_name']}"

    @abstractmethod
    async def plugin_update(
        self,
        dest: str,
        content: Dict[Union[str, bytes], bytes],
        ttl_seconds: Optional[int] = None,
    ) -> None: ...

    @abstractmethod
    async def plugin_get(self, dest: str, key: Union[str, bytes]) -> Any: ...

    @abstractmethod
    async def plugin_len(self, dest: str) -> int: ...

    @abstractmethod
    async def plugin_del(self, dest: str, keys: List[Union[str, bytes]]) -> None: ...

    @abstractmethod
    async def plugin_keys(self, dest: str) -> List[str]: ...

    @abstractmethod
    async def plugin_key_exists(self, dest: str, key: Union[str, bytes]) -> bool: ...

    @abstractmethod
    async def plugin_find(self, dest: str, key: Union[str, bytes]) -> List[str]: ...

    @abstractmethod
    async def plugin_clean(self, dest: str) -> None: ...

    @abstractmethod
    async def enqueue_plugin_job(self, plugin_name: str, content: Union[List[JobItem], JobItem]) -> None: ...

    @abstractmethod
    async def enqueue_result(self, content: ResultItem) -> None: ...

    @asynccontextmanager
    @abstractmethod
    async def get_plugin_job(self, plugin_name: str) -> AsyncIterator[List[JobItem]]:
        yield []

    @asynccontextmanager
    @abstractmethod
    async def get_result(self) -> AsyncIterator[List[ResultItem]]:
        yield []

    @abstractmethod
    async def plugin_queue_len(self, plugin_name: str) -> int: ...

    @abstractmethod
    async def result_queue_len(self) -> int: ...

    @abstractmethod
    async def clean_plugin_queue(self, plugin_name: str) -> None: ...

    @abstractmethod
    async def clean_results_queue(self) -> None: ...

    @abstractmethod
    async def plugin_iter_keys(self, dest: str) -> AsyncIterator[str]:
        yield ""
