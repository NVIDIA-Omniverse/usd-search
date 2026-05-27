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
import os
from typing import Any

import orjson

# local / proprietary modules
from deepsearch_utils import secure_pickle

from search_utils.cache_utils.redis_async import AsyncCacheRedis
from search_utils.log_utils import print_wrapper
from search_utils.misc_utils import compress_data, decompress_data

from . import farm_utils_logger
from .data import (
    DEBUG_SAVE_FARM_DATA,
    DEBUG_SAVE_FARM_DATA_FOLDER,
    FarmResponse,
    FarmResultContent,
    ServerResponses,
)


def deserialize(content: str) -> Any:
    for r in ServerResponses:
        if content == r.value:
            return r.value

    if content.startswith("Error rendering:"):
        farm_utils_logger.warning("Error rendering: %s", str(content))
        return ServerResponses.rendering_error.value

    try:
        return decompress_data(content, compression_type="zlib")
    except Exception as e:
        farm_utils_logger.warning("deserialization error: %s for content: %s", str(e), str(content))
        raise ValueError(f"deserialization error: {str(e)}") from e


def serialize(content: Any) -> str:
    return compress_data(content, compression_type="zlib")


async def write_content(jresp: FarmResponse, cache: AsyncCacheRedis, deserialize_content: bool = True):
    with print_wrapper("Writing data:", logger=farm_utils_logger.debug, print_after=False):

        # load data
        if jresp["request"] == "result":
            # deserialize data on demand
            payload: FarmResultContent = jresp["payload"]
            if deserialize_content:
                content = deserialize(payload["content"])
            else:
                content = payload["content"]
            # store data in cache
            if DEBUG_SAVE_FARM_DATA:
                os.makedirs(DEBUG_SAVE_FARM_DATA_FOLDER, exist_ok=True)
                with open(
                    f"{DEBUG_SAVE_FARM_DATA_FOLDER}/{os.path.basename(payload['path'])}.pkl",
                    "wb",
                ) as pkl_file:
                    secure_pickle.dump(dict(content=content, path=payload["path"]), pkl_file)
            await cache.set(payload["path"], content)
            farm_utils_logger.info("%s received", payload["path"])
        else:
            farm_utils_logger.info("%s non-result status", jresp)


async def writer(resp, cache: AsyncCacheRedis):
    with print_wrapper("data loading:", logger=farm_utils_logger.debug, print_after=False):
        # load data
        jresp = orjson.loads(resp)
    # write content
    await write_content(jresp, cache)
