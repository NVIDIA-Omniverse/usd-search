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

"""Filesystem watcher that triggers reindexing via the info-endpoint /process/asset API."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image
from watchfiles import Change, awatch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("fs-watcher")

# 3D and material file extensions the USD Search pipeline can process.
_3D_EXTENSIONS: set[str] = {
    ".usd",
    ".usda",
    ".usdc",
    ".usdz",
    ".gltf",
    ".glb",
    ".fbx",
    ".obj",
    ".stl",
    ".ply",
    ".abc",
    ".mdl",
    ".mtlx",
}

# Image extensions: dynamically retrieved from Pillow's registry.
_IMAGE_EXTENSIONS: set[str] = {ex for ex, f in Image.registered_extensions().items() if f in Image.OPEN}

SUPPORTED_EXTENSIONS: set[str] = _3D_EXTENSIONS | _IMAGE_EXTENSIONS

# Directories to skip entirely.
SKIP_DIRS: set[str] = {".omniverse", ".git", "__pycache__", ".DS_Store"}


def _is_hidden(path: Path) -> bool:
    """Return True if any component of *path* starts with a dot."""
    return any(part.startswith(".") for part in path.parts)


def _is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def _should_skip(path: Path, watch_root: Path) -> bool:
    """Return True if the path should be ignored."""
    rel = path.relative_to(watch_root)
    # Skip hidden files/directories and known junk directories.
    if _is_hidden(rel):
        return True
    for part in rel.parts:
        if part in SKIP_DIRS:
            return True
    return False


def _build_s3_uri(path: Path, watch_root: Path, bucket: str) -> str:
    """Convert a local filesystem path to an S3 URI.

    Example:
        /watch/Projects/car.usd -> s3://usdsearch-local/Projects/car.usd
    """
    rel = path.relative_to(watch_root)
    # URL-encode path components but keep slashes.
    encoded = "/".join(quote(part, safe="") for part in rel.parts)
    return f"s3://{bucket}/{encoded}"


async def _trigger_reindex(
    client: httpx.AsyncClient,
    info_endpoint_url: str,
    s3_uri: str,
) -> None:
    """Call the info-endpoint /process/asset route to trigger reindexing."""
    url = f"{info_endpoint_url}/process/asset"
    try:
        resp = await client.get(url, params={"url": s3_uri})
        if resp.status_code == 200:
            logger.info("Reindex triggered: %s -> HTTP %d", s3_uri, resp.status_code)
        else:
            logger.warning(
                "Reindex request for %s returned HTTP %d: %s",
                s3_uri,
                resp.status_code,
                resp.text[:200],
            )
    except httpx.HTTPError as exc:
        logger.error("Reindex request failed for %s: %s", s3_uri, exc)


async def watch_loop(
    watch_dir: str,
    info_endpoint_url: str,
    bucket: str,
    debounce_ms: int,
) -> None:
    """Main watch loop: detect filesystem changes and trigger reindexing."""
    watch_root = Path(watch_dir)
    if not watch_root.is_dir():
        logger.error("Watch directory does not exist: %s", watch_dir)
        sys.exit(1)

    logger.info(
        "Watching %s for changes (bucket=%s, debounce=%dms, endpoint=%s)",
        watch_dir,
        bucket,
        debounce_ms,
        info_endpoint_url,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        async for changes in awatch(
            watch_root,
            debounce=debounce_ms,
            recursive=True,
            step=200,
        ):
            # Collect unique file paths that need reindexing.
            to_reindex: list[tuple[Path, str]] = []
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type == Change.deleted:
                    logger.info("File deleted (skipping reindex): %s", path)
                    continue
                if not path.is_file():
                    continue
                if _should_skip(path, watch_root):
                    continue
                if not _is_supported(path):
                    continue
                s3_uri = _build_s3_uri(path, watch_root, bucket)
                to_reindex.append((path, s3_uri))

            if not to_reindex:
                continue

            logger.info(
                "Detected %d file change(s), triggering reindex...",
                len(to_reindex),
            )
            for path, s3_uri in to_reindex:
                logger.info("  %s -> %s", path, s3_uri)
                await _trigger_reindex(client, info_endpoint_url, s3_uri)


def main() -> None:
    watch_dir = os.environ.get("WATCH_DIR", "/watch")
    info_endpoint_url = os.environ.get("INFO_ENDPOINT_URL", "http://info-endpoint:8000").rstrip("/")
    bucket = os.environ.get("S3_BUCKET_NAME", "usdsearch-local")
    debounce_ms = int(os.environ.get("DEBOUNCE_MS", "2000"))

    asyncio.run(watch_loop(watch_dir, info_endpoint_url, bucket, debounce_ms))


if __name__ == "__main__":
    main()
