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

"""Prepared reference images (asset views), kept across validation checks.

Before each check, :class:`~llm_client.validation.validation.Validation` prepares every asset view it sends: it
decodes the stored image, fits it to ``image_max_px`` and re-encodes it as ``image_format``
(``Validation._encode_image``). That is most of a check's CPU in the API, and a stored image never changes. With
``image_cache_dir`` set, each prepared view is kept in ``<dir>/<scope>/<sha256 of the stored base64>.b64``, one
copy for every process on the host; with ``image_cache_memory_mb`` set, also in a bounded in-process LRU (or there
alone, for a deployment without a writable disk).

``<scope>`` is a digest of everything besides the stored image that shapes a view
(``Validation.image_encoding_identity``: the image settings, Pillow and its codecs, the encoder's code), so a
change there never serves a view prepared before it. A file starts with its length and CRC-32, and appears under
its name only when whole (a temp file, then ``os.replace``). Only base64 asset views are cached (stored images, and
inline asset views sent to ``/vlm_validate``): never query images, file paths (their file can change under the name)
or PIL images.

Any cache error (unreadable, unwritable, full, a damaged file) prepares the view as without the cache, so a check
never fails because of it; a damaged file is written again. A scope's files stay under ``image_cache_max_mb`` and
never leave less than ``image_cache_min_free_mb`` free on the disk: past either, new views are prepared per check.
Nothing is evicted on its own: the warm-up removes views of images the index no longer holds (``prune``); it and each
API start remove other scopes' unused directories (``sweep``), so a root belongs to one deployment.
"""

import hashlib
import logging
import os
import re
import shutil
import threading
import time
import zlib
from collections import OrderedDict
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MB = 1024 * 1024
# Each process re-reads its scope's size and the disk's free space after writing this much, or this often, so all
# the processes sharing a directory overshoot the cap and the floor by little.
RECHECK_BYTES = 64 * MB
RECHECK_SECONDS = 60.0
# Hex characters of the scope digest: the name of a scope's directory.
SCOPE_CHARS = 24
# Another scope's directory is removed once nothing has written in it for this long (a live process of other
# settings sharing the root, or an old pod during a rolling upgrade, keeps its own).
SCOPE_IDLE_SECONDS = 24 * 3600.0
OUTCOMES = ("hit", "miss", "written", "not_kept", "bypass")
_SCOPE_NAME = re.compile(r"^[0-9a-f]{%d}$" % SCOPE_CHARS)
_VIEW_NAME = re.compile(r"^[0-9a-f]{64}\.b64$")
_TEMP_NAME = re.compile(r"^[0-9a-f]{64}\.b64\.\d+\.\d+\.tmp$")


