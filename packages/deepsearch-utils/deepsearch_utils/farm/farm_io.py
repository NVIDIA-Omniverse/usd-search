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
import base64
import io
import os
import struct
from typing import Any, List

import numpy as np
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

# Wire format for a rendered payload, as written by rendering-job's
# serialize_payload() (services/rendering-job/deepsearch_rendering_job/utils.py,
# since the ovrtx renderer migration): a magic header, a little-endian uint32
# length, an orjson metadata block, then a compressed .npz array block, all
# base64-encoded. Duplicated here (rather than importing from the rendering-job
# package) since that package pulls in GPU/ovrtx dependencies this image
# doesn't otherwise need - keep this in sync with serialize_payload's format
# if it ever changes.
_PAYLOAD_MAGIC = b"DSRP1\0"


def _flatten_images(images: List[Any]) -> List[Any]:
    flat: List[Any] = []
    for item in images:
        if isinstance(item, list):
            flat.extend(_flatten_images(item))
        else:
            flat.append(item)
    return flat


def _normalize_images(images: Any) -> Any:
    if isinstance(images, np.ndarray):
        return images
    if not isinstance(images, list):
        return images

    flat = _flatten_images(images)
    if not flat:
        return np.empty((0, 0, 0, 0), dtype=np.uint8)

    arrays = [np.asarray(im) for im in flat if im is not None]
    if not arrays:
        return np.empty((0, 0, 0, 0), dtype=np.uint8)

    if any(arr.ndim == 4 for arr in arrays):
        normalized = []
        for arr in arrays:
            if arr.ndim == 4:
                normalized.append(arr)
            elif arr.ndim == 3:
                normalized.append(arr[None, ...])
            else:
                normalized.append(np.asarray(arr))
        return np.concatenate(normalized, axis=0)

    return np.stack(arrays, axis=0)


def _deserialize_rendered_payload(content: str) -> Any:
    """Decode a rendered payload produced by rendering-job's serialize_payload()."""
    frame = base64.b64decode(content.encode("ascii"))
    if not frame.startswith(_PAYLOAD_MAGIC):
        raise ValueError("Unrecognized rendered payload format")

    offset = len(_PAYLOAD_MAGIC)
    (meta_len,) = struct.unpack_from("<I", frame, offset)
    offset += struct.calcsize("<I")
    header = orjson.loads(frame[offset : offset + meta_len])
    array_bytes = frame[offset + meta_len :]

    with np.load(io.BytesIO(array_bytes), allow_pickle=False) as npz:
        arrays = {key: npz[key] for key in npz.files}

    meta = header["meta"]
    data = {key: (arrays[key] if key in arrays else meta[key]) for key in header["order"]}
    if isinstance(data, dict) and "images" in data:
        data["images"] = _normalize_images(data["images"])
    return data


def deserialize(content: str) -> Any:
    for r in ServerResponses:
        if content == r.value:
            return r.value

    if content.startswith("Error rendering:"):
        farm_utils_logger.warning("Error rendering: %s", str(content))
        return ServerResponses.rendering_error.value

    try:
        return _deserialize_rendered_payload(content)
    except Exception:
        pass

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
