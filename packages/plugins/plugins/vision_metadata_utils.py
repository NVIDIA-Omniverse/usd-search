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

import hashlib
import json
import logging
import math
import urllib.parse
from typing import Sequence, TypeVar

from PIL import Image

from search_utils.misc_utils import image_to_base64

from .config import VisionMetadataPluginConfig

T = TypeVar("T")
logger = logging.getLogger(__name__)

# This identifier is part of the asset-state fingerprint of deployments that
# opted in with a metadata revision. Change it whenever encoding/sampling policy
# changes in a way that can affect output.
VISION_METADATA_ENCODER_POLICY = "png-rgb-uniform-adaptive-v1"

# The image strings are embedded in a larger JSON request. Reserving fixed and
# per-image space keeps the configured byte ceiling useful at HTTP boundaries,
# rather than treating base64 characters as the entire request.
# The prompt and structured-output schema are currently around 13 KiB on disk;
# keep ample headroom for their JSON representation and provider wrappers.
VLM_REQUEST_FIXED_OVERHEAD_BYTES = 64 * 1024
VLM_REQUEST_PER_IMAGE_OVERHEAD_BYTES = 128

# Below this longest-edge size, retaining extra views costs more metadata
# quality than uniformly dropping a view. A final remaining view may shrink as
# far as one pixel so a failure is raised only when the byte limit is truly
# impossible to satisfy. Tiny input images are never upscaled.
VLM_MIN_IMAGE_MAX_PX = 64


# Optional batch-item keys a caller may set beside the images: one label per
# image ("front", "spin 2", "open"), in order, and a name hint for the asset.
# Nothing in this repo sets `view_labels`: the thumbnail path only passes them
# through, so its views go unlabelled unless the producer of the batch items
# (a custom loader, a later view-classification pass) fills them.
VIEW_LABELS_FIELD = "view_labels"
ASSET_HINT_FIELD = "asset_hint"


def carry_view_inputs(data: Sequence[dict], batch_data: list, indices: list[int], images_field: str) -> None:
    """Copy each kept item's view labels and name hint from the raw ``data`` onto
    its prepared ``batch_data`` entry. Labels follow the images preprocessing
    kept (a 1x1 placeholder image is dropped, so is its label)."""

    for entry, index in zip(batch_data, indices):
        item = data[index]
        hint = item.get(ASSET_HINT_FIELD)
        if hint:
            entry[ASSET_HINT_FIELD] = str(hint)
        labels = item.get(VIEW_LABELS_FIELD)
        images = item.get(images_field) or []
        if labels is None:
            continue
        if len(labels) != len(images):
            logger.warning(
                "%s: %d view labels for %d images; sending the views unlabelled",
                item.get("omni_path"),
                len(labels),
                len(images),
            )
            continue
        kept = [str(label) for label, image in zip(labels, images) if image.size != (1, 1)]
        if len(kept) == len(entry[images_field]):
            entry[VIEW_LABELS_FIELD] = kept


class VLMPayloadBudgetError(ValueError):
    """Raised when even one minimum-size image cannot fit the request budget."""


def vision_metadata_asset_state_hash(hash_value: str, config: VisionMetadataPluginConfig) -> str:
    """Return the plugin's cache identity for an asset.

    Without a configured ``vlm_metadata_revision`` (the default) this is the bare
    asset hash, byte-identical to the identity used before the request limits
    existed, so an upgrade never requeues unchanged assets and earlier metadata
    stays searchable alongside newer output. A non-empty revision opts the
    deployment in: the revision and the request limits are folded into a stable,
    credential-free fingerprint, and changing any of them reprocesses unchanged
    assets.
    """

    if not config.vlm_metadata_revision:
        return hash_value

    fingerprint_input = {
        "encoder_policy": VISION_METADATA_ENCODER_POLICY,
        "max_images": config.vlm_max_images,
        "max_px": config.vlm_image_max_px,
        "max_request_bytes": config.vlm_max_request_bytes,
        "revision": config.vlm_metadata_revision,
    }
    if config.vlm_asset_hint:
        # Only present when on, so opted-in deployments that never use it keep
        # their fingerprint (and are not reprocessed) on upgrade.
        fingerprint_input["asset_hint"] = True
    serialized = json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    fingerprint = hashlib.sha256(serialized).hexdigest()
    return f"{hash_value}_vision_metadata_{fingerprint}"


def uniformly_sample(items: Sequence[T], max_items: int) -> list[T]:
    """Return at most ``max_items`` ordered values, including both endpoints."""

    if max_items <= 0:
        raise ValueError("max_items must be positive")

    item_count = len(items)
    if item_count <= max_items:
        return list(items)
    if max_items == 1:
        return [items[0]]

    indices = [round(i * (item_count - 1) / (max_items - 1)) for i in range(max_items)]
    return [items[index] for index in indices]


def estimate_vlm_image_request_bytes(base64_images: Sequence[str]) -> int:
    """Estimate serialized request bytes attributable to the image inputs."""

    return (
        VLM_REQUEST_FIXED_OVERHEAD_BYTES
        + VLM_REQUEST_PER_IMAGE_OVERHEAD_BYTES * len(base64_images)
        + sum(len(image.encode("ascii")) for image in base64_images)
    )