class ReferenceImageCache:
    """The prepared views of one scope: on disk in ``directory`` (None: memory only) and in a bounded LRU.

    Never raises: a cache failure is a miss. ``counts`` holds each outcome of this process (``OUTCOMES``): ``hit``
    (memory or disk), ``miss`` (prepared), ``written`` / ``not_kept`` (a miss whose view was kept on disk or was not:
    full, unwritable), ``bypass`` (an input that is not a stored base64 image). ``on_event``, when set, is called
    with each outcome (the API's metric). ``full`` is set while the last write found the scope at its cap or the disk
    at its floor.
    """

    def __init__(
        self,
        directory: Optional[str],
        max_bytes: int,
        min_free_bytes: int,
        memory_bytes: int = 0,
        on_event: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self.min_free_bytes = min_free_bytes
        self.memory_bytes = memory_bytes
        self.on_event = on_event
        self.counts = dict.fromkeys(OUTCOMES, 0)
        self.full = False
        self._lock = threading.Lock()
        self._warned: set[str] = set()
        self._memory: "OrderedDict[str, str]" = OrderedDict()
        self._memory_used = 0
        # Bytes of this scope's files and free on the disk, as last read plus this process's writes since.
        self._used: Optional[int] = None
        self._free = 0
        self._written_since = 0
        self._read_at = 0.0
        self._scanning = False

    def describe(self) -> str:
        disk = (
            f"{self.directory} (max {self.max_bytes // MB} MiB, min free {self.min_free_bytes // MB} MiB)"
            if self.directory
            else "no directory"
        )
        return f"{disk}, memory {self.memory_bytes // MB} MiB"

    def disk_bytes(self) -> tuple[int, int]:
        """(bytes of this scope's views, bytes free on its disk) as this process last read them plus its own writes
        since (re-read every ``RECHECK_BYTES`` / ``RECHECK_SECONDS``); (0, 0) before its first write."""
        with self._lock:
            return (self._used, self._free) if self._used is not None else (0, 0)

    def count(self, outcome: str) -> None:
        with self._lock:
            self.counts[outcome] += 1
        if self.on_event is not None:
            try:
                self.on_event(outcome)
            except Exception:  # a metric never fails a check
                pass

    @staticmethod
    def key(image: str) -> str:
        """A stored base64 image's key: the name of its view, ``<key>.b64``."""
        return hashlib.sha256(image.encode("utf-8")).hexdigest()

    def prepare(self, image: str, encode: Callable[[str], str]) -> str:
        """``encode(image)`` for a stored base64 image: read from the cache when it holds it, kept there when not."""
        key = None
        value = None
        try:
            key = self.key(image)
            value = self._recall(key)
        except Exception as e:
            self._warn_once("lookup", "cannot look up a stored image (%s); preparing it per check", e)
        if value is not None:
            self.count("hit")
            return value
        value = encode(image)  # its errors are the check's, as without the cache
        self.count("miss")
        if key is not None:
            self._remember(key, value)
            if self.directory is not None:
                self.count("written" if self._write(self.directory, key, value) else "not_kept")
        return value

    def usage(self) -> tuple[int, int]:
        """(files, bytes) of this scope's views on disk; (0, 0) without a directory."""
        files = size = 0
        if self.directory is None:
            return files, size
        try:
            with os.scandir(self.directory) as entries:
                for entry in entries:
                    if entry.name.endswith(".b64"):
                        try:
                            size += entry.stat().st_size
                            files += 1
                        except OSError:  # replaced or removed meanwhile
                            pass
        except OSError:
            pass
        return files, size

    def sweep(self, older_than: float = 600.0, idle: float = SCOPE_IDLE_SECONDS) -> int:
        """Remove what earlier runs left beside this scope: other scopes' directories under the same root that nothing
        has written in for ``idle`` seconds (other settings, Pillow or encoder code), and temp files of writers that
        died (older than ``older_than`` seconds). Only names this module makes are touched, but any such directory
        under the root goes: give each deployment a root of its own. Returns how many were removed."""
        if self.directory is None:
            return 0
        removed = 0
        now = time.time()
        for entry in _entries(os.path.dirname(self.directory)):
            try:
                if (
                    not _SCOPE_NAME.match(entry.name)
                    or entry.path == self.directory
                    or not entry.is_dir(follow_symlinks=False)
                ):
                    continue
                unused = now - entry.stat(follow_symlinks=False).st_mtime  # a write adds a name: the mtime moves
                if unused < idle:
                    continue
                shutil.rmtree(entry.path, ignore_errors=True)
            except OSError:  # removed meanwhile
                continue
            if not os.path.lexists(entry.path):
                removed += 1
                logger.info(
                    "Reference image cache: removed %s (another scope, unused for %.0f h)", entry.path, unused / 3600
                )
        for entry in _entries(self.directory):
            try:
                if _TEMP_NAME.match(entry.name) and now - entry.stat().st_mtime > older_than:
                    os.unlink(entry.path)
                    removed += 1
            except OSError:  # renamed into place or removed meanwhile
                continue
        return removed

    def prune(self, keep: set, written_before: float) -> int:
        """Remove this scope's views whose key is not in ``keep`` and that were written before ``written_before`` (a
        ``time.time()``): the warm-up's views of images the index no longer holds, once it has seen every image.
        Returns how many were removed."""
        if self.directory is None:
            return 0
        removed = 0
        for entry in _entries(self.directory):
            try:
                if (
                    _VIEW_NAME.match(entry.name)
                    and entry.name[:-4] not in keep
                    and entry.stat().st_mtime < written_before
                ):
                    os.unlink(entry.path)
                    removed += 1
            except OSError:  # replaced or removed meanwhile
                continue
        return removed

    def _warn_once(self, kind: str, message: str, *args) -> None:
        if kind not in self._warned:
            self._warned.add(kind)
            logger.warning("Reference image cache: " + message, *args)

    def _recall(self, key: str) -> Optional[str]:
        value = self._memory_get(key)
        if value is None and self.directory is not None:
            value = self._read(os.path.join(self.directory, key + ".b64"))
            if value is not None:
                self._remember(key, value)
        return value

    def _memory_get(self, key: str) -> Optional[str]:
        if self.memory_bytes <= 0:
            return None
        with self._lock:
            value = self._memory.get(key)
            if value is not None:
                self._memory.move_to_end(key)
            return value

    def _remember(self, key: str, value: str) -> None:
        size = len(value)
        if size > self.memory_bytes:  # also: memory off
            return
        with self._lock:
            old = self._memory.pop(key, None)
            if old is not None:
                self._memory_used -= len(old)
            self._memory[key] = value
            self._memory_used += size
            while self._memory_used > self.memory_bytes:
                _, evicted = self._memory.popitem(last=False)
                self._memory_used -= len(evicted)

    def _read(self, path: str) -> Optional[str]:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return None
        except Exception as e:
            self._warn_once("read", "cannot read %s (%s); preparing views per check", path, e)
            return None
        head, _, body = data.partition(b"\n")
        try:
            size, crc = head.split(b" ")
            if int(size) == len(body) and int(crc, 16) == zlib.crc32(body):
                return body.decode("ascii")
        except (ValueError, UnicodeDecodeError):
            pass
        self._warn_once("damaged", "%s is damaged; preparing the view again", path)
        return None

    def _room(self, directory: str, size: int) -> bool:
        """True while the scope stays under ``max_bytes`` and the disk keeps ``min_free_bytes``; both re-read from
        the disk every ``RECHECK_BYTES`` this process writes, or every ``RECHECK_SECONDS``. A re-read lists the scope's
        files outside the lock: hits and other writers go on with the numbers they have (only the first read, once
        per process, makes them wait)."""
        rescan = False
        with self._lock:
            if self._used is None:
                self._used, self._free = self.usage()[1], _free_bytes(directory)
                self._written_since, self._read_at = 0, time.monotonic()
            elif not self._scanning and (
                self._written_since >= RECHECK_BYTES or time.monotonic() - self._read_at >= RECHECK_SECONDS
            ):
                self._scanning = rescan = True
        if rescan:
            numbers = None
            try:
                numbers = self.usage()[1], _free_bytes(directory)
            finally:
                with self._lock:
                    if numbers is not None:
                        self._used, self._free = numbers
                    self._written_since, self._read_at, self._scanning = 0, time.monotonic(), False
        with self._lock:
            if self._used is None:  # the first read failed
                return False
            self.full = self._used + size > self.max_bytes or self._free - size < self.min_free_bytes
            if self.full:
                return False
            self._used += size
            self._free -= size
            self._written_since += size
            return True

    def _write(self, directory: str, key: str, value: str) -> bool:
        path = os.path.join(directory, key + ".b64")
        temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            body = value.encode("ascii")
            head = b"%d %08x\n" % (len(body), zlib.crc32(body))
            if not self._room(directory, len(head) + len(body)):
                self._warn_once(
                    "full",
                    "full (%d MiB of views, or under %d MiB free on the disk); new views are prepared per check",
                    self.max_bytes // MB,
                    self.min_free_bytes // MB,
                )
                return False
            try:
                fh = open(temp, "wb")
            except FileNotFoundError:
                os.makedirs(directory, exist_ok=True)
                fh = open(temp, "wb")
            with fh:
                fh.write(head)
                fh.write(body)
            os.replace(temp, path)
            return True
        except Exception as e:
            self._warn_once("write", "cannot write in %s (%s); views are prepared per check", directory, e)
            try:
                os.unlink(temp)
            except OSError:
                pass
            return False


def _entries(path: str) -> list:
    """The entries of a directory; none when it cannot be listed."""
    try:
        with os.scandir(path) as entries:
            return list(entries)
    except OSError:
        return []


def _free_bytes(path: str) -> int:
    """Free bytes on the disk that holds ``path`` (its nearest existing parent); 0 when unreadable: no writes."""
    try:
        while not os.path.exists(path) and os.path.dirname(path) != path:
            path = os.path.dirname(path)
        return shutil.disk_usage(path).free
    except OSError:
        return 0
