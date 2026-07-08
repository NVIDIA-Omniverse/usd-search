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

from typing import List, Optional

from deepsearch_utils.image_processing_utils import GifSamplingMode

# local / proprietary modules
from .base_plugin import BasePluginConfig


class VisionMetadataPluginConfig(BasePluginConfig):
    vlm_agenerate_timeout: float = 60 * 60  # 60 minutes
    use_embedding_client: bool = False


class ImageToEmbeddingConfig(BasePluginConfig):
    # GIF frame sampling strategy:
    #   FIXED   -> take every gif_frame_sample_frequency-th frame, capped at gif_max_frames.
    #   UNIFORM -> spread up to gif_max_frames frames evenly across the GIF
    #              (gif_frame_sample_frequency is ignored).
    gif_sampling_mode: GifSamplingMode = GifSamplingMode.FIXED
    # Only applies in FIXED mode: take every Nth frame (1 = every frame).
    gif_frame_sample_frequency: int = 1
    gif_max_frames: int = 512
    max_file_size_mb: int = 0  # 0 = unlimited; if > 0, skip files larger than this (in MB)
    # Full-size images can be large; serialize data loads to bound memory.
    data_load_concurrency: Optional[int] = 1


class ThumbnailToEmbeddingConfig(ImageToEmbeddingConfig):
    thumbnail_filepath_patterns: Optional[List[str]] = None
    thumbnail_location: str = ".thumbs"
    thumbnail_suffixes: Optional[List[str]] = ["", ".auto"]
    # Thumbnails are small; restore the unlimited default from BasePluginConfig.
    data_load_concurrency: Optional[int] = None
