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
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import orjson
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, FastAPI, Request, status
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

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

# On-disk Kit asset cache location (downloaded USD / textures are reused across
# requests). Mirrors the rendering-job RenderingServiceSettings.cache_location;
# /cache is created in docker/Dockerfile.kit.
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
    timeout_seconds: int = Field(
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
    return JSONResponse(status_code=status.HTTP_408_REQUEST_TIMEOUT, content={"detail": str(exc)})


@app.exception_handler(GenericException)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc)})


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
    # As the client library stores its cache independently from the main Kit
    # cache, the cache_root path needs to be set explicitly here.
    content = f"""
[paths]

cache_root = "{home_directory}/cache"
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


async def _prepare_storage_api_settings(
    request: ConstructGraphRequest,
) -> Dict[str, str]:
    EXTRA_VARS = {}
    if request.storage_api_url != "":
        if request.storage_api_token is not None:
            EXTRA_VARS = {"OMNI_STORAGE_AUTHORIZATION": f"Bearer {request.storage_api_token}"}
        elif request.storage_api_openid_client_id is not None and request.storage_api_openid_client_secret is not None:
            assert (
                request.storage_api_openid_token_url is not None
            ), "Storage API token URL is required for OpenID authentication"
            assert (
                request.storage_api_openid_scope is not None
            ), "Storage API scope is required for OpenID authentication"
            assert (
                request.storage_api_openid_grant_type is not None
            ), "Storage API grant type is required for OpenID authentication"

            token = await get_openid_token(request)
            assert token is not None, "Failed to get OpenID token: token is None"

            EXTRA_VARS = {"OMNI_STORAGE_AUTHORIZATION": f"Bearer {token}"}

        return {
            "STORAGE_API_URL": request.storage_api_url,
            **EXTRA_VARS,
        }
    return {}


@router.post("/construct_graph/")
async def construct_graph(request: ConstructGraphRequest, http_request: Request) -> Dict[str, Any]:
    async with semaphore:
        logger.info(f"Constructing graph for URL: {request.url} started")
        with tempfile.TemporaryDirectory() as output_dir:
            prepare_omniverse_toml(request=request, home_directory=output_dir)
            output_file = f"{output_dir}/output"
            storage_api_env_settings = await _prepare_storage_api_settings(request=request)

            # Prepare environment for subprocess
            kit_env = {
                **os.environ,
                **storage_api_env_settings,
                "OMNI_USER": request.omni_user,
                "OMNI_PASS": request.omni_pass,
                "USD_URL": _convert_ags_url_to_kit_url(
                    request.url,
                    bucket=request.aws_bucket,
                    region=request.aws_region,
                    endpoint=request.aws_endpoint_url,
                ),
                "OUTPUT_PATH": output_file,
                "OMNI_CONFIG_PATH": output_dir,  # make sure that home directories for different executions are different
            }

            # Run Kit subprocess asynchronously with timeout
            kit_process = await asyncio.create_subprocess_exec(
                "/opt/nvidia/omniverse/kit-kernel/kit",
                "--/log/level=Verbose",
                "--/log/fileLogLevel=Verbose",
                "--/exts/omni.client/logLevel=0",
                f"--/app/tokens/omni_global_cache={CACHE_LOCATION}",
                f"--/app/tokens/omni_cache={CACHE_LOCATION}",
                # "-vv",  # enable verbose logging
                "--enable",
                "omni.usd",
                "--enable",
                "omni.usd.schema.semantics",
                "--enable",
                "omni.usd.libs",
                "--enable",
                "omni.client",
                "--enable",
                "omni.materialx.libs",
                "--enable",
                "omni.mdl",
                "--enable",
                "omni.mdl.neuraylib",
                "--enable",
                "omni.kit.usd.mdl",
                "--/app/extensions/registryEnabled=0",
                "--exec",
                str(Path(__file__).parent / "usd_deps_kit.py"),
                env=kit_env,
            )

            # Track this request's process so concurrent requests don't share
            # state; always de-register it once the request is done.
            process_id = kit_process.pid
            app.state.kit_processes[process_id] = kit_process

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
                            raise GenericException("Client disconnected, Kit process cancelled")

                        # Check if timeout exceeded
                        if elapsed_time >= request.timeout_seconds:
                            logger.warning("Kit process timed out")
                            kit_process.kill()
                            await kit_process.wait()
                            raise asyncio.TimeoutError(
                                f"Kit process timed out after {request.timeout_seconds} seconds ({request.timeout_seconds / 60:.1f} minutes)"
                            )

                        # Wait for process to complete or check interval
                        try:
                            await asyncio.wait_for(
                                kit_process.wait(),
                                timeout=DISCONNECT_CHECK_INTERVAL,
                            )
                        except asyncio.TimeoutError:
                            # Process still running, continue polling
                            elapsed_time += DISCONNECT_CHECK_INTERVAL
                            continue

                except asyncio.CancelledError as e:
                    kit_process.kill()
                    await kit_process.wait()  # Clean up the process
                    raise GenericException("Kit process was cancelled") from e
                except GenericException:
                    # Re-raise our own exceptions (disconnection, timeout converted to GenericException)
                    raise
                except asyncio.TimeoutError:
                    # Re-raise timeout errors
                    raise
                except Exception as e:
                    kit_process.kill()
                    await kit_process.wait()  # Clean up the process
                    raise GenericException("Kit process failed") from e

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

                    # Return a Response directly: skips FastAPI's pure-Python
                    # jsonable_encoder pass and serializes the (potentially large)
                    # graph with orjson instead of the stdlib json encoder.
                    # (orjson over fastapi's ORJSONResponse, which is deprecated
                    # in recent FastAPI and warns per-request.)
                    return Response(content=orjson.dumps(graph_result_dict), media_type="application/json")
                else:
                    raise GenericException(f"Kit process failed with exit code {kit_process.returncode}")
            finally:
                app.state.kit_processes.pop(process_id, None)


app.include_router(router)
