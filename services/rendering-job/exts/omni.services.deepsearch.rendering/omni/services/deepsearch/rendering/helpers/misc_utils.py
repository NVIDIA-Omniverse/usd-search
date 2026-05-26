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

import bz2
import os

# standard modules
import pickle
import sys
import zlib
from typing import Any, Callable, Optional, Tuple

from . import logger

# local/ proprietary modules
from .log_utils import prepare_message, print_wrapper

compression_type = os.getenv("RENDERING_SERVICE_COMPRESSION", "None").lower()


def rgba_to_int(r: int, g: int, b: int, a: int) -> int:
    return (a & 0xFF) << 24 | (b & 0xFF) << 16 | (g & 0xFF) << 8 | (r & 0xFF)


def get_size(input: Any) -> str:
    # get size of input
    input_sz = float(sys.getsizeof(input))
    # bytes
    if input_sz < 1024:
        return f"{input_sz:.01f} B"

    # killobytes
    input_sz /= 1024
    if input_sz < 1024:
        return f"{input_sz:.01f} kB"

    # megabytes
    input_sz /= 1024
    if input_sz < 1024:
        return f"{input_sz:.01f} MB"

    # gigabytes
    input_sz /= 1024
    return f"{input_sz:.01f} GB"


def get_compression_method(input: str) -> Optional[Tuple[Callable, Callable]]:
    if input == "none":
        return None
    elif input == "zlib":
        return lambda x: zlib.compress(x, level=9), zlib.decompress
    elif input == "bz2":
        return lambda x: bz2.compress(x, compresslevel=9), bz2.decompress
    else:
        raise NotImplementedError(f"compression method: {input} is not supported")


def pickle_data(input, compress: bool = True, compression_type: str = compression_type) -> str:
    """Serialize numpy data using :func:`pickle.dumps` functionality"""
    serialized = pickle.dumps(input)
    if compress and compression_type != "none":
        with print_wrapper("compressing", logger=logger.debug):
            compression_functionality = get_compression_method(compression_type)

            if compression_functionality is None:
                return serialized.decode("latin1")

            compression_method_impl, _ = compression_functionality
            compressed = compression_method_impl(serialized)
        prepare_message(
            item_list=[
                f"serialized: {sys.getsizeof(serialized) / 1024 / 1024:.02f} Mb",
                f"compressed: {sys.getsizeof(compressed) / 1024 / 1024:.02f} Mb",
            ],
            logger=logger.debug,
        )
        return compressed.decode("latin1")
    else:
        return serialized.decode("latin1")


def unpickle_data(input, compress: bool = True, compression_type: str = compression_type) -> str:
    """Deserialize numpy data using :func:`pickle.dumps` functionality"""
    input = input.encode("latin1")
    try:
        if compress and compression_type != "none":
            with print_wrapper("decompressing", logger=logger.debug):
                compression_functionality = get_compression_method(compression_type)
                if compression_functionality is not None:
                    _, decompress = compression_functionality
                    input = decompress(input)
        return pickle.loads(input)
    except Exception as e:
        logger.warn(f"Decompression error: {str(e)}, trying without compression [deprecated]")
        return pickle.loads(input)


def str2bool(s: Any) -> bool:
    """Convert input string to bool"""
    if isinstance(s, str):
        return s.lower() in ("true", "1")
    else:
        return s
