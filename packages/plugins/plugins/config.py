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
from pydantic import Field, field_validator

# local / proprietary modules
from .base_plugin import BasePluginConfig


class VisionMetadataPluginConfig(BasePluginConfig):
    vlm_agenerate_timeout: float = 60 * 60  # 60 minutes
    use_embedding_client: bool = False
    # Cap on images per VLM request (evenly sampled when exceeded). Guards
    # against request-body blowups (e.g. a 512-frame GIF, now PNG-encoded);
    # hub-served open models also cap around 10-16 images per request.
    vlm_max_images: int = Field(default=16, gt=0)
    # Max pixel edge for VLM input images (env VLM_IMAGE_MAX_PX). Shrink-only:
    # smaller sources pass through at native size — upscaling adds no
    # information, only payload bytes.
    vlm_image_max_px: int = Field(default=512, gt=0)
    # Upper bound for the complete image portion of a VLM request, including
    # conservative fixed and per-image serialization overhead.
    vlm_max_request_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    # Optional output-contract revision (env VLM_METADATA_REVISION). Empty, the
    # default, keeps the legacy asset-only cache identity: upgrading never
    # reprocesses unchanged assets on its own, and earlier metadata stays
    # searchable. Any non-empty value opts the deployment in: the revision and
    # the three request limits above then join the cache identity, and changing
    # any of them (e.g. bumping the revision after a model, prompt or schema
    # change) makes unchanged assets eligible for reprocessing.
    vlm_metadata_revision: str = ""

    @field_validator("vlm_metadata_revision")
    @classmethod
    def normalize_vlm_metadata_revision(cls, value: str) -> str:
        # Whitespace-only means "not set"; surrounding whitespace never re-keys.
        return value.strip()


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
