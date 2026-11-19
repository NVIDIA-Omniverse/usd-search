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

"""Fill the VLM validation reference image cache before checks need it.

``nice -n 10 python -m deepsearch_api.validation.warm_image_cache [--threads N] [--wait SECONDS]``, run with the API's
environment (in each replica: an emptyDir is the pod's own): every image of the image cache index, loaded as a check
loads it (``OpenSearchImageLoader.load_images``) and prepared through ``Validation.prepare_reference_images``, the
path a check takes, so the cache holds exactly what a check would write. It first removes what earlier runs left in
the cache directory (other settings' directories nothing writes in any more, stale temp files) and, after a run that
saw every image, the views of images the index no longer holds. It stops when the cache is full (the cache never
evicts: raise max_mb to keep the rest). The API processes read and fill the same directory on their own, so nothing
waits on this: run it beside them, niced. Exits 0 when done, full, or with nothing to do; 1 when it stopped early
(checks prepare the rest as they go).
"""

import argparse
import asyncio
import contextlib
import functools
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from llm_client import Validation
from llm_client.validation.image_cache import ReferenceImageCache

from .config import ValidationSettings

logger = logging.getLogger(__name__)

# Batches in a row that come back without one image: the index is not answering (the loader logs and returns none).
EMPTY_BATCHES = 3


async def fill(
    validation: Validation,
    loader,
    threads: int = 1,
    batch: int = 25,
    page: int = 500,
    report: Optional[Callable[[dict], None]] = None,
    every: float = 60.0,
) -> dict:
    """Prepare every image of ``loader``'s index through ``validation.prepare_reference_images``.

    Ids come from ``loader.image_ids`` (a scroll), images from ``loader.load_images`` in batches of ``batch``, and up
    to ``threads`` views are prepared at once in threads; ``report(counts)`` is called every ``every`` seconds.
    Returns ``{"images", "missing", "failed", "full", "complete", "keys"}``: images prepared or found, ids without
    an image, images that could not be prepared (as a check would fail on them), whether the cache is full (it stops
    at the next batch), whether it saw every image, and the keys of the images it saw. Raises when the index fails,
    or when ``EMPTY_BATCHES`` batches in a row bring no image.
    """
    counts: dict = {"images": 0, "missing": 0, "failed": 0, "full": False, "complete": False, "keys": set()}
    cache = validation.image_cache
    loop = asyncio.get_running_loop()
    slots = asyncio.Semaphore(threads * 2)  # images held at once: a few batches, never the whole index
    pending: set = set()
    empty = 0
    reported = time.monotonic()

    def done(future) -> None:  # on the loop's thread
        slots.release()
        pending.discard(future)
        if future.cancelled() or future.exception() is not None:
            counts["failed"] += 1

    with ThreadPoolExecutor(threads, thread_name_prefix="warm-image-cache") as pool:

        async def prepare(ids: list) -> None:
            nonlocal empty
            images = await loader.load_images(ids)
            found = 0
            for image_id in ids:
                image = images.get(image_id)
                if not isinstance(image, str) or not image:
                    counts["missing"] += 1
                    continue
                found += 1
                counts["images"] += 1
                counts["keys"].add(ReferenceImageCache.key(image))
                await slots.acquire()
                future = loop.run_in_executor(pool, validation.prepare_reference_images, [image])
                pending.add(future)
                future.add_done_callback(done)
            empty = 0 if found else empty + 1
            if empty >= EMPTY_BATCHES:
                raise RuntimeError(f"{EMPTY_BATCHES} batches in a row brought no image: is the image index answering?")

        try:
            ids: list = []
            async with contextlib.aclosing(loader.image_ids(page=page)) as image_ids:
                async for image_id in image_ids:
                    ids.append(image_id)
                    if len(ids) < batch:
                        continue
                    await prepare(ids)
                    ids = []
                    if cache is not None and cache.full:  # the rest would be prepared for nothing
                        break
                    if report is not None and time.monotonic() - reported >= every:
                        report(counts)
                        reported = time.monotonic()
                else:
                    if ids:
                        await prepare(ids)
                    counts["complete"] = True
        finally:
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
    counts["full"] = cache is not None and cache.full
    return counts


