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
from logging import LogRecord
from pathlib import Path
from time import time
from typing import (
    Any,
    AsyncIterator,
    Coroutine,
    Dict,
    Iterable,
    Iterator,
    List,
    TypeVar,
)

import numpy as np
from asset_graph_service_client.api_client import ApiClient
from numpy.typing import NDArray
from PIL import Image


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Exclude healthchecks from access logs
        return record.getMessage().find("/health") == -1 and record.getMessage().find("/metrics") == -1


class GRPCCommonFilter(logging.Filter):
    def filter(self, record: LogRecord) -> bool:
        # TODO: find a better way to filter out these exceptions from GRPC (possibly a GPRC version upgrade may help)
        return record.getMessage().find("Exception serializing message!") == -1


class OTELDisabledWarningFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("SDK is disabled.") == -1


def get_api_description() -> str:
    with open(f"{Path(__file__).parent}/README.md", "r", encoding="utf-8") as file:
        return file.read()


def center_crop(img: Image.Image) -> Image.Image:
    """Center crop of the PIL image"""

    w, h = img.size
    nh = nw = min(w, h)
    # compute crop corners
    left = int(np.ceil((w - nw) / 2))
    right = w - int(np.floor((w - nw) / 2))
    top = int(np.ceil((h - nh) / 2))
    bottom = h - int(np.floor((h - nh) / 2))
    # crop the image
    return img.crop((left, top, right, bottom))


def img_paths2numpy_array(img_paths: List[str], size: int = 224) -> NDArray[np.uint8]:
    inputs: List[NDArray[np.uint8]] = []
    for img_path in img_paths:
        image = Image.open(img_path)
        cropped_im = center_crop(image).resize((size, size))
        inputs.append(np.asarray(cropped_im, dtype=np.uint8))
    return np.stack(inputs)


def byte_str2numpy_array(byte_str: str, dtype: type = np.float32, shape: List[int] = [-1, 1536]) -> NDArray[np.float32]:
    arr = byte_str.encode("latin1")
    np_arr: NDArray[np.float32] = np.frombuffer(arr, dtype=dtype)
    np_arr.shape = tuple(shape)
    return np_arr


def numpy_array2byte_str(arr: NDArray[np.float32]) -> str:
    return arr.tobytes().decode("latin1")


T = TypeVar("T")


async def batch_worker(tasks: Iterable[Coroutine[Any, Any, T]], n_workers: int) -> List[T]:
    """Process async tasks in parallel using n_workers"""
    tasks_iterator = iter(tasks)

    async def _worker() -> List[Any]:
        results = []
        for task in tasks_iterator:
            results.append(await task)
        return results

    results_batches = await asyncio.gather(*[_worker() for i in range(n_workers)])
    return [result for batch in results_batches for result in batch]


class DurationLogger:
    def __init__(self, name: str, logger: logging.Logger, level: str) -> None:
        self.name = name
        self.logger = logger
        self.level_numeric: int = getattr(logging, level.upper(), "INFO")
        self.start = 0.0

    def __enter__(self) -> Iterator[None]:
        self.start = time()

    def __exit__(self, _type, value, traceback) -> None:
        elapsed_time = time() - self.start
        self.logger.log(self.level_numeric, "%s executed in %s seconds", self.name, elapsed_time)


class AsyncPoolExecutor:
    def __init__(self, num_workers: int):
        self.num_workers = num_workers
        self.semaphore = asyncio.Semaphore(num_workers)

    async def _worker(self, func: Coroutine) -> Any:
        async with self.semaphore:
            return await func

    async def run_tasks(self, tasks: List[Coroutine]) -> tuple[Any]:
        wrapped_tasks = [self._worker(task) for task in tasks]
        return await asyncio.gather(*wrapped_tasks)


@asynccontextmanager
async def ags_client_with_headers(client: ApiClient, headers: Dict[str, str]) -> AsyncIterator[ApiClient]:
    _client = ApiClient(configuration=client.configuration)
    for header_name, header_value in headers.items():
        _client.set_default_header(header_name=header_name, header_value=header_value)

    async with _client:
        yield _client
