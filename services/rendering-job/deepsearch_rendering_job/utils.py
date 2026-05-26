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

import asyncio
import base64
import hashlib
import io
import logging
import resource
import socket
import time
import zlib
from asyncio import Semaphore
from asyncio.subprocess import Process
from contextlib import closing
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import orjson
import psutil
from PIL import Image

from .models import (
    RenderingStatus,
    kit_process_memory_gauge,
    kit_process_memory_gauge_percentage,
    kit_process_pid_gauge,
    kit_process_rendering_time_gauge,
    kit_process_rendering_time_percentage_gauge,
    waiting_requests_gauge,
)
from .secure_pickle import RENDERING_APPROVED_CLASSES
from .secure_pickle import loads as _secure_loads

logger = logging.getLogger(__name__)


def find_free_port() -> int:
    """Find available port on the system

    Returns:
        int: port number
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as _socket:
        _socket.bind(("", 0))
        _socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(_socket.getsockname()[1])


def get_key(url: str) -> str:
    return hashlib.sha256(str(url).encode()).hexdigest()


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


def unpickle_data(input: str) -> Union[str, dict]:
    """Deserialize numpy data using :func:`pickle.dumps` functionality"""
    status_map = {
        RenderingStatus.load_error: RenderingStatus.load_error,
        RenderingStatus.error: RenderingStatus.error,
        RenderingStatus.timeout: RenderingStatus.timeout,
        RenderingStatus.invalid_mtl_names: RenderingStatus.invalid_mtl_names,
    }
    if input in status_map:
        return status_map[input]
    if input.startswith("Error rendering"):
        return RenderingStatus.render_error

    input_bytes = input.encode("latin1")
    decompressed_bytes = zlib.decompress(input_bytes)
    data = _secure_loads(decompressed_bytes, approved_imports=RENDERING_APPROVED_CLASSES)
    return normalize_payload_images(data)


def image_to_base64(input, format: str = "JPEG") -> str:
    """Covert image to base64 format

    Args:
        input: PIL image type

    Returns:
        str: base64 encoding of an image
    """
    with io.BytesIO() as output:
        input.convert("RGB").save(output, format=format)
        content = base64.b64encode(output.getvalue()).decode("ascii")
    return content


def extract_images_from_payload(content: dict, key: str = "images") -> List[str]:
    images = content.get(key, [])
    if images is None or (hasattr(images, "__len__") and len(images) == 0):
        return []

    # Detect background-only images (uniform color with std <= 1.0)
    has_content = any(not hasattr(im, "std") or im.std() > 1.0 for im in images)
    if not has_content:
        logger.warning("All %d images are background-only, returning empty list", len(images))
        return []

    return [image_to_base64(Image.fromarray(im)) for im in images]


def extract_camera_metadata_from_payload(content: dict, key: str = "camera_metadata") -> List[Dict[str, Any]]:
    return [orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY) for data in content[key]]


def set_memory_limit(max_mem_mb: int):
    """Set a hard memory limit for the subprocess (Unix only)."""
    print(f"Setting memory limit to {max_mem_mb} MB")
    max_bytes = max_mem_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))


async def memory_limit_watcher(
    process: Process, max_mem_mb: int, worker_id: Optional[str] = None
) -> Optional[RenderingStatus]:
    """Watch the memory usage of the process and kill it if it exceeds the limit.

    Args:
        process: The process to watch
        max_mem_mb: Maximum memory in MB
        worker_id: Optional worker ID for metrics labeling. If None, will use PID.
    """
    p = psutil.Process(process.pid)

    # Determine the worker_id label - use provided worker_id or fallback to PID
    worker_label = worker_id if worker_id is not None else f"pid_{process.pid}"

    oom_killed = False
    while True:
        if process.returncode is not None:
            logger.info("Process returned code: %s", process.returncode)
            break
        rss_mb = p.memory_info().rss / 1024 / 1024
        percentage = (rss_mb / max_mem_mb) * 100

        # kit process memory labels
        kit_process_memory_labels = {
            "worker_id": worker_label,
            "memory_limit": max_mem_mb if max_mem_mb > 0 else None,
        }
        # update prometheus metrics
        kit_process_memory_gauge.labels(**kit_process_memory_labels).set(rss_mb)
        kit_process_memory_gauge_percentage.labels(**kit_process_memory_labels).set(percentage)
        kit_process_pid_gauge.labels(worker_id=worker_label).set(process.pid)
        # issue a waring in case 95% percent of memory is reached
        if percentage > 95:
            logger.warning(
                "Memory usage is high for %s: RSS %.1f MB (%.1f%%), process will be killed if exceeded %d MB",
                worker_label,
                rss_mb,
                percentage,
                max_mem_mb,
            )
        else:
            logger.debug("RSS for %s: %.1f MB (%.1f%%)", worker_label, rss_mb, percentage)
        if rss_mb > max_mem_mb:
            process.terminate()
            process.kill()
            await process.wait()
            oom_killed = True
            logger.warning("Killed process %s at %.1f MB RSS", worker_label, rss_mb)
            break
        await asyncio.sleep(0.5)

    kit_process_pid_gauge.labels(worker_id=worker_label).set(0)
    kit_process_memory_gauge.labels(**kit_process_memory_labels).set(0)
    kit_process_memory_gauge_percentage.labels(**kit_process_memory_labels).set(0)
    if oom_killed:
        return RenderingStatus.out_of_memory
    return None


async def rendering_timeout_watcher(
    process: Process, worker_id: Optional[str] = None, timeout: Optional[float] = None
) -> Optional[RenderingStatus]:
    """Watch the memory usage of the process and kill it if it exceeds the limit.

    Args:
        process: The process to watch
        max_mem_mb: Maximum memory in MB
        worker_id: Optional worker ID for metrics labeling. If None, will use PID.
    """
    start_time = time.time()

    # Determine the worker_id label - use provided worker_id or fallback to PID
    worker_label = worker_id if worker_id is not None else f"pid_{process.pid}"

    timed_out = False
    while True:
        if process.returncode is not None:
            logger.info("Process returned code: %s", process.returncode)
            break

        time_left = timeout - (time.time() - start_time)

        # kit process rendering time labels
        kit_process_rendering_time_labels = {"worker_id": worker_label}
        # update prometheus metrics
        kit_process_rendering_time_gauge.labels(**kit_process_rendering_time_labels).set(time.time() - start_time)
        kit_process_rendering_time_percentage_gauge.labels(**kit_process_rendering_time_labels).set(
            (time.time() - start_time) / timeout * 100
        )

        # issue a waring in case 5% percent of time is left
        if time_left / timeout < 0.05:
            logger.warning("Rendering timeout for %s: %.1f seconds left", worker_label, time_left)
        else:
            logger.debug("Rendering timeout for %s: %.1f seconds left", worker_label, time_left)
        if time_left <= 0:
            process.terminate()
            process.kill()
            await process.wait()
            logger.warning("Killed process %s due to rendering timeout", worker_label)
            timed_out = True
            break
        await asyncio.sleep(0.5)

    kit_process_rendering_time_gauge.labels(**kit_process_rendering_time_labels).set(0)
    kit_process_rendering_time_percentage_gauge.labels(**kit_process_rendering_time_labels).set(0)
    if timed_out:
        return RenderingStatus.timeout
    return None


async def create_process_with_memory_limit_and_timeout(
    *args,
    max_mem_mb: int,
    worker_id: Optional[str] = None,
    timeout: Optional[float] = None,
    **kwargs,
) -> Tuple[Process, Optional[asyncio.Task], Optional[asyncio.Task]]:
    """Create a process with memory limit monitoring.

    Args:
        *args: Process arguments
        max_mem_mb: Maximum memory in MB (if <= 0, no limit is enforced)
        worker_id: Optional worker ID for metrics labeling
        timeout: Optional rendering timeout in seconds
        **kwargs: Additional process arguments

    Returns:
        The created process
    """
    process = await asyncio.create_subprocess_exec(*args, **kwargs)
    memory_watcher_task = None
    timeout_watcher_task = None
    if max_mem_mb > 0:
        memory_watcher_task = asyncio.create_task(memory_limit_watcher(process, max_mem_mb, worker_id=worker_id))
    if timeout is not None and timeout > 0:
        timeout_watcher_task = asyncio.create_task(
            rendering_timeout_watcher(process, worker_id=worker_id, timeout=timeout)
        )
    return process, memory_watcher_task, timeout_watcher_task


async def update_waiting_requests_gauge(semaphore: Optional[Semaphore]) -> None:
    if isinstance(semaphore, Semaphore):
        waiting_requests_gauge.set(len(semaphore._waiters) if semaphore._waiters is not None else 0)
    else:
        waiting_requests_gauge.set(0)
