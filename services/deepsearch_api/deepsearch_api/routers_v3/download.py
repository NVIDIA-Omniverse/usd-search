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
import contextlib
import functools
import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Optional

from asset_graph_service_client.api.ags_asset_graph_api import AGSAssetGraphApi
from asset_graph_service_client.api_client import ApiClient
from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.routers_v2 import dependencies, service
from deepsearch_api.routers_v2.models import AssetUrl
from deepsearch_api.telemetry_decorator import telemetry_track_asset_load
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.requests import Request

from search_utils.asset_uri import is_search_path_uri, uri_path_spellings
from search_utils.storage_client import (
    RemoteFileUri,
    StorageClient,
    VerifyBatchAccessResponse,
)
from search_utils.url_mapping import (
    normalize_upstream_document,
    rewrite_response_document,
)

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


_NO_SIZE_REPORTED = "no_size_reported"
_NOT_FOUND = "not_found"
_MAX_REASON_CHARS = 200


def _error_status(exc: BaseException) -> str:
    """Report the status a storage failure carries, either itself or on the error it wraps."""
    for candidate in (exc, exc.__cause__):
        response = getattr(candidate, "response", None)
        if not isinstance(response, dict):
            continue
        error = response.get("Error")
        code = (error or {}).get("Code") or response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if code:
            return str(code)
    return ""


def _error_reason(exc: Exception) -> str:
    """Describe a failure even when the exception itself stringifies to nothing."""
    reason = type(exc).__name__
    message = _log_safe(exc).strip()[:_MAX_REASON_CHARS]
    if message:
        reason = f"{reason}: {message}"
    status = _error_status(exc)
    return f"{reason} ({status})" if status else reason


# Mirrors the AGS routers' access-verification toggle so the bundle honours the
# same ACL policy as the dependency-graph endpoints it builds on.
ENABLE_ACCESS_VERIFICATION = os.getenv("ENABLE_ACCESS_VERIFICATION", "true").lower() in ("true", "1")


class DownloadSettings(BaseSettings):
    """Tunables for the /download bundler (override via DOWNLOAD_* env vars)."""

    model_config = SettingsConfigDict(env_prefix="download_")

    # Max transitive dependencies to pull from the asset graph for one bundle;
    # 0 = unlimited (default) — some scenes legitimately reference more than any
    # fixed cap; set DOWNLOAD_MAX_DEPENDENCIES to bound it.
    max_dependencies: int = Field(0, ge=0)
    # Max dependency depth to traverse (None = unbounded).
    max_dependency_depth: Optional[int] = None
    # Concurrent per-file downloads while assembling the ZIP (env: DOWNLOAD_CONCURRENCY).
    concurrency: int = 8
    # Concurrent HEAD requests for the size-only (manifest_only) preview.
    size_check_concurrency: int = 16
    # Max total bundle size in bytes; 0 = unlimited (default).
    max_bundle_bytes: int = 0
    # Directory for the temp ZIP (None = system default). Must be disk-backed:
    # the archive is served from here, so it lives until the client finishes.
    temp_dir: Optional[str] = None
    # Bundle assemblies in flight per process (0 = unlimited); bounds temp_dir
    # usage at ~max_concurrent × max_bundle_bytes.
    max_concurrent: int = 4
    # Seconds to wait for a free slot before giving up with 503.
    queue_timeout: float = 60.0
    # Compression policy for archive members (env: DOWNLOAD_COMPRESSION):
    #   "auto"    — deflate, except members whose extension is already a
    #               compressed container (`stored_extensions`). The default.
    #   "deflate" — always deflate, the pre-1.5 behaviour.
    #   "stored"  — never compress; fastest, largest archive.
    compression: str = "auto"
    # Extensions stored uncompressed under "auto" (comma-separated, leading dot
    # optional). USD payloads are absent on purpose: .usda compresses well.
    stored_extensions: str = ".png,.jpg,.jpeg,.webp,.avif,.jxl,.gif,.mp4,.mov,.zip,.usdz,.gz,.bz2,.xz,.7z,.ktx2,.basis"
    # Emit a span per bundle member — the only thing covering body-transfer
    # time. One extra span per file; set false where scenes are huge.
    trace_files: bool = True
    # A dependency URL holding this placeholder names a set of UDIM tiles, not a
    # file. Graphs built before the builder expanded it record it verbatim; the
    # bundler then checks tiles udim_probe_first_tile..udim_probe_last_tile
    # (inclusive; one existence check each; four-digit tiles, 1001-9999) and
    # bundles those that exist.
    udim_token: str = Field("<UDIM>", min_length=1)
    udim_probe_first_tile: int = Field(1001, ge=1001, le=9999)
    udim_probe_last_tile: int = Field(1099, ge=1001, le=9999)

    @model_validator(mode="after")
    def _ordered_udim_range(self) -> "DownloadSettings":
        if self.udim_probe_first_tile > self.udim_probe_last_tile:
            raise ValueError("DOWNLOAD_UDIM_PROBE_FIRST_TILE must not exceed DOWNLOAD_UDIM_PROBE_LAST_TILE")
        return self


