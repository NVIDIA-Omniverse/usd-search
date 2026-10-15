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
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import orjson
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, FastAPI, Request, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from .failures import (
    GraphBuildError,
    GraphBuildReason,
    memory_limit_watcher,
    reason_for_exit_code,
)
from .redaction import redact_url
from .timings import TIMINGS_PATH_ENV, read_timings

# Per-phase build timings ride on a response header rather than in the body: the
# success body is the graph document, which is forwarded verbatim to the Asset
# Graph Service, and build telemetry has no business in a stored graph. A header
# keeps one mechanism for both the success and failure paths.
TIMINGS_HEADER = "X-Graph-Build-Timings"

SENTRY_DSN = os.getenv("SENTRY_DSN")
# Default timeout for Kit subprocess execution (30 minutes = 1800 seconds)
DEFAULT_KIT_TIMEOUT_SECONDS = int(os.getenv("KIT_TIMEOUT_SECONDS", "1800"))
# Upper bound for a caller-supplied timeout_seconds. Caps how long a single
# request can hold a Kit-processing slot (the semaphore defaults to 1), so a
# stray/oversized value cannot wedge the worker. Never below the configured
# default, so raising KIT_TIMEOUT_SECONDS keeps working.
MAX_KIT_TIMEOUT_SECONDS = max(86400, DEFAULT_KIT_TIMEOUT_SECONDS)
# Interval for checking client disconnection (in seconds)
DISCONNECT_CHECK_INTERVAL = float(os.getenv("DISCONNECT_CHECK_INTERVAL", "1.0"))

# Soft memory watchdog for the Kit subprocess, in MB. Must be set *below* the
# container's memory limit: killing Kit ourselves turns an unattributable cgroup
# OOM kill (exit 137, connection dropped mid-request) into a reported
# `reason: oom`. 0 / unset disables it and leaves the kernel in charge.
KIT_WORKER_MEMORY_LIMIT_MB = int(os.getenv("KIT_WORKER_MEMORY_LIMIT_MB", "0"))

# On-disk asset cache location (downloaded USD / textures are reused across
# requests). Mirrors the rendering-job RenderingServiceSettings.cache_location;
# /cache is created (writable by nvs) in docker/Dockerfile.usdsearch.
CACHE_LOCATION = os.getenv("CACHE_LOCATION", "/cache")

n_parallel_processes = int(os.getenv("N_PARALLEL_PROCESSES", "1"))

semaphore = asyncio.Semaphore(n_parallel_processes)

logger = logging.getLogger(__name__)

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_kit_process_registry(app)
    yield


def _init_kit_process_registry(app: FastAPI) -> None:
    # Registry of currently-executing Kit subprocesses, keyed by PID. Each
    # in-flight request registers its process here and removes it on completion,
    # so concurrent requests (N_PARALLEL_PROCESSES > 1) never clobber each
    # other's process handle. Initialized at app creation (not only in lifespan)
    # so it also exists under ASGI transports that skip lifespan events (tests).
    app.state.kit_processes = {}


app = FastAPI(lifespan=lifespan)
_init_kit_process_registry(app)
router = APIRouter()


class GenericException(Exception):
    pass


