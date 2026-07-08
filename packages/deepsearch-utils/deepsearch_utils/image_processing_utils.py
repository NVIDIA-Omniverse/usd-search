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
from enum import Enum
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


class GifSamplingMode(str, Enum):
    """GIF frame sampling strategy.

    ``FIXED`` strides by ``frame_sample_frequency`` and caps at ``max_frames``;
    ``UNIFORM`` spreads up to ``max_frames`` frames evenly across the whole GIF.
    """

    FIXED = "fixed"
    UNIFORM = "uniform"


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
    gif_frame_sample_frequency: int = 1,
    gif_max_frames: int = 512,
    gif_sampling_mode: GifSamplingMode = GifSamplingMode.FIXED,
) -> List[Image.Image]:
    """Load image from bytes

    Args:
        content (bytearray): image content
        file_format (str): file format
        exr_gamma_correction (bool, optional): Optional Gamma correction . Defaults to True.
        downsize (Optional[int], optional): size to which image needs to be down-sampled if not None. If the image has smaller size - it would be kept unchanged. Defaults to None.
        gif_frame_sample_frequency (int, optional): for GIFs in "fixed" mode, sample every Nth frame (1 = every frame). Defaults to 1.
        gif_max_frames (int, optional): for GIFs, cap on the total number of extracted frames. Defaults to 512.
        gif_sampling_mode (GifSamplingMode, optional): GIF frame sampling strategy. Defaults to GifSamplingMode.FIXED.

    Raises:
        NotImplementedError: _description_

    Returns:
        Image.Image: _description_
    """
    file_format = file_format.lstrip(".").lower()
    if file_format == "gif":
        return [
            downsize_keep_aspect(im, sz=downsize).convert("RGBA")
            for im in load_gif_as_multiple_images(
                content=content,
                frame_sample_frequency=gif_frame_sample_frequency,
                max_frames=gif_max_frames,
                sampling_mode=gif_sampling_mode,
            )
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


def _fixed_sampling_indices(n_frames: int, frame_sample_frequency: int, max_frames: int) -> List[int]:
    """Stride-based sampling: every Nth frame, capped at max_frames."""
    indices: List[int] = []
    for frame_index in range(0, n_frames, frame_sample_frequency):
        if len(indices) >= max_frames:
            break
        indices.append(frame_index)
    return indices


def _uniform_sampling_indices(n_frames: int, max_frames: int) -> List[int]:
    """Uniform sampling: up to max_frames frames spread evenly across the GIF.

    Uses even buckets ``(arange(k) * n) // k`` with ``k = min(max_frames,
    n_frames)``. Since ``n_frames / k >= 1`` the indices are strictly
    increasing, so when ``n_frames <= max_frames`` every frame is returned.
    """
    k = min(max_frames, n_frames)
    return ((np.arange(k) * n_frames) // k).tolist()


def load_gif_as_multiple_images(
    content: bytearray,
    frame_sample_frequency: int = 1,
    max_frames: int = 512,
    sampling_mode: GifSamplingMode = GifSamplingMode.FIXED,
) -> List[Image.Image]:
    """Load GIF as multiple images using the requested sampling strategy.

    Args:
        content (bytearray): GIF content
        frame_sample_frequency (int): for ``FIXED`` mode, sample every Nth frame
            (1 = every frame). Ignored in ``UNIFORM`` mode.
        max_frames (int): cap on the total number of extracted frames. In
            ``UNIFORM`` mode this is the target number of evenly-spaced frames.
        sampling_mode (GifSamplingMode): ``FIXED`` strides by
            ``frame_sample_frequency`` and caps at ``max_frames``; ``UNIFORM``
            spreads up to ``max_frames`` frames evenly across the whole GIF.
    Returns:
        List[Image.Image]: List of images
    """
    if max_frames < 1:
        raise ValueError("max_frames must be >= 1")
    try:
        sampling_mode = GifSamplingMode(sampling_mode)
    except ValueError:
        raise ValueError(
            f"Unknown sampling_mode: {sampling_mode!r} (expected one of {[m.value for m in GifSamplingMode]})"
        ) from None

    with TemporaryDirectory() as tmp_dir:
        tmp_file_path = os.path.join(tmp_dir, "thumbnail.gif")

        with open(tmp_file_path, "wb") as f:
            f.write(content)

        im = Image.open(tmp_file_path)

        if sampling_mode == GifSamplingMode.UNIFORM:
            indices = _uniform_sampling_indices(im.n_frames, max_frames)
        else:
            if frame_sample_frequency < 1:
                raise ValueError("frame_sample_frequency must be >= 1")
            indices = _fixed_sampling_indices(im.n_frames, frame_sample_frequency, max_frames)

        frames: List[Image.Image] = []
        for frame_index in indices:
            im.seek(frame_index)
            frames.append(im.copy())

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
