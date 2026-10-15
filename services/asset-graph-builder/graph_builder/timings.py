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

"""Per-phase build timings, written incrementally so a killed build still reports.

Where the time in a graph build actually goes — Kit process startup, opening the
stage, traversing it — is only visible from inside the Kit subprocess, and the
builds we most want to explain are exactly the ones that never finish: an OOM
kill or a timeout SIGKILLs Kit mid-traversal.

So timings go to their **own** file, one line per event, flushed as they happen.
The graph document cannot serve this purpose: it is written once at the very end,
so a killed build produces no document and no timings at all. With a separate
append-only file the supervising service can still report "it spent 40s starting
Kit, 12s opening the stage, then died 22 minutes into traverse_recursive" — which
is the difference between an actionable OOM report and an opaque one.

SIGKILL cannot be trapped, so nothing may be deferred to an exit handler; each
record is flushed at the moment it is produced.
"""

import json
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

#: Env var naming the file the Kit script appends timing records to.
TIMINGS_PATH_ENV = "TIMINGS_PATH"


class TimingRecorder:
    """Append-only phase timer used inside the Kit subprocess.

    A no-op when no path is configured, so the Kit script stays runnable
    standalone.
    """

    def __init__(self, path: Optional[str]) -> None:
        self._path = path
        self._start = time.monotonic()

    @classmethod
    def from_env(cls) -> "TimingRecorder":
        return cls(os.getenv(TIMINGS_PATH_ENV) or None)

    @property
    def enabled(self) -> bool:
        return self._path is not None

    def _write(self, record: Dict[str, Any]) -> None:
        if self._path is None:
            return
        record["elapsed_ms"] = round((time.monotonic() - self._start) * 1000, 2)
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
                handle.flush()
        except OSError as exc:  # never fail a build over telemetry
            logger.warning("Could not record timing %r: %s", record.get("phase") or record.get("event"), exc)

    def script_started(self) -> None:
        """Record the wall-clock moment the Kit script began executing.

        The supervising service subtracts this from its own spawn timestamp to
        get Kit's startup cost — the one phase it cannot measure from outside,
        and the one the "cold start dominates" question hinges on.
        """
        self._write({"event": "script_start", "epoch": time.time()})

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Time a phase, recording its start before running it.

        The start record is what makes a killed build legible: a phase with a
        start and no end is where the process died.
        """
        self._write({"event": "phase_start", "phase": name})
        started = time.monotonic()
        try:
            yield
        finally:
            self._write(
                {
                    "event": "phase_end",
                    "phase": name,
                    "duration_ms": round((time.monotonic() - started) * 1000, 2),
                }
            )


def read_timings(path: str, spawned_at: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Read a timings file into a flat summary, tolerating truncation.

    A SIGKILLed process can leave a half-written final line, so malformed lines
    are skipped rather than discarding the whole file.

    Args:
        path: the timings file the Kit script was told to write.
        spawned_at: ``time.time()`` from just before the subprocess was created.
            When given, the summary includes ``kit_startup_ms``.

    Returns:
        ``{"kit_startup_ms": float, "phases": {name: ms}, "died_in": name|None,
        "total_ms": float}``, or ``None`` if nothing was recorded.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None

    records: List[Dict[str, Any]] = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            # Truncated final line from a killed process — everything before it
            # is still good.
            continue

    if not records:
        return None

    summary: Dict[str, Any] = {"phases": {}, "died_in": None}
    open_phases: List[str] = []

    for record in records:
        event = record.get("event")
        if event == "script_start" and spawned_at is not None:
            summary["kit_startup_ms"] = round((record["epoch"] - spawned_at) * 1000, 2)
        elif event == "phase_start":
            open_phases.append(record.get("phase"))
        elif event == "phase_end":
            phase = record.get("phase")
            summary["phases"][phase] = record.get("duration_ms")
            if phase in open_phases:
                open_phases.remove(phase)

    # A phase that started and never ended is where the process was killed.
    if open_phases:
        summary["died_in"] = open_phases[-1]

    summary["total_ms"] = records[-1].get("elapsed_ms")
    return summary
