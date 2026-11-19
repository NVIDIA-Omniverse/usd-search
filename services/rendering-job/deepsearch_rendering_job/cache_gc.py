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

"""Size budget for the resolver's on-disk USD cache (``OVRTX_USD_CACHE_DIR``).

Every render runs ovrtx's client library in a short-lived child process, and all
of them download into the one shared cache directory without ever evicting from
it. The ``[cache] max_size`` written into ``omniverse.toml`` is enforced only by
the Hub's cleaner, which nothing here runs (each client logs
``with_cleaner=false``), so left alone the cache grows until the kubelet evicts
the pod at the volume's ``sizeLimit``. The long-lived parent process (the API
server, or the k8s renderer job's CLI) therefore owns eviction.

Deleting cache entries is safe at any time: a missing entry is a plain cache
miss and gets downloaded again, and a reader that already has a file open keeps
reading it after the unlink.

Kept in step with ``services/asset-graph-builder/graph_builder/cache_gc.py``,
which bounds the graph builder's cache the same way; the two services ship as
separate images with no shared package.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import List, Tuple

logger = logging.getLogger(__name__)

# The client library's own bookkeeping (``_cache.json`` marker, ``_cache.lock``).
# Not content, so never evicted.
_RESERVED_PREFIX = "_cache."


@dataclass
class TrimResult:
    usage_before: int
    usage_after: int
    files_removed: int


def _disk_usage(st: os.stat_result) -> int:
    # Allocated blocks, not st_size: the kubelet's emptyDir accounting counts
    # what the files occupy on disk.
    return st.st_blocks * 512


def _last_used(st: os.stat_result) -> float:
    # Never mtime: the client library stamps downloads with the server's
    # Last-Modified, so mtime says how old the asset is, not when it was used.
    # ctime is the download time and atime moves on a cache hit (at most daily
    # under relatime), so their max is a usable LRU key.
    return max(st.st_atime, st.st_ctime)


def _scan(root: str) -> Tuple[List[Tuple[float, int, str]], int]:
    entries: List[Tuple[float, int, str]] = []
    total = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            # A directory's own blocks count too, as they do in the kubelet's du.
            total += _disk_usage(os.lstat(directory))
            iterator = os.scandir(directory)
        except FileNotFoundError:
            continue
        with iterator:
            for entry in iterator:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    st = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue
                size = _disk_usage(st)
                total += size
                if not entry.name.startswith(_RESERVED_PREFIX):
                    entries.append((_last_used(st), size, entry.path))
    return entries, total


def _prune_empty_dirs(root: str) -> None:
    for directory, _, _ in os.walk(root, topdown=False):
        if directory == root:
            continue
        try:
            os.rmdir(directory)
        except OSError:
            pass  # not empty, or already gone


def trim_cache(root: str, max_size_bytes: int, cleanup_threshold: float) -> TrimResult:
    """Evict least-recently-used files once usage exceeds the budget.

    Trims down to ``cleanup_threshold * max_size_bytes`` whenever usage is above
    ``max_size_bytes``, so a full cache is not trimmed again on every pass.
    ``cleanup_threshold`` is clamped to ``[0, 1]``: a percentage such as 80 would
    otherwise put the target above usage and nothing would ever be evicted.
    """
    cleanup_threshold = min(max(cleanup_threshold, 0.0), 1.0)
    entries, usage = _scan(root)
    if usage <= max_size_bytes:
        return TrimResult(usage_before=usage, usage_after=usage, files_removed=0)

    target = int(max_size_bytes * cleanup_threshold)
    usage_after = usage
    removed = 0
    for _, size, path in sorted(entries):
        if usage_after <= target:
            break
        try:
            os.remove(path)
        except FileNotFoundError:
            pass  # evicted concurrently; still no longer counted
        except OSError as e:
            logger.warning("Could not evict cache file %s: %s", path, e)
            continue
        usage_after -= size
        removed += 1
    _prune_empty_dirs(root)
    return TrimResult(usage_before=usage, usage_after=usage_after, files_removed=removed)


async def run_cache_gc(root: str, max_size_bytes: int, cleanup_threshold: float, interval_seconds: float) -> None:
    """Trim ``root`` now and then every ``interval_seconds``, until cancelled.

    The first pass runs immediately: a restarted container can come back to a
    volume that is already full.
    """
    logger.info(
        "Cache GC enabled for %s: max_size_bytes=%d cleanup_threshold=%s interval_seconds=%s",
        root,
        max_size_bytes,
        cleanup_threshold,
        interval_seconds,
    )
    while True:
        try:
            result = await asyncio.to_thread(trim_cache, root, max_size_bytes, cleanup_threshold)
            if result.files_removed:
                logger.info(
                    "Cache GC evicted %d files from %s: %d -> %d bytes",
                    result.files_removed,
                    root,
                    result.usage_before,
                    result.usage_after,
                )
        except Exception:
            logger.exception("Cache GC pass failed for %s", root)
        await asyncio.sleep(interval_seconds)
