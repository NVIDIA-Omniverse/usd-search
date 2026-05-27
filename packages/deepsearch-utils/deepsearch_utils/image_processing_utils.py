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

import os
from io import BytesIO
from tempfile import TemporaryDirectory
from typing import List, Literal, Optional, Union

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from pytinyexr import PyEXRImage

from .misc_utils import get_pillow_supported_formats

PILLOW_FORMATS = get_pillow_supported_formats()
EXR_FLOAT_TYPE = os.getenv("EXR_FLOAT_TYPE", "float16")


def get_exr_float_type():
    if EXR_FLOAT_TYPE.lower() == "float16":
        return np.float16
    if EXR_FLOAT_TYPE.lower() == "float32":
        return np.float32

    raise ValueError("EXR float type is unsupported")


def load_exr_image(path: str) -> NDArray[Union[np.float32, np.float16]]:
    img = PyEXRImage(path)
    return np.reshape(np.array(img, dtype=get_exr_float_type()), (img.height, img.width, 4))


def load_exr_image_from_bytes(content: bytearray):
    with TemporaryDirectory() as tmp_dir:
        with open(f"{tmp_dir}/exr_content.exr", "wb") as f:
            f.write(content)
        return load_exr_image(f"{tmp_dir}/exr_content.exr")


def gamma_correction(image: NDArray[np.float32], gamma: float = 0.45) -> Image.Image:
    im_gamma_correct = np.clip(np.power(np.clip(image, 0, None), gamma), 0, 1)
    return Image.fromarray(np.uint8(im_gamma_correct * 255))


def load_image_from_bytes_by_type(
    content: bytearray,
    file_format: str,
    exr_gamma_correction: bool = True,
    downsize: Optional[int] = None,
    offset_ms: int = 1000,
) -> List[Image.Image]:
    """Load image from bytes

    Args:
        content (bytearray): image content
        file_format (str): file format
        exr_gamma_correction (bool, optional): Optional Gamma correction . Defaults to True.
        downsize (Optional[int], optional): size to which image needs to be down-sampled if not None. If the image has smaller size - it would be kept unchanged. Defaults to None.
        offset_ms (int, optional): offset in milliseconds for GIF. Defaults to 1000.

    Raises:
        NotImplementedError: _description_

    Returns:
        Image.Image: _description_
    """
    file_format = file_format.lstrip(".").lower()
    if file_format == "gif":
        return [
            downsize_keep_aspect(im, sz=downsize).convert("RGBA")
            for im in load_gif_as_multiple_images(content=content, offset_ms=offset_ms)
        ]
    elif file_format in PILLOW_FORMATS:
        with BytesIO(content) as stream:
            return [downsize_keep_aspect(Image.open(stream).convert("RGBA"), sz=downsize)]
    elif file_format == "exr":
        img = load_exr_image_from_bytes(content=content)
        if not exr_gamma_correction:
            return [downsize_keep_aspect(img, sz=downsize)]
        return [downsize_keep_aspect(gamma_correction(image=img), sz=downsize)]
    else:
        raise NotImplementedError(f"{format} is not supported")


def load_gif_as_multiple_images(content: bytearray, offset_ms: int = 1000) -> List[Image.Image]:
    """Load GIF as multiple images
    Args:
        content (bytearray): GIF content
        offset_ms (int): offset in milliseconds
    Returns:
        List[Image.Image]: List of images
    """

    with TemporaryDirectory() as tmp_dir:
        tmp_file_path = os.path.join(tmp_dir, "thumbnail.gif")

        with open(tmp_file_path, "wb") as f:
            f.write(content)

        im = Image.open(tmp_file_path)

        frames: List[Image.Image] = []
        elapsed = 0  # ms from start of GIF
        next_target = offset_ms  # next second mark in ms

        for frame_index in range(im.n_frames):
            im.seek(frame_index)

            # Some GIFs store duration in various places
            duration = im.info.get("duration", 0)  # ms

            # If we've crossed a 1-second boundary, save this frame
            if elapsed >= next_target:
                frames.append(im.copy())
                # move to next second mark
                next_target += offset_ms

            elapsed += duration

    return frames


def downsize_keep_aspect(
    img: Image.Image,
    sz: Optional[int] = None,
    resampling_method: Literal = Image.Resampling.LANCZOS,
) -> Image.Image:
    if sz is None:
        return img

    aspect = max(img.size) / min(img.size)
    target_sz = aspect * sz
    if max(img.size) > target_sz:
        img.thumbnail((target_sz, target_sz), resample=resampling_method)
    return img


def center_crop(img: Image.Image) -> Image.Image:
    """Center crop of the PIL image"""

    w, h = img.size
    nh = nw = min(w, h)
    # compute crop cornres
    left = int(np.ceil((w - nw) / 2))
    right = w - int(np.floor((w - nw) / 2))
    top = int(np.ceil((h - nh) / 2))
    bottom = h - int(np.floor((h - nh) / 2))
    # crop the image
    return img.crop((left, top, right, bottom))
