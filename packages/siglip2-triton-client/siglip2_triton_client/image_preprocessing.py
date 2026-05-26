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
from typing import Union

# third party modules
import numpy as np
from numpy.typing import NDArray
from PIL import Image
from transformers import SiglipImageProcessor


class ImagePreprocessor:
    def __init__(
        self,
        size: tuple[int, int] = (384, 384),
        image_mean: list[float] | None = None,
        image_std: list[float] | None = None,
        rescale_factor: float = 1.0 / 255.0,
        resample: int = 2,
    ):
        self.processor = SiglipImageProcessor(
            size={"height": size[0], "width": size[1]},
            image_mean=image_mean or [0.5, 0.5, 0.5],
            image_std=image_std or [0.5, 0.5, 0.5],
            rescale_factor=rescale_factor,
            resample=resample,
            do_resize=True,
            do_rescale=True,
            do_normalize=True,
        )

    def __call__(
        self,
        images: Union[
            Image.Image,
            list[Image.Image],
            "NDArray[np.uint8]",
            list["NDArray[np.uint8]"],
        ],
    ) -> NDArray[np.float32]:
        processed = self.processor(images=images, return_tensors="np")
        return processed["pixel_values"]

    def batch_iter(
        self,
        images: Union[list[Image.Image], list["NDArray[np.uint8]"]],
        batch_size: int = 32,
    ):
        for start in range(0, len(images), batch_size):
            batch = images[start : start + batch_size]
            yield self(batch)
