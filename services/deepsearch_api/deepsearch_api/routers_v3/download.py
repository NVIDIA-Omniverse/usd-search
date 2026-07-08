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
import json
import logging
import os
import re
import tempfile
import zipfile
from typing import Annotated, Optional

from asset_graph_service_client.api.ags_asset_graph_api import AGSAssetGraphApi
from asset_graph_service_client.api_client import ApiClient
from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.routers_v2 import dependencies, service
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.requests import Request

from search_utils.storage_client import RemoteFileUri, StorageClient

router = APIRouter(
    tags=["Download"],
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Control characters (notably CR/LF) in request-derived values (asset URLs,
# exception text echoing them back) can forge or corrupt log lines (CWE-117).
# Neutralize them before logging user-controlled data.
_LOG_CTRL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _log_safe(value: object) -> str:
    """Strip control characters from a value so it cannot inject log lines."""
    return _LOG_CTRL_CHARS.sub(" ", str(value))


# Mirrors the AGS routers' access-verification toggle so the bundle honours the
# same ACL policy as the dependency-graph endpoints it builds on.
ENABLE_ACCESS_VERIFICATION = os.getenv("ENABLE_ACCESS_VERIFICATION", "true").lower() in ("true", "1")


class DownloadSettings(BaseSettings):
    """Tunables for the /download bundler (override via DOWNLOAD_* env vars)."""

    model_config = SettingsConfigDict(env_prefix="download_")

    # Max transitive dependencies to pull from the asset graph for one bundle
    # (None = unlimited, the default — some scenes legitimately reference more
    # than any fixed cap; set DOWNLOAD_MAX_DEPENDENCIES to bound it).
    max_dependencies: Optional[int] = None
    # Max dependency depth to traverse (None = unbounded).
    max_dependency_depth: Optional[int] = None
    # Concurrent per-file downloads while assembling the ZIP (env: DOWNLOAD_CONCURRENCY).
    concurrency: int = 8
    # Concurrent HEAD requests for the size-only (manifest_only) preview.
    size_check_concurrency: int = 16
    # Max total bundle size in bytes; 0 = unlimited (default).
    max_bundle_bytes: int = 0
    # Directory for the temp ZIP while assembling (None = system default). On
    # Kubernetes, point this at a mounted tmpfs/RAM volume for speed without
    # consuming the service's heap.
    temp_dir: Optional[str] = None


def _strip_scheme(uri: str) -> str:
    """Return the path portion of a storage URI (drop the `scheme://` prefix)."""
    return re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", uri)


def _common_dir_parts(paths: list[str]) -> list[str]:
    """Longest common leading directory segments across the given path strings.

    Used to lay files out in the zip relative to a shared root so that USD
    relative references between layers keep resolving after extraction.
    """
    if not paths:
        return []
    split = [p.split("/")[:-1] for p in paths]  # directory parts only (drop filename)
    common = split[0]
    for parts in split[1:]:
        i = 0
        while i < len(common) and i < len(parts) and common[i] == parts[i]:
            i += 1
        common = common[:i]
        if not common:
            break
    return common


def _arcname(uri: str, common_parts: list[str]) -> str:
    """In-zip path for a URI: its path with the shared directory prefix removed."""
    path = _strip_scheme(uri)
    parts = path.split("/")
    if common_parts and parts[: len(common_parts)] == common_parts:
        parts = parts[len(common_parts) :]
    arc = "/".join(p for p in parts if p)
    # Guard against pathological names that would escape the archive root.
    arc = arc.replace("..", "_").lstrip("/")
    return arc or path.rsplit("/", 1)[-1] or "asset"


async def _collect_dependency_uris(
    asset_url: str,
    async_ags_client: ApiClient,
    storage_client: StorageClient,
    settings: "DownloadSettings",
) -> tuple[list[str], dict]:
    """Return (uris, stats): the root asset plus every (ACL-allowed, non-deleted)
    transitive dependency, and a stats dict describing what was skipped.

    Falls back to just the root if the asset graph service is unavailable or the
    asset has not been graphed — a single-file bundle is still useful.

    stats keys:
      - dependencies_reported: total dependency entries returned by the graph
      - skipped_deleted: deps the graph marks as deleted
      - skipped_no_access_or_missing: deps the access check excluded (no
        permission OR the object does not exist — the check can't always tell
        these apart, hence the combined label)
      - skipped: list of {url, reason} for every excluded dependency
    """
    uris: list[str] = [asset_url]
    stats = {
        "dependencies_reported": 0,
        "skipped_deleted": 0,
        "skipped_no_access_or_missing": 0,
        "skipped": [],
    }
    try:
        asset_dependencies = await AGSAssetGraphApi(
            api_client=async_ags_client
        ).get_dependencies_flat_dependency_graph_flat_get(
            root_node_url=asset_url,
            max_level=settings.max_dependency_depth,
            limit=settings.max_dependencies,
        )
    except Exception as exc:  # noqa: BLE001 — AGS down / asset not graphed → root-only bundle
        logger.warning(
            "Could not fetch dependencies for %s; bundling root only: %s",
            _log_safe(asset_url),
            _log_safe(exc),
        )
        return uris, stats

    stats["dependencies_reported"] = len(asset_dependencies)

    dep_urls = []
    for a in asset_dependencies:
        if getattr(a, "deleted", False):
            stats["skipped_deleted"] += 1
            stats["skipped"].append({"url": a.url, "reason": "deleted"})
        else:
            dep_urls.append(a.url)

    if ENABLE_ACCESS_VERIFICATION and dep_urls:
        verified = set(await service.check_acl(dep_urls, storage_client))
        for u in dep_urls:
            if u not in verified:
                stats["skipped_no_access_or_missing"] += 1
                stats["skipped"].append({"url": u, "reason": "no_access_or_missing"})
        dep_urls = [u for u in dep_urls if u in verified]

    seen = {asset_url}
    for url in dep_urls:
        if url not in seen:
            seen.add(url)
            uris.append(url)
    return uris, stats


@router.get(
    "/download/asset",
    summary="Download an asset and its dependencies as a ZIP archive",
    description="Fetch a USD asset together with all of its transitive dependency files (sublayers, "
    "referenced USDs, textures) and return them as a single ZIP. Files are laid out relative to a "
    "shared root directory so the scene's relative references resolve after extraction. A "
    "`manifest.json` describing the bundle (root url, included files, any per-file errors) is added "
    "at the archive root. Works for every storage backend (S3, Nucleus, local-fs). If the asset has "
    "no recorded dependencies (or the asset graph is unavailable) a single-file archive is returned.",
    response_class=Response,
    responses={
        200: {
            "description": "ZIP archive containing the asset and its dependencies",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
        },
        403: {
            "description": "Access Denied",
            "content": {"application/json": {"example": {"detail": "Access denied"}}},
        },
        404: {
            "description": "Asset Not Found",
            "content": {"application/json": {"example": {"detail": "Asset 's3://bucket/asset.usd' not found"}}},
        },
    },
)
async def download_asset(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    request: Request,
    asset_url: Annotated[
        str,
        Query(description="The complete storage URL of the asset to download (e.g. s3://bucket/path/scene.usd)."),
    ],
    manifest_only: Annotated[
        bool,
        Query(
            description="If true, do not build the ZIP — return JSON describing the bundle "
            "(root url, file count, total size in bytes, per-file sizes, errors). Lets a UI show "
            "the bundle size before the user commits to the download."
        ),
    ] = False,
) -> Response:
    """Bundle an asset and its dependencies into a downloadable ZIP archive."""
    with tracer.start_as_current_span("download.asset", kind=SpanKind.SERVER) as span:
        span.set_attribute("asset_url", asset_url)

        storage_require_auth = request.app.global_settings.storage_require_auth
        settings: DownloadSettings = request.app.download_settings

        # ACL-gate the root asset (dependencies are filtered inside _collect_dependency_uris).
        if storage_require_auth:
            remote_file_uris: list[RemoteFileUri] = [asset_url]
            accessible = await service.check_acl(remote_file_uris, storage_client)
            if not accessible:
                raise HTTPException(status_code=403, detail="Access denied")

        uris, dep_stats = await _collect_dependency_uris(asset_url, async_ags_client, storage_client, settings)
        span.set_attribute("file_count", len(uris))
        span.set_attribute(
            "dependencies_skipped", dep_stats["skipped_deleted"] + dep_stats["skipped_no_access_or_missing"]
        )

        # Size-only mode: HEAD every file (no body transfer) and report the bundle
        # size so a UI can show it before the user commits to a full download.
        if manifest_only:
            head_semaphore = asyncio.Semaphore(settings.size_check_concurrency)

            async def _head(uri: str):
                async with head_semaphore:
                    try:
                        item = await storage_client.head_item(uri)
                        return uri, (item.size if item and item.size is not None else None), None
                    except Exception as exc:  # noqa: BLE001 — best-effort per file
                        return uri, None, str(exc)

            head_results = await asyncio.gather(*[_head(u) for u in uris])
            sized = [{"url": uri, "size": size} for uri, size, err in head_results if size is not None]
            head_errors = {uri: err for uri, size, err in head_results if size is None}
            # Mirror the full-download path: if the root asset itself is unretrievable,
            # 404 instead of returning a 200 "empty bundle" — both modes treat a missing
            # asset the same way.
            if not any(f["url"] == asset_url for f in sized):
                raise HTTPException(
                    status_code=404,
                    detail=f"Asset '{asset_url}' could not be retrieved: {head_errors.get(asset_url) or 'not found'}",
                )
            return JSONResponse(
                {
                    "root_url": asset_url,
                    "file_count": len(sized),
                    "total_size": sum(f["size"] for f in sized),
                    "files": sized,
                    "errors": head_errors,
                    "summary": {
                        "dependencies_reported": dep_stats["dependencies_reported"],
                        "accessible": len(sized),
                        "skipped_no_access_or_missing": dep_stats["skipped_no_access_or_missing"],
                        "skipped_deleted": dep_stats["skipped_deleted"],
                    },
                    "skipped": dep_stats["skipped"],
                }
            )

        max_bytes = settings.max_bundle_bytes  # 0 == unlimited

        # When a size cap is configured, HEAD the files first and reject early if
        # the known total already blows the budget (skipped entirely when
        # unlimited, so the common case pays no extra round-trips).
        if max_bytes > 0:
            head_sem = asyncio.Semaphore(settings.size_check_concurrency)

            async def _size(uri: str) -> int:
                async with head_sem:
                    try:
                        item = await storage_client.head_item(uri)
                        return item.size if item and item.size is not None else 0
                    except Exception:  # noqa: BLE001 — unknown size → caught by the download-time guard
                        return 0

            known_total = sum(await asyncio.gather(*[_size(u) for u in uris]))
            if known_total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Download bundle is too large ({known_total} bytes; limit is {max_bytes}).",
                )

        # Lay files out relative to a shared root computed from the planned set
        # (independent of which files ultimately download) so the layout is stable.
        common_parts = _common_dir_parts([_strip_scheme(u) for u in uris])

        # Download concurrently (bounded) and write each file into the ZIP as it
        # arrives, then drop its bytes — peak memory stays ~ concurrency × file
        # size rather than the whole bundle. The ZIP is assembled on disk
        # (configurable dir; mount tmpfs there on k8s) so the service never holds
        # the full archive in RAM.
        semaphore = asyncio.Semaphore(settings.concurrency)

        async def _fetch(uri: str):
            async with semaphore:
                try:
                    data = await storage_client.download_file_content(uri)
                    return uri, bytes(data), None
                except Exception as exc:  # noqa: BLE001 — best-effort per file
                    logger.warning("Failed to download %s: %s", _log_safe(uri), _log_safe(exc))
                    return uri, None, str(exc)

        # Assemble the ZIP on disk inside a TemporaryDirectory context so cleanup
        # is always guaranteed — on success, on error, and on size-cap rejection.
        # Peak RAM during assembly is ~concurrency × largest-file, not the whole
        # bundle. Once assembly finishes we read the completed ZIP into memory
        # before the context exits (so the temp dir can be cleaned up immediately)
        # and return it as a plain Response.
        used_names: set[str] = set()
        manifest_files: list[dict] = []
        errors: dict[str, str] = {}
        root_ok = False
        total_bytes = 0

        with tempfile.TemporaryDirectory(prefix="usdsearch-download-", dir=settings.temp_dir or None) as tmp_dir:
            zip_path = os.path.join(tmp_dir, "bundle.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for coro in asyncio.as_completed([_fetch(u) for u in uris]):
                    uri, data, err = await coro
                    if data is None:
                        errors[uri] = err
                        continue
                    if uri == asset_url:
                        root_ok = True
                    total_bytes += len(data)
                    if max_bytes > 0 and total_bytes > max_bytes:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Download bundle exceeded the size limit of {max_bytes} bytes.",
                        )
                    arc = _arcname(uri, common_parts)
                    # De-collision on the off chance two URIs map to the same arcname.
                    if arc in used_names:
                        stem, _, ext = arc.rpartition(".")
                        n = 1
                        while arc in used_names:
                            arc = f"{stem}_{n}.{ext}" if ext else f"{arc}_{n}"
                            n += 1
                    used_names.add(arc)
                    zf.writestr(arc, data)
                    manifest_files.append({"url": uri, "path": arc, "size": len(data)})
                    del data  # release the bytes before pulling the next file

            if not root_ok:
                raise HTTPException(
                    status_code=404,
                    detail=f"Asset '{asset_url}' could not be retrieved: {errors.get(asset_url, 'not found')}",
                )

            # Bundle summary so the user knows what was (and wasn't) included.
            summary = {
                "dependencies_reported": dep_stats["dependencies_reported"],
                "downloaded": len(manifest_files),  # includes the root asset
                "skipped_no_access_or_missing": dep_stats["skipped_no_access_or_missing"],
                "skipped_deleted": dep_stats["skipped_deleted"],
                "download_failed": len(errors),
            }
            manifest = {
                "root_url": asset_url,
                "file_count": len(manifest_files),
                "total_size": total_bytes,
                "files": manifest_files,
                "summary": summary,
                # Every file left out, with why. Download failures live in `errors`
                # (passed the access check but the fetch failed); access/missing and
                # deleted skips come from dependency resolution.
                "skipped": dep_stats["skipped"],
                "errors": errors,
            }
            # Reopen the ZipFile to append the manifest now that summary is final.
            with zipfile.ZipFile(zip_path, "a") as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            zip_bytes = open(zip_path, "rb").read()
            # TemporaryDirectory.__exit__ runs here, deleting the dir cleanly.

        root_stem = _strip_scheme(asset_url).rsplit("/", 1)[-1]
        root_stem = root_stem.rsplit(".", 1)[0] if "." in root_stem else root_stem
        filename = f"{root_stem or 'asset'}.zip"

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                # Counts-only summary so the UI can flag skipped files without
                # unzipping (the full per-file list stays in manifest.json).
                "X-Download-Summary": json.dumps(summary),
                # Same-origin via the gateway/proxy, but expose explicitly so a
                # direct cross-origin caller can read it too.
                "Access-Control-Expose-Headers": "X-Download-Summary, Content-Disposition",
            },
        )