class ConstructGraphRequest(BaseModel):
    url: str
    omni_user: str = ""
    omni_pass: str = ""
    aws_bucket: str = ""
    aws_region: str = ""
    aws_access_key: str = ""
    aws_access_key_id: str = ""
    aws_endpoint_url: str = ""
    storage_api_url: str = Field(
        default="",
        description="URL of the storage API to use. If provided - all other storage settings are ignored inside Kit.",
    )
    storage_api_token: Optional[str] = Field(default=None, description="Token for the Storage API")
    # OpenID config
    storage_api_openid_client_id: Optional[str] = Field(
        default=None, description="Client ID for the Storage API OpenID"
    )
    storage_api_openid_client_secret: Optional[str] = Field(
        default=None, description="Client secret for the Storage API OpenID"
    )
    storage_api_openid_token_url: Optional[str] = Field(
        default=None, description="OpenID token URL for the Storage API OpenID"
    )
    storage_api_openid_scope: Optional[str] = Field(default=None, description="OpenID scope for the Storage API OpenID")
    storage_api_openid_grant_type: Optional[str] = Field(
        default="client_credentials",
        description="OpenID grant type for the Storage API OpenID",
    )
    storage_api_token_refresh_interval: Optional[int] = Field(
        default=1800,
        description="Token refresh interval for the Storage API OpenID (in seconds)",
    )
    timeout_seconds: float = Field(
        default=DEFAULT_KIT_TIMEOUT_SECONDS,
        le=MAX_KIT_TIMEOUT_SECONDS,
        description=(
            "Timeout for Kit subprocess execution in seconds. Defaults to KIT_TIMEOUT_SECONDS "
            f"env var or 1800 (30 minutes). Capped at {MAX_KIT_TIMEOUT_SECONDS} so a single "
            "request cannot hold a Kit-processing slot indefinitely. Values <= 0 simply time "
            "out immediately and release the slot."
        ),
    )


@app.exception_handler(asyncio.TimeoutError)
async def timeout_exception_handler(request: Request, exc: asyncio.TimeoutError):
    return JSONResponse(
        status_code=status.HTTP_408_REQUEST_TIMEOUT,
        content={"detail": str(exc), "reason": GraphBuildReason.timeout.value},
    )


@app.exception_handler(GraphBuildError)
async def graph_build_error_handler(request: Request, exc: GraphBuildError):
    # The `reason` is the part callers act on: the AGS plugin maps it to a
    # per-asset status so a crawl reports a breakdown instead of an opaque
    # failure rate. `detail` stays human-facing.
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc), "reason": exc.reason.value},
        headers=timings_header(exc.timings),
    )