def _strip_scheme(uri: str) -> str:
    """Return the path portion of a storage URI (drop the `scheme://` prefix)."""
    return re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", uri)


def _stored_extension_set(settings: "DownloadSettings") -> frozenset[str]:
    """Normalized (lowercase, dot-prefixed) extension set from the settings string."""
    extensions = set()
    for raw in settings.stored_extensions.split(","):
        ext = raw.strip().lower()
        if not ext:
            continue
        extensions.add(ext if ext.startswith(".") else f".{ext}")
    return frozenset(extensions)


def _member_compress_type(arc: str, mode: str, stored_extensions: frozenset[str]) -> int:
    """ZIP compression method for one archive member."""
    if mode == "stored":
        return zipfile.ZIP_STORED
    if mode == "deflate":
        return zipfile.ZIP_DEFLATED
    return zipfile.ZIP_STORED if os.path.splitext(arc)[1].lower() in stored_extensions else zipfile.ZIP_DEFLATED


class _TempDirFileResponse(FileResponse):
    """A FileResponse that releases the directory and slot backing it, whatever happens."""

    def __init__(self, *args, cleanup_dir: str, on_close=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cleanup_dir = cleanup_dir
        self._on_close = on_close

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Not Starlette's `background=`: it awaits that only after a
            # successful send, so a cancelled download would leak the bundle.
            shutil.rmtree(self._cleanup_dir, ignore_errors=True)
            if self._on_close is not None:
                self._on_close()


# Process-wide cap on bundle assemblies. A slot is held for assembly *and* for
# the client's download, because the archive occupies temp_dir for both.
_bundle_slots: Optional[asyncio.Semaphore] = None
_bundle_slots_limit: Optional[int] = None


def _bundle_semaphore(limit: int) -> Optional[asyncio.Semaphore]:
    """The shared slot semaphore, or None when unlimited (limit <= 0)."""
    global _bundle_slots, _bundle_slots_limit
    if limit <= 0:
        return None
    if _bundle_slots is None or _bundle_slots_limit != limit:
        _bundle_slots = asyncio.Semaphore(limit)
        _bundle_slots_limit = limit
    return _bundle_slots


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


@contextlib.contextmanager
def _no_phase(_name: str):
    """Fallback for callers that do not supply a phase recorder (tests)."""
    yield None


async def _collect_dependency_uris(
    asset_url: str,
    async_ags_client: ApiClient,
    storage_client: StorageClient,
    settings: "DownloadSettings",
    phase=_no_phase,
) -> tuple[list[str], dict]:
    """Return (uris, stats): the root asset plus every (readable, non-deleted)
    transitive dependency, and a stats dict describing what was skipped.

    Falls back to just the root if the asset graph service is unavailable or the
    asset has not been graphed — a single-file bundle is still useful.

    stats keys:
      - dependencies_reported: total dependency entries returned by the graph
      - dependencies_truncated: the graph returned as many entries as
        `max_dependencies` allowed, so the bundle may be missing files
      - dependencies_unavailable: the graph could not be read at all, so the
        bundle holds the root asset alone and no dependency was even considered
      - skipped_deleted: deps the graph marks as deleted
      - skipped_not_found / skipped_access_denied: excluded, backend said which
      - skipped_no_access_or_missing: excluded by a backend that cannot separate
        "forbidden" from "absent" (Nucleus)
      - skipped_resolved_elsewhere: not storage objects at all
      - respelled: adopted under their percent-decoded URL (see below)
      - udim_expanded: ``<UDIM>`` placeholder URLs replaced by their existing tiles
      - skipped: list of {url, reason} for every excluded dependency
    """
    uris: list[str] = [asset_url]
    stats = {
        "dependencies_reported": 0,
        "dependencies_truncated": False,
        "dependencies_unavailable": False,
        "skipped_deleted": 0,
        "skipped_not_found": 0,
        "skipped_access_denied": 0,
        "skipped_no_access_or_missing": 0,
        "skipped_resolved_elsewhere": 0,
        "respelled": 0,
        "udim_expanded": 0,
        "skipped": [],
    }
    try:
        with phase("ags_graph_ms"):
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
        stats["dependencies_unavailable"] = True
        return uris, stats

    # AGS is gateway-exposed in its own right, so on a deployment that publishes
    # rewritten URLs it answers this call in the public form. Everything below
    # speaks the internal one: the ACL check and the HEADs go to the storage
    # client, and `_arcname` derives the in-archive layout from the URL's path —
    # a public root would share no common prefix with the internal one, scattering
    # the bundle and breaking the scene's relative references on extraction.
    asset_dependencies = normalize_upstream_document(asset_dependencies)

    stats["dependencies_reported"] = len(asset_dependencies)
    if settings.max_dependencies and stats["dependencies_reported"] >= settings.max_dependencies:
        stats["dependencies_truncated"] = True
        logger.warning(
            "Dependency list for %s hit the %d-entry cap; the bundle may be incomplete. "
            "Raise or unset DOWNLOAD_MAX_DEPENDENCIES.",
            _log_safe(asset_url),
            settings.max_dependencies,
        )

    def _skip(url: str, reason: str) -> None:
        stats[f"skipped_{reason}"] += 1
        stats["skipped"].append({"url": url, "reason": reason})

    dep_urls = []
    for a in asset_dependencies:
        if getattr(a, "deleted", False):
            _skip(a.url, service.SKIP_DELETED)
        elif is_search_path_uri(a.url):
            # An MDL module the runtime resolves from its own search path: nothing
            # to fetch, and a copy inside the archive would not be found anyway.
            _skip(a.url, service.SKIP_RESOLVED_ELSEWHERE)
        else:
            dep_urls.append(a.url)

    # Verdicts the UDIM probes already fetched; the access check reuses them.
    probe_verdicts: dict[str, VerifyBatchAccessResponse] = {}
    if dep_urls:
        with phase("udim_expand_ms"):
            tiles, probe_verdicts = await _expand_udim_patterns(dep_urls, storage_client, settings)
        if tiles:
            stats["udim_expanded"] = len(tiles)
            dep_urls = [tile for url in dep_urls for tile in tiles.get(url, [url])]

    if ENABLE_ACCESS_VERIFICATION and dep_urls:
        # Timed separately from the graph call: this is an existence/ACL check
        # per dependency (batched 500 at a time), and on a large scene it —
        # not the Asset Graph Service — is what `dependency_resolve_ms` is
        # mostly made of.
        with phase("dependency_acl_ms"):
            unchecked = [u for u in dep_urls if u not in probe_verdicts]
            verdicts = dict(probe_verdicts)
            if unchecked:
                verdicts.update(await service.check_access(unchecked, storage_client))
            missing = [u for u in dep_urls if _may_be_respelled(verdicts.get(u))]
            respelled = await _respell_missing(missing, storage_client) if missing else {}

        resolved = []
        for u in dep_urls:
            if u in verdicts and verdicts[u].exists:
                resolved.append(u)
            elif u in respelled:
                stats["respelled"] += 1
                resolved.append(respelled[u])
            else:
                _skip(u, service.skip_reason(verdicts.get(u)))
        dep_urls = resolved
    elif dep_urls:
        respelled = await _respell_unverified(dep_urls, storage_client, probe_verdicts, phase)
        if respelled:
            stats["respelled"] += len(respelled)
            dep_urls = [respelled.get(u, u) for u in dep_urls]

    seen = {asset_url}
    for url in dep_urls:
        if url not in seen:
            seen.add(url)
            uris.append(url)
    return uris, stats


#: A UDIM tile number, 1001-9999, as it appears in a listed file name.
_UDIM_TILE = r"(1\d{3}|[2-9]\d{3})"


async def _expand_udim_patterns(
    urls: list[str],
    storage_client: StorageClient,
    settings: "DownloadSettings",
) -> tuple[dict[str, list[str]], dict[str, VerifyBatchAccessResponse]]:
    """Map each ``<UDIM>`` dependency URL to the tile URLs that exist, in tile order.

    Nothing is stored under the literal placeholder, so a graph built before the
    builder expanded it (OMPE-119479) holds a URL that can never resolve, and the
    tiles the scene renders with are absent from the graph. A pattern with no
    existing tile is left out of the map, so it is still reported as skipped —
    the texture really is missing.

    As in the builder's ``expand_udim``, each texture folder is listed once.
    Only patterns whose folder cannot be listed, or lists no tile, fall back to
    probing ``udim_probe_first_tile..udim_probe_last_tile`` in one batch. The
    verdicts those probes fetched are returned too, so the access check that
    follows does not ask for them again.

    Each URL is tried under every spelling (``uri_path_spellings``): a graph built
    before ``graph_url`` can hold the path percent-encoded — the placeholder too,
    as ``%3CUDIM%3E`` — while the backend keys the tiles raw. Per tile, the first
    spelling found is kept, the original first, as ``_respell_missing`` does.
    """
    token = settings.udim_token
    patterns = {url: spellings for url in urls if (spellings := [s for s in uri_path_spellings(url) if token in s])}
    if not patterns:
        return {}, {}
    found = await _list_udim_tiles(patterns, storage_client, token)
    verdicts: dict[str, VerifyBatchAccessResponse] = {}
    unlisted = {url: spellings for url, spellings in patterns.items() if url not in found}
    if unlisted:
        probed, verdicts = await _probe_udim_tiles(unlisted, storage_client, settings)
        found.update(probed)
    if found:
        logger.info(
            "Bundled %d UDIM tile(s) for %d placeholder dependency URL(s) the asset graph stored verbatim, e.g. %s",
            sum(len(t) for t in found.values()),
            len(found),
            _log_safe(next(iter(found))),
        )
    return {url: found[url] for url in patterns if url in found}, verdicts


def _split_udim_spelling(spelling: str, token: str) -> Optional[tuple[str, str, str]]:
    """``(folder, prefix, suffix)`` around a placeholder in the file name, else ``None``."""
    folder, _, name = spelling.rpartition("/")
    if not folder or token not in name:
        return None
    prefix, _, suffix = name.partition(token)
    return folder, prefix, suffix


async def _list_udim_tiles(
    patterns: dict[str, list[str]], storage_client: StorageClient, token: str
) -> dict[str, list[str]]:
    """The tiles each pattern's folder listing holds, one listing per folder and prefix.

    A tile URL is the pattern's own spelling with the tile number filled in, so
    it keeps the URL form the graph uses even when the listing reports another
    (S3 lists ``s3://`` keys for an ``https://`` dependency).
    """
    listings = {
        (parts[0], f"{parts[0]}/{parts[1]}"): None
        for spellings in patterns.values()
        for spelling in spellings
        if (parts := _split_udim_spelling(spelling, token))
    }
    names = dict(
        zip(
            listings,
            await asyncio.gather(*(_listed_names(storage_client, folder, prefix) for folder, prefix in listings)),
        )
    )
    found: dict[str, list[str]] = {}
    for url, spellings in patterns.items():
        tiles: dict[int, str] = {}
        for spelling in spellings:  # the original spelling first: it wins a tile both spell
            if not (parts := _split_udim_spelling(spelling, token)):
                continue
            folder, prefix, suffix = parts
            tile = re.compile(re.escape(prefix) + _UDIM_TILE + re.escape(suffix))
            for name in names.get((folder, f"{folder}/{prefix}")) or ():
                if match := tile.fullmatch(name):
                    tiles.setdefault(int(match.group(1)), spelling.replace(token, match.group(1), 1))
        if tiles:
            found[url] = [tiles[n] for n in sorted(tiles)]
    return found


async def _listed_names(storage_client: StorageClient, folder_uri: str, literal_prefix_uri: str) -> Optional[set[str]]:
    """File names directly inside ``folder_uri`` the backend lists, or ``None`` if it cannot list it."""
    folder = folder_uri.rpartition("/")[2]
    names: set[str] = set()
    try:
        async for uri in storage_client.list_uris_with_prefix(
            literal_prefix_uri=literal_prefix_uri, folder_uri=folder_uri
        ):
            parent, _, name = uri.rstrip("/").rpartition("/")
            # A prefix listing (S3) also reaches keys in subfolders that share the prefix.
            if parent.rpartition("/")[2] == folder:
                names.add(name)
    except Exception as exc:  # noqa: BLE001 — an unlistable folder falls back to probing
        logger.debug("Could not list %s for UDIM tiles: %s", _log_safe(folder_uri), _log_safe(exc))
        return None
    return names


async def _probe_udim_tiles(
    patterns: dict[str, list[str]], storage_client: StorageClient, settings: "DownloadSettings"
) -> tuple[dict[str, list[str]], dict[str, VerifyBatchAccessResponse]]:
    """Check the configured tile range under every spelling, in one batch, and return the verdicts too."""
    token = settings.udim_token
    tile_numbers = range(settings.udim_probe_first_tile, settings.udim_probe_last_tile + 1)
    # (url, tile) -> that tile under each spelling, in preference order.
    tiles = {
        (url, n): [spelling.replace(token, str(n), 1) for spelling in spellings]
        for url, spellings in patterns.items()
        for n in tile_numbers
    }
    verdicts = await service.check_access(list({c: None for cs in tiles.values() for c in cs}), storage_client)
    found: dict[str, list[str]] = {}
    for (url, _), candidates in tiles.items():
        for candidate in candidates:
            verdict = verdicts.get(candidate)
            # A tile that exists but is unreadable still counts: the access check
            # that follows then reports it as access_denied instead of dropping it.
            if verdict is not None and (verdict.exists or verdict.access_denied is True):
                found.setdefault(url, []).append(candidate)
                break
    return found, verdicts


#: Every `skipped_*` counter, in the order a bundle summary reports them.
_SKIP_COUNTERS = (
    "skipped_not_found",
    "skipped_access_denied",
    "skipped_no_access_or_missing",
    "skipped_deleted",
    "skipped_resolved_elsewhere",
)


def _bundle_summary(dep_stats: dict, downloaded: int, failed: int) -> dict:
    """The per-bundle summary shared by the preview, the manifest and the header."""
    return {
        "dependencies_reported": dep_stats["dependencies_reported"],
        "dependencies_truncated": dep_stats["dependencies_truncated"],
        "dependencies_unavailable": dep_stats["dependencies_unavailable"],
        "downloaded": downloaded,  # includes the root asset
        **{key: dep_stats[key] for key in _SKIP_COUNTERS},
        "respelled": dep_stats["respelled"],
        "download_failed": failed,
    }


def _may_be_respelled(verdict) -> bool:
    """Whether a dependency that did not resolve may be looked up under another spelling.

    Not when the backend said the object *is* there and unreadable: the decoded
    spelling would then be a different object, and bundling it would quietly swap
    one dependency for another. ``None`` — the backend cannot tell absent from
    forbidden, which is every non-S3 backend — stays eligible, because that doubt
    is exactly what this fallback exists to resolve.
    """
    if verdict is None:
        return True
    return not verdict.exists and verdict.access_denied is not True


async def _respell_missing(
    missing: list[str],
    storage_client: StorageClient,
) -> dict[str, str]:
    """Map dependency URLs that did not resolve to a spelling that does.

    A graph built before `graph_url` can hold a dependency percent-encoded while
    the storage backend keys it raw, so it resolves under neither. Decoding
    unconditionally would break keys that really contain an escape such as
    ``%20``, so the alternative spelling is adopted only when it exists.
    """
    candidates = {}
    for url in missing:
        for spelling in uri_path_spellings(url):
            if spelling != url:
                candidates[spelling] = url
    if not candidates:
        return {}

    verdicts = await service.check_access(list(candidates), storage_client)
    adopted = {}
    for spelling, original in candidates.items():
        verdict = verdicts.get(spelling)
        if verdict is not None and verdict.exists and original not in adopted:
            adopted[original] = spelling
    if adopted:
        # INFO, not DEBUG: each hit is a graph node stored under a key that does
        # not exist, and the count is the only signal that the graph needs rebuilding.
        logger.info(
            "Adopted %d respelled dependency URL(s) the asset graph stored percent-encoded, e.g. %s -> %s",
            len(adopted),
            *[_log_safe(x) for x in next(iter(adopted.items()))],
        )
    return adopted


async def _respell_unverified(
    urls: list[str],
    storage_client: StorageClient,
    probe_verdicts: dict[str, VerifyBatchAccessResponse],
    phase,
) -> dict[str, str]:
    """Map dependency URLs to a spelling that resolves, when no ACL pass checked them."""
    candidates = [url for url in urls if len(uri_path_spellings(url)) > 1]
    if not candidates:
        return {}
    with phase("dependency_acl_ms"):
        verdicts = {url: probe_verdicts[url] for url in candidates if url in probe_verdicts}
        unchecked = [url for url in candidates if url not in verdicts]
        if unchecked:
            verdicts.update(await service.check_access(unchecked, storage_client))
        missing = [url for url in candidates if _may_be_respelled(verdicts.get(url))]
        return await _respell_missing(missing, storage_client) if missing else {}


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
@telemetry_track_asset_load()
async def download_asset(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    request: Request,
    asset_url: Annotated[
        AssetUrl,
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
    # INTERNAL, not SERVER: this span is nested inside the one FastAPIInstrumentor
    # already opens for the request. Two SERVER spans in a trace make Tempo/Jaeger
    # service graphs and Elastic APM read the inner one as a separate inbound
    # transaction and mis-attribute parent/child durations.
    with tracer.start_as_current_span("download.asset", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("asset_url", asset_url)

        # Telemetry stats for the asset-load event. Filled in phase by phase (not
        # assembled at return) so a request that fails part-way — 403 before any
        # work, 413 after the size check — still reports what the phases that ran
        # cost. `telemetry_track_asset_load` reads this off request.state.
        stats: dict = {}
        request.state.asset_load_stats = stats

        def _record_phase(name: str, started: float) -> None:
            """Stamp a phase duration onto both the request span and the event."""
            elapsed_ms = (time.perf_counter() - started) * 1000
            stats[name] = elapsed_ms
            # Business telemetry runs on its own TracerProvider, so mirror the
            # timings here too or traces and telemetry disagree.
            span.set_attribute(name, elapsed_ms)

        def _record_metric(name: str, value, phase_span=None) -> None:
            """Stamp a non-timing measurement onto the event and the span(s)."""
            stats[name] = value
            span.set_attribute(name, value)
            if phase_span is not None:
                phase_span.set_attribute(name, value)

        @contextlib.contextmanager
        def _phase(name: str):
            """Time a phase, as a child span and as an attribute on the span and the event."""
            started = time.perf_counter()
            try:
                with tracer.start_as_current_span(f"download.{name.removesuffix('_ms')}") as phase_span:
                    yield phase_span
            finally:
                # In a finally so a phase that raises (413 mid-collect, 404 just
                # after it) still reports what it cost.
                _record_phase(name, started)

        storage_require_auth = request.app.global_settings.storage_require_auth
        settings: DownloadSettings = request.app.download_settings

        # ACL-gate the root asset (dependencies are filtered inside _collect_dependency_uris).
        if storage_require_auth:
            # Timed: it is a storage round trip, and until now it sat before the
            # first phase, so a slow backend showed up only as an unexplained
            # head start on the request span.
            with _phase("acl_check_ms"):
                remote_file_uris: list[RemoteFileUri] = [asset_url]
                verdicts = await service.check_access(remote_file_uris, storage_client)
            root = verdicts.get(asset_url)
            if root is None or not root.exists:
                # Only call it denied when the backend said the object is there.
                # A root the backend can see is absent is a 404 — answering 403
                # sends the caller looking for a permission they already have.
                if root is not None and root.access_denied is False:
                    raise HTTPException(status_code=404, detail="Asset not found")
                raise HTTPException(status_code=403, detail="Access denied")

        # `dependency_resolve_ms` stays the total, for continuity with existing
        # dashboards; `ags_graph_ms` and `dependency_acl_ms` break it down.
        with _phase("dependency_resolve_ms"):
            uris, dep_stats = await _collect_dependency_uris(
                asset_url, async_ags_client, storage_client, settings, phase=_phase
            )
        stats["dependencies_reported"] = dep_stats["dependencies_reported"]
        stats["dependencies_truncated"] = dep_stats["dependencies_truncated"]
        stats["dependencies_unavailable"] = dep_stats["dependencies_unavailable"]
        # Unchanged meaning — every non-deletion skip — so existing dashboards stay
        # valid; the new counters break it down without replacing it.
        stats["n_skipped_no_access"] = (
            dep_stats["skipped_not_found"]
            + dep_stats["skipped_access_denied"]
            + dep_stats["skipped_no_access_or_missing"]
        )
        stats["n_skipped_deleted"] = dep_stats["skipped_deleted"]
        stats["n_skipped_resolved_elsewhere"] = dep_stats["skipped_resolved_elsewhere"]
        stats["n_respelled"] = dep_stats["respelled"]
        stats["n_udim_expanded"] = dep_stats["udim_expanded"]
        span.set_attribute("file_count", len(uris))
        span.set_attribute("dependencies_skipped", sum(dep_stats[key] for key in _SKIP_COUNTERS))
        for key in _SKIP_COUNTERS:
            span.set_attribute(key, dep_stats[key])
        span.set_attribute("dependencies_respelled", dep_stats["respelled"])
        span.set_attribute("dependencies_udim_expanded", dep_stats["udim_expanded"])
        span.set_attribute("dependencies_truncated", dep_stats["dependencies_truncated"])
        span.set_attribute("dependencies_unavailable", dep_stats["dependencies_unavailable"])

        # Size-only mode: HEAD every file (no body transfer) and report the bundle
        # size so a UI can show it before the user commits to a full download.
        if manifest_only:
            head_semaphore = asyncio.Semaphore(settings.size_check_concurrency)

            async def _head(uri: str):
                async with head_semaphore:
                    try:
                        item = await storage_client.head_item(uri)
                        if item is None:
                            return uri, None, _NOT_FOUND
                        if item.size is None:
                            return uri, None, _NO_SIZE_REPORTED
                        return uri, item.size, None
                    except Exception as exc:  # noqa: BLE001 — best-effort per file
                        return uri, None, _error_reason(exc)

            with _phase("size_check_ms"):
                head_results = await asyncio.gather(*[_head(u) for u in uris])
            sized = [{"url": uri, "size": size} for uri, size, err in head_results if size is not None]
            head_errors = {uri: err for uri, size, err in head_results if size is None}
            # Counts describe what *would* be transferred — this path moves no
            # asset bytes. Recorded before the 404 below so a failed preview
            # still reports what the HEAD pass found.
            stats["n_files"] = len(sized)
            stats["total_bytes"] = sum(f["size"] for f in sized)
            stats["n_failed"] = len(head_errors)
            # Mirror the full-download path: if the root asset itself is unretrievable,
            # 404 instead of returning a 200 "empty bundle" — both modes treat a missing
            # asset the same way.
            if not any(f["url"] == asset_url for f in sized):
                raise HTTPException(
                    status_code=404,
                    detail=f"Asset '{asset_url}' could not be retrieved: {head_errors.get(asset_url) or 'not found'}",
                )
            return JSONResponse(
                rewrite_response_document(
                    {
                        "root_url": asset_url,
                        "file_count": len(sized),
                        "total_size": sum(f["size"] for f in sized),
                        "files": sized,
                        "errors": head_errors,
                        "summary": {
                            **_bundle_summary(dep_stats, downloaded=len(sized), failed=len(head_errors)),
                            "accessible": len(sized),
                        },
                        "skipped": dep_stats["skipped"],
                    }
                )
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

            with _phase("size_check_ms"):
                known_total = sum(await asyncio.gather(*[_size(u) for u in uris]))
            if known_total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Download bundle is too large ({known_total} bytes; limit is {max_bytes}).",
                )

        # From here the request occupies temp_dir until its client has finished.
        # Deliberately after the preview and size-cap paths: neither writes
        # anything, so neither should wait for, or consume, a slot.
        slots = _bundle_semaphore(settings.max_concurrent)
        slot_held = False

        def _release_slot() -> None:
            nonlocal slot_held
            if slot_held:
                slot_held = False
                slots.release()

        if slots is not None:
            try:
                with _phase("queue_wait_ms"):
                    await asyncio.wait_for(slots.acquire(), timeout=settings.queue_timeout)
            except (asyncio.TimeoutError, TimeoutError):
                raise HTTPException(
                    status_code=503,
                    detail="Too many downloads in progress; retry shortly.",
                    headers={"Retry-After": "30"},
                )
            slot_held = True

        # Lay files out relative to a shared root computed from the planned set
        # (independent of which files ultimately download) so the layout is stable.
        common_parts = _common_dir_parts([_strip_scheme(u) for u in uris])

        # Download concurrently (bounded) and write each file into the ZIP as it
        # arrives, then drop its bytes — peak memory stays ~ concurrency × file
        # size rather than the whole bundle. The ZIP is assembled on disk
        # (configurable dir; mount tmpfs there on k8s) so the service never holds
        # the full archive in RAM.
        semaphore = asyncio.Semaphore(settings.concurrency)
        # Per-file wall clock. Summed and maxed onto the collect span below:
        # `fetch_wait_ms` is how long the consumer loop sat blocked, which with
        # concurrent fetches is ~the whole phase and says nothing about overlap.
        # The sum against the phase wall clock is what shows the concurrency.
        fetch_durations: list[float] = []

        @contextlib.contextmanager
        def _fetch_span(uri: str):
            if not settings.trace_files:
                yield None
                return
            with tracer.start_as_current_span("download.fetch") as span:
                span.set_attribute("asset_url", uri)
                yield span

        async def _fetch(uri: str):
            async with semaphore:
                # Spans the whole fetch, unlike the storage client's HTTP span,
                # which ends at response headers — the difference between the two
                # is body-transfer time.
                started = time.perf_counter()
                with _fetch_span(uri) as fetch_span:
                    try:
                        data = bytes(await storage_client.download_file_content(uri))
                        if fetch_span is not None:
                            fetch_span.set_attribute("bytes", len(data))
                        return uri, data, None
                    except Exception as exc:  # noqa: BLE001 — best-effort per file
                        logger.warning("Failed to download %s: %s", _log_safe(uri), _log_safe(exc))
                        if fetch_span is not None:
                            fetch_span.set_attribute("error_type", type(exc).__name__)
                        return uri, None, _error_reason(exc)
                    finally:
                        fetch_durations.append((time.perf_counter() - started) * 1000)

        # Assemble the ZIP on disk. Peak RAM during assembly is ~concurrency ×
        # largest-file, and the finished archive is now streamed straight off
        # disk instead of being read back into memory, so peak RSS no longer
        # scales with bundle size at all.
        #
        # The temp dir therefore has to outlive this handler: the response removes
        # it once the body has been sent, and the `except BaseException` below
        # removes it on every path that returns no response.
        used_names: set[str] = set()
        manifest_files: list[dict] = []
        errors: dict[str, str] = {}
        root_ok = False
        total_bytes = 0
        compress_ms = 0.0
        fetch_wait_ms = 0.0
        n_stored = 0
        n_deflated = 0

        compression = settings.compression.strip().lower()
        stored_extensions = _stored_extension_set(settings)
        loop = asyncio.get_running_loop()

        tmp_dir = tempfile.mkdtemp(prefix="usdsearch-download-", dir=settings.temp_dir or None)
        try:
            zip_path = os.path.join(tmp_dir, "bundle.zip")
            with _phase("collect_ms") as collect_span:
                try:
                    # One writer thread: ZipFile is not thread-safe, so members
                    # are written in series — but off the event loop, so deflate
                    # no longer stalls every other request on the worker.
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="usdsearch-zip") as zip_executor:
                        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                            for coro in asyncio.as_completed([_fetch(u) for u in uris]):
                                fetch_wait_started = time.perf_counter()
                                uri, data, err = await coro
                                fetch_wait_ms += (time.perf_counter() - fetch_wait_started) * 1000
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
                                compress_type = _member_compress_type(arc, compression, stored_extensions)
                                if compress_type == zipfile.ZIP_STORED:
                                    n_stored += 1
                                else:
                                    n_deflated += 1
                                compress_started = time.perf_counter()
                                await loop.run_in_executor(
                                    zip_executor,
                                    functools.partial(zf.writestr, arc, data, compress_type=compress_type),
                                )
                                compress_ms += (time.perf_counter() - compress_started) * 1000
                                manifest_files.append({"url": uri, "path": arc, "size": len(data)})
                                del data  # release the bytes before pulling the next file
                finally:
                    # Also on the 413 above: how long the bundle took to collect
                    # before it blew the budget is exactly the interesting part.
                    stats["n_files"] = len(manifest_files)
                    stats["total_bytes"] = total_bytes
                    stats["n_failed"] = len(errors)
                    # `collect_ms` on its own cannot say whether a slow bundle was
                    # the backend or the zip. These split it: `fetch_wait_ms` is
                    # time blocked on storage, `compress_ms` time in the writer.
                    _record_metric("fetch_wait_ms", fetch_wait_ms, collect_span)
                    _record_metric("compress_ms", compress_ms, collect_span)
                    _record_metric("n_stored", n_stored, collect_span)
                    _record_metric("n_deflated", n_deflated, collect_span)
                    if fetch_durations:
                        # `fetch_total_ms` well above `collect_ms` means the
                        # fetches overlapped; close to it means they serialized.
                        # `fetch_max_ms` is the straggler that set the phase.
                        _record_metric("fetch_total_ms", sum(fetch_durations), collect_span)
                        _record_metric("fetch_max_ms", max(fetch_durations), collect_span)

            if not root_ok:
                raise HTTPException(
                    status_code=404,
                    detail=f"Asset '{asset_url}' could not be retrieved: {errors.get(asset_url, 'not found')}",
                )

            # Now only the manifest: the archive is no longer read back into
            # memory here, so this phase is cheap where it used to carry a
            # synchronous full-file read.
            with _phase("finalize_ms"):
                # Bundle summary so the user knows what was (and wasn't) included.
                summary = _bundle_summary(dep_stats, downloaded=len(manifest_files), failed=len(errors))
                # The manifest travels with the archive, so it carries the public URL
                # form too — a user who unzips it must see the same addresses the API
                # gave them. `arc` paths are derived from the internal URIs above and
                # stay as they are: they describe the layout on disk, not an address.
                manifest = rewrite_response_document(
                    {
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
                )
                # Reopen the ZipFile to append the manifest now that summary is final.
                with zipfile.ZipFile(zip_path, "a") as zf:
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        except BaseException:
            # No response will be returned, so nothing else will free these.
            # BaseException rather than Exception: a client that disconnects
            # mid-bundle cancels this task, and one leaked temp dir (and slot)
            # per cancelled download eventually fills the volume.
            shutil.rmtree(tmp_dir, ignore_errors=True)
            _release_slot()
            raise

        root_stem = _strip_scheme(asset_url).rsplit("/", 1)[-1]
        root_stem = root_stem.rsplit(".", 1)[0] if "." in root_stem else root_stem
        filename = f"{root_stem or 'asset'}.zip"

        # Streamed off disk rather than buffered in RAM. Passing `filename` makes
        # FileResponse set Content-Disposition itself — do not also pass one in
        # `headers`, that emits the header twice.
        return _TempDirFileResponse(
            zip_path,
            media_type="application/zip",
            filename=filename,
            headers={
                # Counts-only summary so the UI can flag skipped files without
                # unzipping (the full per-file list stays in manifest.json).
                "X-Download-Summary": json.dumps(summary),
                # Same-origin via the gateway/proxy, but expose explicitly so a
                # direct cross-origin caller can read it too.
                "Access-Control-Expose-Headers": "X-Download-Summary, Content-Disposition",
            },
            cleanup_dir=tmp_dir,
            # The slot is held until the body has been sent, because that is how
            # long the archive occupies temp_dir.
            on_close=_release_slot,
        )
