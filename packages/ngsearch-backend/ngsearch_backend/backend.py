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

import base64

# standard modules
import io
from typing import Optional, Tuple

# third party modules
from PIL import Image

from .utils import strip_alpha_channel


def to_base64(input: str) -> str:
    return base64.b64encode(input).decode("ascii")


def get_byte_im(im, im_size: Optional[Tuple[int, int]] = None) -> bytes:
    """Convert numpy image into bytes"""
    img = Image.fromarray(strip_alpha_channel(im))
    if im_size is not None and isinstance(im_size, tuple):
        img = img.resize(im_size)
    output = io.BytesIO()
    img.save(output, format="JPEG")
    return output.getvalue()


class EmbedBackend:
    def __init__(self, *args, **kwargs):
        pass

    def search(self, query_feats, N: int):
        raise NotImplementedError("Using functionality of the base class")

    def __len__(self):
        raise NotImplementedError("Using functionality of the base class")
