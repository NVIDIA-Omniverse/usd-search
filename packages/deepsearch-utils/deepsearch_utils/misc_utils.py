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

from typing import List

import numpy as np
from numpy.typing import NDArray
from PIL import Image


def strip_alpha_channel(input_array: NDArray[np.float32]) -> NDArray[np.float32]:
    """Remove alpha channel from the input array

    Args:
        input_array (NDArray[np.float32]): Assumes that the channel dimension is the last one

    Returns:
        NDArray[np.float32]: resulting array with alpha channel stripped
    """
    return input_array[..., :3]


def get_pillow_supported_formats() -> List[str]:
    """Retrieve a list of file formats supported by Pillow.

    Returns:
        List[str]: list of supported formats
    """
    exts = Image.registered_extensions()
    return [ex.lstrip(".") for ex, f in exts.items() if f in Image.OPEN]


def lstrip(input_str: str, pattern: str, exact: bool = False) -> str:
    """Slightly modified version of lstrip that allows removing exact instead of individual symbols.

    Args:
        input_str (str): input string.
        pattern (str): pattern that need to be removed.
        exact (bool, optional): if ``True`` instead of removing symbols removes the exact match. Otherwise works as standard :py:func:`lstrip`. Defaults to False.

    Returns:
        str: resulting string
    """
    if not exact:
        input_str = input_str.lstrip(pattern)
    elif input_str.startswith(pattern):
        input_str = input_str[len(pattern) :]

    return input_str


def remove_omni_prefix(input: str) -> str:
    """Remove omniverse prefix from the path.

    Args:
        input (str): input string

    Returns:
        str: output string after removal.
    """
    return lstrip(input, "omni:", exact=True)
