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
import hashlib
import io
import logging
import struct
from asyncio import Semaphore
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import orjson
from PIL import Image

from .models import RenderingStatus, waiting_requests_gauge

logger = logging.getLogger(__name__)

# Wire format for a rendered payload: a magic header, a little-endian uint32
# length, the orjson metadata block, then the compressed ``.npz`` array block.
_PAYLOAD_MAGIC = b"DSRP1\0"


def get_key(url: str) -> str:
    return hashlib.sha256(str(url).encode()).hexdigest()


def redact_url(url: str) -> str:
    """Log-safe form of a user-supplied URL: drop credentials, query, fragment; escape control chars.

    Query strings routinely carry secrets (S3 presigned ``X-Amz-Signature``), userinfo can hold
    ``user:pass``, and a decoded CR/LF would let a caller forge log lines.
    """
    url = str(url)
    try:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if ":" in netloc:  # IPv6 literal
            netloc = f"[{netloc}]"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        url = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        url = url.split("?", 1)[0].split("#", 1)[0]
        if "://" in url:  # still drop userinfo from the unparseable authority
            scheme, rest = url.split("://", 1)
            authority, sep, path = rest.partition("/")
            url = f"{scheme}://{authority.rsplit('@', 1)[-1]}{sep}{path}"
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in url)


def _flatten_images(images: List[Any]) -> List[Any]:
    flat: List[Any] = []
    for item in images:
        if isinstance(item, list):
            flat.extend(_flatten_images(item))
        else:
            flat.append(item)
    return flat


def _normalize_images(images: Any) -> Any:
    if isinstance(images, np.ndarray):
        return images
    if not isinstance(images, list):
        return images

    flat = _flatten_images(images)
    if not flat:
        return np.empty((0, 0, 0, 0), dtype=np.uint8)

    arrays = [np.asarray(im) for im in flat if im is not None]
    if not arrays:
        return np.empty((0, 0, 0, 0), dtype=np.uint8)

    if any(arr.ndim == 4 for arr in arrays):
        normalized = []
        for arr in arrays:
            if arr.ndim == 4:
                normalized.append(arr)
            elif arr.ndim == 3:
                normalized.append(arr[None, ...])
            else:
                normalized.append(np.asarray(arr))
        return np.concatenate(normalized, axis=0)

    return np.stack(arrays, axis=0)


def normalize_payload_images(content: Any, key: str = "images") -> Any:
    if not isinstance(content, dict) or key not in content:
        return content

    content[key] = _normalize_images(content[key])
    return content


def serialize_payload(data: Any, compress: bool = True) -> str:
    """Serialize a rendered payload to a binary-safe, base64 wire string.

    Arrays go in an ``.npz`` block and the rest (camera metadata, bounding boxes)
    in an orjson block, so no ``pickle`` is involved. A plain status string is
    passed through unchanged. ``compress`` is writer-only; :func:`deserialize_payload`
    reads either form.
    """
    if not isinstance(data, dict):
        return str(data)

    arrays = {key: np.asarray(value) for key, value in data.items() if isinstance(value, np.ndarray)}
    meta = {key: value for key, value in data.items() if not isinstance(value, np.ndarray)}

    array_buffer = io.BytesIO()
    save_arrays = np.savez_compressed if compress else np.savez
    save_arrays(array_buffer, **arrays)
    meta_bytes = orjson.dumps({"order": list(data.keys()), "meta": meta}, option=orjson.OPT_SERIALIZE_NUMPY)

    frame = _PAYLOAD_MAGIC + struct.pack("<I", len(meta_bytes)) + meta_bytes + array_buffer.getvalue()
    return base64.b64encode(frame).decode("ascii")


def deserialize_payload(input: str) -> Any:
    """Reconstruct a rendered payload produced by :func:`serialize_payload`."""
    status_map = {
        RenderingStatus.load_error: RenderingStatus.load_error,
        RenderingStatus.error: RenderingStatus.error,
        RenderingStatus.timeout: RenderingStatus.timeout,
        RenderingStatus.invalid_mtl_names: RenderingStatus.invalid_mtl_names,
        RenderingStatus.empty_scene: RenderingStatus.empty_scene,
    }
    if input in status_map:
        return status_map[input]
    if input.startswith("Error rendering"):
        return RenderingStatus.render_error

    frame = base64.b64decode(input.encode("ascii"))
    if not frame.startswith(_PAYLOAD_MAGIC):
        raise ValueError("Unrecognized rendered payload format")

    offset = len(_PAYLOAD_MAGIC)
    (meta_len,) = struct.unpack_from("<I", frame, offset)
    offset += struct.calcsize("<I")
    header = orjson.loads(frame[offset : offset + meta_len])
    array_bytes = frame[offset + meta_len :]

    with np.load(io.BytesIO(array_bytes), allow_pickle=False) as npz:
        arrays = {key: npz[key] for key in npz.files}

    meta = header["meta"]
    data = {key: (arrays[key] if key in arrays else meta[key]) for key in header["order"]}
    return normalize_payload_images(data)


def image_to_base64(input, format: str = "JPEG") -> str:
    """Convert image to base64 format."""
    with io.BytesIO() as output:
        input.convert("RGB").save(output, format=format)
        content = base64.b64encode(output.getvalue()).decode("ascii")
    return content


def extract_images_from_payload(content: dict, key: str = "images") -> List[str]:
    images = content.get(key, [])
    if images is None or (hasattr(images, "__len__") and len(images) == 0):
        return []

    has_content = any(not hasattr(im, "std") or im.std() > 1.0 for im in images)
    if not has_content:
        logger.warning("All %d images are background-only, returning empty list", len(images))
        return []

    return [image_to_base64(Image.fromarray(im)) for im in images]


def extract_camera_metadata_from_payload(content: dict, key: str = "camera_metadata") -> List[Dict[str, Any]]:
    return [orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY) for data in content[key]]


class TrackingSemaphore(Semaphore):
    """Semaphore that tracks free slots and waiters with plain counters.

    ``asyncio.Semaphore`` exposes waiter state only through the loop-bound
    ``_waiters`` deque, which is unreliable across event loops (e.g. the test
    client portal loop).  This subclass maintains ``value`` (free slots) and
    ``waiters`` (callers blocked on acquisition) as simple integers so the
    readiness and process-limit checks behave consistently.
    """

    def __init__(self, value: int = 1) -> None:
        super().__init__(value)
        self.value = value
        self.waiters = 0

    async def acquire(self) -> bool:
        if self.value <= 0:
            self.waiters += 1
            try:
                await super().acquire()
            except BaseException:
                self.waiters -= 1
                raise
            self.waiters -= 1
        else:
            await super().acquire()
        self.value -= 1
        return True

    def release(self) -> None:
        self.value += 1
        super().release()


async def update_waiting_requests_gauge(semaphore: Optional[Semaphore]) -> None:
    if isinstance(semaphore, TrackingSemaphore):
        waiting_requests_gauge.set(semaphore.waiters)
    else:
        waiting_requests_gauge.set(0)
