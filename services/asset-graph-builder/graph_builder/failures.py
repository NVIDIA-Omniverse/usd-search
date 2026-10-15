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

"""Failure taxonomy shared by the graph-builder service and its builder script.

A graph build can fail for very different reasons — the asset is gone, the
credentials are wrong, the layer is malformed, the builder ran out of memory, the
build took too long. Historically all of them collapsed into one opaque
``graph_construction_failed`` at the plugin, which made a crawl's failure rate
impossible to act on. Every failure path here carries a :class:`GraphBuildReason`
so the caller can report a real breakdown.

Two processes cooperate:

* ``usd_deps.py`` runs in the builder subprocess. It classifies what it can see
  from the inside (the layer would not open, the asset is missing) and reports it
  by writing an error document to ``OUTPUT_PATH`` *and* exiting with the matching
  code from :class:`BuilderExitCode`.
* ``service.py`` supervises that process. It classifies what is only visible
  from the outside (the process was killed for exceeding the memory watchdog,
  the build exceeded its timeout) and otherwise adopts the child's reason.
"""

import asyncio
import logging
import os
from asyncio.subprocess import Process
from enum import Enum, IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


class GraphBuildReason(str, Enum):
    """Why a graph build failed. Serialized as ``reason`` in the error body."""

    #: Kit exceeded the memory watchdog, or was reaped by the kernel OOM killer.
    oom = "oom"
    #: The build exceeded ``timeout_seconds``.
    timeout = "timeout"
    #: The stage could not be opened (malformed layer, unresolvable sublayer, ...).
    open_layer_failed = "open_layer_failed"
    #: The storage backend reports the asset does not exist.
    asset_not_found = "asset_not_found"
    #: The storage backend rejected the credentials, or could not be reached.
    access_denied = "access_denied"
    #: Kit exited non-zero for a reason it did not classify itself.
    kit_crashed = "kit_crashed"
    #: The HTTP client went away mid-build.
    client_disconnected = "client_disconnected"
    #: Anything unclassified — a bug in the builder rather than a bad asset.
    internal_error = "internal_error"


class BuilderExitCode(IntEnum):
    """Exit codes the Kit script uses to report a classified failure.

    Kept small and well away from the codes a signal death produces (128+N), so
    ``-9`` / ``137`` remain unambiguously "killed", not "classified".
    """

    ok = 0
    open_layer_failed = 3
    asset_not_found = 4
    access_denied = 5
    internal_error = 6


#: Exit code -> reason, for the codes the Kit script sets deliberately.
EXIT_CODE_REASONS = {
    BuilderExitCode.open_layer_failed: GraphBuildReason.open_layer_failed,
    BuilderExitCode.asset_not_found: GraphBuildReason.asset_not_found,
    BuilderExitCode.access_denied: GraphBuildReason.access_denied,
    BuilderExitCode.internal_error: GraphBuildReason.internal_error,
}


def reason_for_exit_code(returncode: Optional[int]) -> GraphBuildReason:
    """Map a Kit process exit code to a reason.

    ``-9`` (asyncio's rendering of SIGKILL) and ``137`` (128 + SIGKILL, what a
    shell wrapper would report) are treated as OOM: nothing else in this service
    SIGKILLs Kit except the memory watchdog and the timeout path, and both of
    those classify the failure themselves before this is consulted. A SIGKILL
    that reaches here therefore came from outside the process — in practice the
    kernel's cgroup OOM killer.
    """
    if returncode in (-9, 137):
        return GraphBuildReason.oom
    try:
        return EXIT_CODE_REASONS[BuilderExitCode(returncode)]
    except (ValueError, KeyError):
        return GraphBuildReason.kit_crashed


class GraphBuildError(Exception):
    """A build failure that carries its reason and the HTTP status to report."""

    def __init__(
        self,
        message: str,
        reason: GraphBuildReason = GraphBuildReason.internal_error,
        status_code: int = 500,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code
        #: Partial phase timings, attached by the request handler. Failed builds
        #: are the ones whose timings matter most — "died 22 minutes into
        #: traverse_recursive" is what turns an OOM report into a fixable one.
        self.timings: Optional[dict] = None


def _rss_mb(pid: int) -> Optional[float]:
    """Resident set size of ``pid`` in MB, or ``None`` if the process is gone.

    Read straight from ``/proc`` rather than via ``psutil`` so the watchdog adds
    no dependency and no per-poll object churn. ``statm`` field 2 is the
    resident page count.
    """
    try:
        with open(f"/proc/{pid}/statm", "r", encoding="utf-8") as statm:
            resident_pages = int(statm.read().split()[1])
    except (FileNotFoundError, ProcessLookupError, IndexError, ValueError):
        return None
    return resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)


async def memory_limit_watcher(
    process: Process,
    max_mem_mb: int,
    poll_interval: float = 0.5,
) -> bool:
    """Kill ``process`` if its RSS exceeds ``max_mem_mb``. Returns whether it did.

    This is a *soft* limit that must sit below the container's memory limit. Its
    whole purpose is to lose the race to the kernel deliberately: if we kill Kit
    first we can answer "this asset needs more than N MB", whereas a cgroup OOM
    kill of the service process leaves nothing to report and takes the in-flight
    request's connection down with it.

    Only the direct child's RSS is measured — the same approach the rendering-job
    watcher uses (``deepsearch_rendering_job/utils.py``). Kit dominates the
    cgroup's footprint, so summing a process tree would buy accuracy that does
    not change the outcome while risking double-counted shared pages.
    """
    if max_mem_mb <= 0:
        return False

    while process.returncode is None:
        rss_mb = _rss_mb(process.pid)
        if rss_mb is None:
            break
        if rss_mb > max_mem_mb:
            logger.warning(
                "Kit process %d exceeded the memory watchdog: RSS %.1f MB > %d MB; killing it",
                process.pid,
                rss_mb,
                max_mem_mb,
            )
            process.kill()
            await process.wait()
            return True
        if rss_mb > 0.95 * max_mem_mb:
            logger.warning(
                "Kit process %d memory is high: RSS %.1f MB (%.0f%% of the %d MB watchdog)",
                process.pid,
                rss_mb,
                rss_mb / max_mem_mb * 100,
                max_mem_mb,
            )
        else:
            logger.debug("Kit process %d RSS: %.1f MB", process.pid, rss_mb)
        await asyncio.sleep(poll_interval)

    return False