def timings_header(timings: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Render build timings as a response header, or nothing if unavailable."""
    if not timings:
        return {}
    return {TIMINGS_HEADER: json.dumps(timings, separators=(",", ":"))}


@app.exception_handler(GenericException)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc), "reason": GraphBuildReason.internal_error.value},
    )


async def get_openid_token(auth: ConstructGraphRequest, token: Optional[str] = None) -> Optional[str]:
    if auth.storage_api_openid_client_id is not None and auth.storage_api_openid_client_secret is not None:
        client = AsyncOAuth2Client(
            client_id=auth.storage_api_openid_client_id,
            client_secret=auth.storage_api_openid_client_secret,
            scope=auth.storage_api_openid_scope,
            token_endpoint=auth.storage_api_openid_token_url,
            grant_type=auth.storage_api_openid_grant_type,
        )
        if token is None:
            token = await client.fetch_token()
        else:
            token = await client.ensure_active_token(token)
        return token["access_token"]
    return None


def prepare_omniverse_toml(request: ConstructGraphRequest, home_directory: str) -> None:
    # Per-request omniverse.toml (located via OMNI_CONFIG_PATH) keeps each request's
    # S3 credentials isolated, while cache_root points at the shared on-disk asset
    # cache (previously supplied by Kit's omni_cache token) so downloads are reused
    # across requests. logs stay in the request's temp dir.
    content = f"""
[paths]

cache_root = "{CACHE_LOCATION}"
logs_root = "{home_directory}/logs"
"""

    if request.aws_bucket != "":
        if request.aws_endpoint_url:
            # Note: Auth support is currently broken in the client library. Urls not matching the Amazon AWS pattern are using the base HTTP provider. https://gitlab-master.nvidia.com/omniverse/client-library/-/blob/main/source/library/provider_http/HttpProviderFactory.cpp#L96
            content += f"""
[s3]

[s3."{request.aws_endpoint_url.replace('http://', '').replace('https://', '')}"]
accessKeyId = "{request.aws_access_key_id}"
secretAccessKey = "{request.aws_access_key}"
"""

        else:
            content += f"""
[s3]

[s3."{request.aws_bucket}.s3.{request.aws_region}.amazonaws.com"]
accessKeyId = "{request.aws_access_key_id}"
bucket = "{request.aws_bucket}"
region = "{request.aws_region}"
secretAccessKey = "{request.aws_access_key}"
"""

    os.makedirs(home_directory, exist_ok=True)
    with open(f"{home_directory}/omniverse.toml", "w", encoding="utf-8") as f:
        f.write(content)


def drop_none_inplace(source_dict: Dict[str, Any]) -> None:
    """Drop keys with None values in dictionary"""

    # checking for dictionary and dropping keys with None
    if isinstance(source_dict, dict):
        for key in list(source_dict.keys()):
            if source_dict[key] is None:
                del source_dict[key]
            else:
                drop_none_inplace(source_dict[key])
    # checking for list and pruning each entry
    elif isinstance(source_dict, list):
        for val in source_dict:
            drop_none_inplace(val)


def _convert_ags_url_to_kit_url(
    url: str,
    bucket: Optional[str] = None,
    region: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    # AGS uses https S3 urls
    if bucket is not None and url.startswith(f"s3://{bucket}"):
        if region is None and endpoint is None:
            raise ValueError("Region is not set. Please define the region for URL conversion to work properly")

        url_parsed = urlparse(url)
        if endpoint:
            return f"{endpoint}/{bucket}{url_parsed.path}"
        else:
            return f"https://{bucket}.s3.{region}.amazonaws.com{url_parsed.path}"
    return url


@lru_cache(maxsize=1)
def _resolver_stack_paths() -> tuple[List[str], List[str]]:
    """Discover the packman USD stack's shared-lib and python-binding dirs.

    The image lays out stock OpenUSD, the Omniverse client and omni_usd_resolver
    under OMNI_USD_STACK_HOME with per-package layouts, so the dirs are found by
    walking rather than hard-coded. Debug variants are skipped so only release
    libraries land on the paths.
    """
    home = os.getenv("OMNI_USD_STACK_HOME")
    if not home or not os.path.isdir(home):
        return [], []

    lib_dirs: List[str] = []
    py_dirs: List[str] = []
    for root, dirs, files in os.walk(home):
        dirs[:] = [d for d in dirs if d != "debug"]
        if any(f.endswith(".so") or ".so." in f for f in files):
            lib_dirs.append(root)
        if "pxr" in dirs or "omni" in dirs:
            py_dirs.append(root)
    return lib_dirs, py_dirs


def _resolver_subprocess_env() -> Dict[str, str]:
    """Prepend the packman USD stack's native libs and bindings for the builder only.

    The image keeps them off the global paths so other services sharing the
    usdsearch image never load the standalone stack's USD libs.
    """
    lib_dirs, py_dirs = _resolver_stack_paths()

    env: Dict[str, str] = {}
    for var, dirs in (("LD_LIBRARY_PATH", lib_dirs), ("PYTHONPATH", py_dirs)):
        if not dirs:
            continue
        existing = os.getenv(var)
        env[var] = os.pathsep.join(dirs + ([existing] if existing else []))
    return env


async def _prepare_storage_api_settings(
    request: ConstructGraphRequest,
) -> Dict[str, str]:
    """Translate the request's Storage API config into Omniverse client env vars.

    The standalone Omniverse client (packman ``client_library``) reads
    ``OMNI_STORAGE_HOST``/``PORT``/``SECURE`` when it initializes in the builder
    subprocess and registers that endpoint directly (matching Kit's
    ``register_storage_direct``). The bearer is passed via
    ``OMNI_STORAGE_AUTHORIZATION``.

    The Discovery Service variant (``OMNI_STORAGE_DISCOVERY``) that the renderer's
    ``apply_storage_env`` also handles is omitted because the Asset Graph Service
    caller only ever sends a direct ``storage_api_url``.
    """
    if request.storage_api_url == "":
        return {}

    if request.storage_api_token is not None:
        token: Optional[str] = request.storage_api_token
    elif request.storage_api_openid_client_id is not None and request.storage_api_openid_client_secret is not None:
        assert (
            request.storage_api_openid_token_url is not None
        ), "Storage API token URL is required for OpenID authentication"
        assert request.storage_api_openid_scope is not None, "Storage API scope is required for OpenID authentication"
        assert (
            request.storage_api_openid_grant_type is not None
        ), "Storage API grant type is required for OpenID authentication"

        token = await get_openid_token(request)
        assert token is not None, "Failed to get OpenID token: token is None"
    else:
        token = None

    url = request.storage_api_url
    parsed = urlparse(url if "://" in url else f"//{url}")
    if parsed.scheme in ("grpcs", "https"):
        secure = True
    elif parsed.scheme in ("grpc", "http"):
        secure = False
    else:
        secure = parsed.port is None or parsed.port == 443
    port = str(parsed.port) if parsed.port else ("443" if secure else "80")
    settings = {
        "OMNI_STORAGE_HOST": parsed.hostname or "",
        "OMNI_STORAGE_PORT": port,
        "OMNI_STORAGE_SECURE": "1" if secure else "0",
    }
    if token is not None:
        settings["OMNI_STORAGE_AUTHORIZATION"] = f"Bearer {token}"
    return settings


async def _watchdog_fired(memory_watcher: "asyncio.Future[bool]") -> bool:
    """Whether the memory watchdog killed Kit, waiting briefly for its verdict.

    Both the watchdog and the supervision loop wake on the process exiting, in
    an unspecified order, so the watchdog's result may not be settled yet at the
    moment the loop notices a non-zero exit. The process is already gone here,
    so the watchdog only has to finish its current poll interval.
    """
    try:
        return await asyncio.wait_for(asyncio.shield(memory_watcher), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return False


def _kit_failure(returncode: Optional[int], output_file: str, killed_by_watchdog: bool) -> GraphBuildError:
    """Turn a failed Kit run into a reasoned error.

    Precedence: the watchdog's own verdict, then whatever the Kit script
    classified for itself in the output file, then the exit code.
    """
    if killed_by_watchdog:
        return GraphBuildError(
            f"Kit process exceeded the {KIT_WORKER_MEMORY_LIMIT_MB} MB memory watchdog and was killed",
            reason=GraphBuildReason.oom,
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        )

    reason = reason_for_exit_code(returncode)
    detail = f"Kit process failed with exit code {returncode}"

    # The Kit script writes {"error": {...}} to the output file for failures it
    # can classify from the inside (see usd_deps.py). A killed process never
    # gets that far, hence the exit-code fallback above.
    try:
        with open(output_file, "r", encoding="utf-8") as f:
            error = json.load(f).get("error")
    except (OSError, ValueError):
        error = None

    if isinstance(error, dict):
        try:
            reason = GraphBuildReason(error.get("reason"))
        except ValueError:
            logger.warning("Kit reported an unknown failure reason %r", error.get("reason"))
        detail = error.get("message") or detail

    if reason is GraphBuildReason.oom:
        return GraphBuildError(
            f"{detail} (killed by the kernel — the container is out of memory)",
            reason=reason,
            status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
        )
    return GraphBuildError(detail, reason=reason)


def _log_timings(timings_file: str, spawned_at: float, url: str, succeeded: bool) -> Optional[Dict[str, Any]]:
    """Read the build's phase timings and log them as one structured line.

    Logged as well as returned because trace collection is off by default
    (``OTEL_SDK_DISABLED``), so the log is what most deployments will actually
    have when asking where a build's time went.
    """
    timings = read_timings(timings_file, spawned_at=spawned_at)
    if not timings:
        return None

    logger.info(
        "Graph build timings for %s: kit_startup_ms=%s total_ms=%s phases=%s%s",
        redact_url(url),
        timings.get("kit_startup_ms"),
        timings.get("total_ms"),
        timings.get("phases"),
        "" if succeeded else f" died_in={timings.get('died_in')}",
    )
    return timings


@router.post("/construct_graph/")
async def construct_graph(request: ConstructGraphRequest, http_request: Request) -> Dict[str, Any]:
    async with semaphore:
        logger.info("Constructing graph for URL: %s started", redact_url(request.url))
        with tempfile.TemporaryDirectory() as output_dir:
            prepare_omniverse_toml(request=request, home_directory=output_dir)
            output_file = f"{output_dir}/output"
            timings_file = f"{output_dir}/timings.jsonl"
            storage_api_env_settings = await _prepare_storage_api_settings(request=request)

            # Strip inherited PXR_* (e.g. PXR_PLUGINPATH_NAME) so the builder loads
            # only the packman stack's USD plugins, never another service's.
            base_env = {key: value for key, value in os.environ.items() if not key.startswith("PXR_")}

            # Newer omni.client wheels read OMNI_USER/OMNI_PASS, older ones OMNI_USERNAME/
            # OMNI_PASSWORD, so set both spellings.
            kit_env = {
                **base_env,
                **_resolver_subprocess_env(),
                **storage_api_env_settings,
                "OMNI_USER": request.omni_user,
                "OMNI_PASS": request.omni_pass,
                "OMNI_USERNAME": request.omni_user,
                "OMNI_PASSWORD": request.omni_pass,
                "USD_URL": _convert_ags_url_to_kit_url(
                    request.url,
                    bucket=request.aws_bucket,
                    region=request.aws_region,
                    endpoint=request.aws_endpoint_url,
                ),
                "OUTPUT_PATH": output_file,
                TIMINGS_PATH_ENV: timings_file,
                "OMNI_CONFIG_PATH": output_dir,  # make sure that home directories for different executions are different
            }

            # Taken before the spawn so the gap to the builder script's own first
            # record measures interpreter/USD-plugin startup — the one phase that
            # is invisible from inside the subprocess.
            spawned_at = time.time()

            # Run the builder in a fresh Python subprocess so each request gets an
            # isolated USD runtime (per-request Nucleus/Storage creds, no shared
            # stage cache) that can be killed on timeout/OOM without touching the
            # service. It registers the standalone Omniverse AR resolver, which
            # handles omniverse://, s3:// and http(s):// — no Kit kernel is launched.
            kit_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "graph_builder.usd_deps",
                env=kit_env,
            )

            # Track this request's process so concurrent requests don't share
            # state; always de-register it once the request is done.
            process_id = kit_process.pid
            app.state.kit_processes[process_id] = kit_process

            # Soft memory watchdog: kills Kit just below the container limit so an
            # over-large asset is reported as `reason: oom` instead of taking the
            # whole container down with a cgroup kill (exit 137). No-ops when the
            # limit is unset.
            memory_watcher = asyncio.ensure_future(memory_limit_watcher(kit_process, KIT_WORKER_MEMORY_LIMIT_MB))

            try:
                try:
                    # Wait for process with timeout, checking for client disconnection
                    elapsed_time = 0.0
                    while kit_process.returncode is None:
                        # Check if client disconnected
                        if await http_request.is_disconnected():
                            logger.warning("Client disconnected, cancelling Kit process")
                            kit_process.kill()
                            await kit_process.wait()
                            raise GraphBuildError(
                                "Client disconnected, Kit process cancelled",
                                reason=GraphBuildReason.client_disconnected,
                            )

                        # Check if timeout exceeded
                        if elapsed_time >= request.timeout_seconds:
                            logger.warning("Kit process timed out")
                            kit_process.kill()
                            await kit_process.wait()
                            # A GraphBuildError rather than a bare TimeoutError so
                            # the response carries the partial timings — a timed-out
                            # build is one of the two cases where knowing which
                            # phase it died in is the whole point.
                            raise GraphBuildError(
                                f"Kit process timed out after {request.timeout_seconds} seconds ({request.timeout_seconds / 60:.1f} minutes)",
                                reason=GraphBuildReason.timeout,
                                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                            )

                        # Poll at most until the deadline, so a sub-interval
                        # timeout_seconds is honoured instead of waiting a whole
                        # DISCONNECT_CHECK_INTERVAL past it.
                        wait_timeout = min(
                            DISCONNECT_CHECK_INTERVAL,
                            request.timeout_seconds - elapsed_time,
                        )
                        try:
                            await asyncio.wait_for(
                                kit_process.wait(),
                                timeout=wait_timeout,
                            )
                        except asyncio.TimeoutError:
                            # Process still running, continue polling
                            elapsed_time += wait_timeout
                            continue

                except asyncio.CancelledError as e:
                    kit_process.kill()
                    await kit_process.wait()  # Clean up the process
                    raise GraphBuildError(
                        "Kit process was cancelled",
                        reason=GraphBuildReason.client_disconnected,
                    ) from e
                except (GenericException, GraphBuildError):
                    # Re-raise our own exceptions (disconnection, timeout converted to GraphBuildError)
                    raise
                except asyncio.TimeoutError:
                    # Re-raise timeout errors
                    raise
                except Exception as e:
                    kit_process.kill()
                    await kit_process.wait()  # Clean up the process
                    raise GraphBuildError("Kit process failed") from e

                if kit_process.returncode == 0:
                    # make sure the URLs are correctly set (according to service input)
                    if request.aws_bucket is not None and request.url.startswith(f"s3://{request.aws_bucket}"):
                        with open(output_file, "r", encoding="utf-8") as f:
                            graph_result = f.read()

                        new_graph_result = graph_result.replace(
                            f"https://{request.aws_bucket}.s3.{request.aws_region}.amazonaws.com",
                            f"s3://{request.aws_bucket}",
                        )
                        if request.aws_endpoint_url:
                            new_graph_result = new_graph_result.replace(
                                f"{request.aws_endpoint_url}/{request.aws_bucket}",
                                f"s3://{request.aws_bucket}",
                            )

                        with open(output_file, "w", encoding="utf-8") as f:
                            f.write(new_graph_result)

                    with open(output_file, "r", encoding="utf-8") as f:
                        graph_result_dict = json.load(f)

                    # Make sure there are no Nones in the graph result
                    drop_none_inplace(graph_result_dict)

                    build_timings = _log_timings(timings_file, spawned_at, request.url, succeeded=True)

                    # Return a Response directly: skips FastAPI's pure-Python
                    # jsonable_encoder pass and serializes the (potentially large)
                    # graph with orjson instead of the stdlib json encoder.
                    # (orjson over fastapi's ORJSONResponse, which is deprecated
                    # in recent FastAPI and warns per-request.)
                    return Response(
                        content=orjson.dumps(graph_result_dict),
                        media_type="application/json",
                        headers=timings_header(build_timings),
                    )
                else:
                    raise _kit_failure(
                        returncode=kit_process.returncode,
                        output_file=output_file,
                        killed_by_watchdog=await _watchdog_fired(memory_watcher),
                    )
            except GraphBuildError as exc:
                # Attach whatever the killed build managed to record. This is the
                # case the separate timings file exists for: no graph document was
                # written, but the phase breakdown up to the kill still is.
                exc.timings = _log_timings(timings_file, spawned_at, request.url, succeeded=False)
                raise
            finally:
                memory_watcher.cancel()
                app.state.kit_processes.pop(process_id, None)


app.include_router(router)
