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

"""Package-internal constants shared across multiple modules."""

# Image-format magic-byte signatures (file headers).
PNG_MAGIC_BYTES = b"\x89PNG"
JPEG_MAGIC_BYTES = b"\xff\xd8\xff"
GIF87_MAGIC_BYTES = b"GIF87a"
GIF89_MAGIC_BYTES = b"GIF89a"

# Mapping from header bytes to MIME type. Used by both the inbound base64
# image validator (``routers_v2/models.py``) and the outbound Content-Type
# detector (``routers_v3/images.py``).
IMAGE_MAGIC_TO_MIME: dict[bytes, str] = {
    JPEG_MAGIC_BYTES: "image/jpeg",
    PNG_MAGIC_BYTES: "image/png",
    GIF87_MAGIC_BYTES: "image/gif",
    GIF89_MAGIC_BYTES: "image/gif",
}

# Maximum number of images accepted per VLM validation call.
MAX_IMAGES_PER_VALIDATION = 8

# Internal route URIs (used by tests against the live app).
HEALTH_URI = "health"
METRICS_URI = "metrics"