def _copy_with_max_edge(image: Image.Image, max_px: int) -> Image.Image:
    copied = image.convert("RGB")
    copied.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    return copied


def _resize_copies(images: Sequence[Image.Image], max_px: int) -> list[Image.Image]:
    return [_copy_with_max_edge(image, max_px) for image in images]


def _encode_png(images: Sequence[Image.Image]) -> list[str]:
    return [image_to_base64(image, format="PNG") for image in images]


def _payload_capacity(max_request_bytes: int, image_count: int) -> int:
    return max_request_bytes - VLM_REQUEST_FIXED_OVERHEAD_BYTES - VLM_REQUEST_PER_IMAGE_OVERHEAD_BYTES * image_count


def encode_vlm_images(
    images: Sequence[Image.Image],
    config: VisionMetadataPluginConfig,
    logger: logging.Logger | None = None,
) -> list[str]:
    """Sample and PNG-encode images without exceeding the configured budget.

    The routine first retains the configured number of uniformly spaced views,
    then reduces their resolution together. Views are removed uniformly only
    when the full set cannot fit at the minimum useful resolution. All resizing
    is performed on copies, so callers' images and sequences are unchanged.
    """

    return encode_vlm_images_with_indices(images, config=config, logger=logger)[0]


def asset_hint_from_path(omni_path: str, folders: int = 2) -> str:
    """The asset's file name and its nearest folders, e.g.
    ``refrigerator_f01/simready_usd/sm_refrigerator_f01_01.usd`` — no scheme,
    host, bucket or revision (those name the store, not the object)."""

    path = urllib.parse.unquote(
        urllib.parse.urlsplit(str(omni_path)).path if "://" in str(omni_path) else str(omni_path)
    )
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return "/".join(parts[-(folders + 1) :])


def encode_vlm_images_with_indices(
    images: Sequence[Image.Image],
    config: VisionMetadataPluginConfig,
    logger: logging.Logger | None = None,
) -> tuple[list[str], list[int]]:
    """``encode_vlm_images`` plus the input index of every image kept, in order,
    so a caller's per-image labels follow the sampling."""

    selected_indices = uniformly_sample(range(len(images)), config.vlm_max_images)
    if not selected_indices:
        return [], []
    selected = [images[index] for index in selected_indices]

    initial_prepared = _resize_copies(selected, config.vlm_image_max_px)
    initial_count = len(initial_prepared)
    initial_max_px = max(max(image.size) for image in initial_prepared)
    candidate_count = initial_count

    while candidate_count > 0:
        # Always choose each candidate set from the original selection. Sampling
        # an already sampled list repeatedly would compound rounding errors and
        # progressively skew the retained views.
        positions = uniformly_sample(range(initial_count), candidate_count)
        prepared = [initial_prepared[position] for position in positions]
        current_max_px = max(max(image.size) for image in prepared)
        minimum_max_px = 1 if len(prepared) == 1 else min(VLM_MIN_IMAGE_MAX_PX, current_max_px)
        working = list(prepared)

        while True:
            encoded = _encode_png(working)
            request_bytes = estimate_vlm_image_request_bytes(encoded)
            if request_bytes <= config.vlm_max_request_bytes:
                if logger is not None and (len(working) != initial_count or current_max_px != initial_max_px):
                    logger.warning(
                        "Adjusted VLM input to %d image(s) at <=%dpx (%d/%d request bytes)",
                        len(working),
                        current_max_px,
                        request_bytes,
                        config.vlm_max_request_bytes,
                    )
                return encoded, [selected_indices[position] for position in positions]

            if current_max_px <= minimum_max_px:
                break

            payload_capacity = _payload_capacity(config.vlm_max_request_bytes, len(working))
            encoded_bytes = sum(len(image) for image in encoded)
            if payload_capacity <= 0:
                next_max_px = minimum_max_px
            else:
                # Image bytes approximately scale with pixel area. Leave a 5%
                # safety margin for PNG compression's non-linear behaviour and
                # always make progress even for unusually compressible inputs.
                scale = math.sqrt(payload_capacity / encoded_bytes) * 0.95
                next_max_px = max(minimum_max_px, min(current_max_px - 1, int(current_max_px * scale)))

            current_max_px = next_max_px
            working = _resize_copies(prepared, current_max_px)

        if len(prepared) == 1:
            minimum_encoded = _encode_png(_resize_copies(prepared, minimum_max_px))
            minimum_bytes = estimate_vlm_image_request_bytes(minimum_encoded)
            raise VLMPayloadBudgetError(
                "Unable to fit one PNG VLM image within vlm_max_request_bytes="
                f"{config.vlm_max_request_bytes}; minimum supported request is {minimum_bytes} bytes"
            )

        # The full view set could not fit at the minimum useful resolution.
        # Drop one view uniformly, restart from the capped originals, and let
        # the next pass retain the highest resolution that fits.
        candidate_count -= 1

    raise VLMPayloadBudgetError("Unable to prepare any VLM images within the configured request budget")