def _open_loader():
    """The image loader the API builds, from the same environment."""
    from ..routers_v2.dependencies import build_image_loader
    from ..search_backend.main import SearchSettings

    return build_image_loader(SearchSettings())


async def _wait_for_index(loader, wait: float) -> int:
    """The index's image count, asked again with backoff for up to ``wait`` seconds (OpenSearch may be starting)."""
    deadline = time.monotonic() + wait
    delay = 1.0
    while True:
        try:
            return await loader.image_count()
        except Exception:
            if time.monotonic() + delay > deadline:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * 2, 15.0)


async def _fill_index(
    validation: Validation, cache: ReferenceImageCache, threads: int, wait: float, say: Callable[[str], None]
) -> dict:
    loader = _open_loader()
    if not hasattr(loader, "image_ids"):
        raise RuntimeError(f"{type(loader).__name__} has no image index to read")
    try:
        total = await _wait_for_index(loader, wait)
        started = time.monotonic()

        def report(counts: dict) -> None:
            c = cache.counts
            rate = counts["images"] / max(time.monotonic() - started, 1e-9)
            say(
                f"{counts['images']} of {total} images ({c['written']} written, {c['not_kept']} not kept), "
                f"{rate:.0f} images/s"
            )

        counts = await fill(validation, loader, threads=threads, report=report)
        counts["total"] = total
        return counts
    finally:
        client = getattr(loader, "client", None)
        if client is not None:
            await client.close()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m deepsearch_api.validation.warm_image_cache",
        description="Fill the VLM validation reference image cache (USDSEARCH_VISION_VALIDATION_IMAGE_CACHE_DIR) "
        "from the image cache index.",
    )
    parser.add_argument(
        "--threads", type=int, default=1, help="views prepared at once (default 1: it shares the API's CPU)"
    )
    parser.add_argument(
        "--wait", type=float, default=300.0, help="seconds to wait for the image index to answer (default 300)"
    )
    args = parser.parse_args(argv)
    say = functools.partial(print, "warm_image_cache:", flush=True)

    settings = ValidationSettings()
    if not settings.enabled:
        say("vision validation is off: nothing to do")
        return 0
    if not settings.image_cache_dir:
        say("the reference image cache is off (USDSEARCH_VISION_VALIDATION_IMAGE_CACHE_DIR is empty): nothing to do")
        return 0
    validation = Validation(config=settings.to_validation_config())
    cache = validation.image_cache
    if cache is None:
        say("the reference image cache is off (see the warning above): nothing to do")
        return 0
    swept = cache.sweep()
    say(f"filling {cache.describe()}")
    started, wall, cpu = time.monotonic(), time.time(), time.process_time()
    try:
        counts = asyncio.run(_fill_index(validation, cache, max(1, args.threads), max(0.0, args.wait), say))
    except Exception as e:
        say(f"stopped ({type(e).__name__}: {e}); checks prepare the rest as they go")
        return 1
    if counts["complete"]:  # every image seen: views of images no longer stored go (not those written meanwhile)
        swept += cache.prune(counts["keys"], written_before=wall)
    if counts["full"]:
        say(
            f"the cache is full after {counts['images']} of {counts['total']} images; the rest are prepared per "
            f"check (raise USDSEARCH_VISION_VALIDATION_IMAGE_CACHE_MAX_MB to keep them)"
        )
    files, size = cache.usage()
    c = cache.counts
    say(
        f"{counts['images']} images in {time.monotonic() - started:.1f} s ({time.process_time() - cpu:.1f} CPU-s): "
        f"{c['written']} written, {c['hit']} already there, {c['not_kept']} not kept, {counts['failed']} failed, "
        f"{counts['missing']} ids without an image; {files} files, {size / 1e6:.0f} MB in {cache.directory} "
        f"({swept} old entries removed)"
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("llm_client.validation.image_cache").setLevel(logging.INFO)  # each directory it removes
    sys.exit(main())
