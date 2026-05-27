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

import logging
import os
import re
from asyncio.subprocess import Process
from typing import Dict, List, Optional

from .auth import get_openid_token
from .models import Authentication
from .utils import create_process_with_memory_limit_and_timeout

logger = logging.getLogger(__name__)


def prepare_omniverse_toml(request: Authentication, home_directory: str) -> None:

    # As client library stores cache independently from main Kit cache - it needs special handling
    # here
    logger.info("Preparing omniverse.toml for home directory: %s", home_directory)
    content = f"""
[paths]

cache_root = "{home_directory}/cache"
logs_root = "{home_directory}/logs"

"""

    if request.aws_bucket != "":
        os.makedirs(home_directory, exist_ok=True)
        if request.aws_endpoint:
            # Note: Auth support is currently broken in the client library.
            # Urls not matching the Amazon AWS pattern are using the base HTTP provider.
            # https://gitlab-master.nvidia.com/omniverse/client-library/-/blob/main/source/library/provider_http/HttpProviderFactory.cpp#L96
            content += f"""
[s3]

[s3."{re.sub(r'^https?://', '', request.aws_endpoint)}"]
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
    # write omniverse.toml file
    with open(f"{home_directory}/omniverse.toml", "w", encoding="utf-8") as toml_file:
        toml_file.write(content)


async def _prepare_storage_api_settings(request: Authentication) -> Dict[str, str]:
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


async def start_kit_worker(
    request: Authentication,
    output_dir: str,
    log_level: str = "info",
    port: int = 8223,
    cache_location: str = "/cache",
    extension_folder: str = "/exts",
    hssc_uri: Optional[str] = None,
    enable_shader_cache_wrapper: bool = False,
    memory_limit: int = -1,  # unlimited
    worker_id: Optional[str] = None,
    rendering_timeout: Optional[float] = None,
    kit_extra_args: Optional[List[str]] = None,
) -> Process:
    prepare_omniverse_toml(request=request, home_directory=output_dir)
    storage_api_env_settings = await _prepare_storage_api_settings(request=request)
    process_env = {**os.environ, **storage_api_env_settings}
    process_env["OMNI_CONFIG_PATH"] = output_dir
    process_env["OMNI_USER"] = request.omni_user
    process_env["OMNI_PASS"] = request.omni_pass
    command_line_args = [
        "--/app/extensions/excluded/0=omni.replicator.core",
        f"--/log/level={log_level}",
        f"--/app/tokens/omni_global_cache={cache_location}",
        f"--/app/tokens/omni_cache={cache_location}",
        "--/app/settings/fabricStageFrameHistoryCount=3",
        "--/app/settings/fabricDefaultStageFrameHistoryCount=3",
        "--enable omni.services.deepsearch.rendering",
        "--enable omni.services.convert.asset",
        "--enable omni.kit.thumbnails.mdl",
        "--enable omni.hydra.rtx",
        f"--ext-folder {extension_folder.rstrip('/')}",
        f"--/exts/omni.services.transport.server.http/port={port}",
    ]
    # additional arguments to pass to Kit
    if kit_extra_args is not None:
        command_line_args.extend(kit_extra_args)
    # HSSC cache setup
    if hssc_uri is not None:
        command_line_args.extend(
            [
                "--enable omni.hsscclient",
                f"--/UJITSO/datastore/hsscUri={hssc_uri}",
                "--/UJITSO/enabled=true",
                "--/UJITSO/geometry=true",
                "--/UJITSO/textures=true",
            ]
        )

        # Replace schema with hsscdns for shader cache wrapper
        if enable_shader_cache_wrapper:
            process_env["AUTO_ENABLE_DRIVER_SHADER_CACHE_WRAPPER"] = hssc_uri

    logger.info("command_line_args: %s", command_line_args)
    logger.info(
        "AUTO_ENABLE_DRIVER_SHADER_CACHE_WRAPPER: %s",
        process_env.get("AUTO_ENABLE_DRIVER_SHADER_CACHE_WRAPPER"),
    )

    return await create_process_with_memory_limit_and_timeout(
        "/startup.sh",
        *command_line_args,
        env=process_env,
        max_mem_mb=memory_limit,
        worker_id=worker_id,
        timeout=rendering_timeout,
    )
