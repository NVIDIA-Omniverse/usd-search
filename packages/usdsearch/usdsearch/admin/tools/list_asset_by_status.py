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
import fnmatch
import os
from typing import Dict, List, Optional

import httpx
from cache.src import GenericPluginStatus
from info_endpoint.src.api.models import PluginStatusType, StatusResult
from tqdm.asyncio import tqdm_asyncio

from search_utils.storage_client import StorageClient

from .ls import ls
from .utils import _make_request


async def get_asset_status(
    endpoint_url: str, asset_url: str, api_semaphore: asyncio.Semaphore
) -> Optional[StatusResult]:
    async with api_semaphore:
        async with httpx.AsyncClient() as client:
            response = await _make_request(
                client=client,
                method="GET",
                url=f"{endpoint_url}/info/indexing/asset/status",
                params=dict(url=asset_url),
            )

            if response.status_code != 200:
                print(f"Error getting status for '{asset_url}': {response.status_code}: {response.text}")
                return None

    return StatusResult(**response.json())


async def group_assets_by_latest_status(
    asset_urls: List[str],
    endpoint_url: str,
    include_statuses: Optional[List[GenericPluginStatus]] = None,
    exclude_statuses: Optional[List[GenericPluginStatus]] = None,
    include_plugins: Optional[List[str]] = None,
    num_parallel_api_calls: int = 10,
) -> Dict[GenericPluginStatus, Dict[str, List[str]]]:
    api_semaphore = asyncio.Semaphore(num_parallel_api_calls)
    statuses: List[Optional[StatusResult]] = await tqdm_asyncio.gather(
        *[
            get_asset_status(
                endpoint_url=endpoint_url,
                asset_url=asset_url,
                api_semaphore=api_semaphore,
            )
            for asset_url in asset_urls
        ],
        desc="retrieving asset statuses",
    )

    result = {}

    for status in statuses:
        if status is None:
            continue

        for plugin_name, plugin_status in status.plugins_statuses.items():
            if include_plugins is not None and len(include_plugins) > 0 and plugin_name not in include_plugins:
                continue

            if (
                plugin_status.indexing_status == PluginStatusType.not_found
                or plugin_status.plugin_status_history is None
            ):
                latest_plugin_status = "missing"
            else:
                latest_plugin_status = plugin_status.plugin_status_history[0].status
            if include_statuses is not None and latest_plugin_status not in include_statuses:
                continue

            if exclude_statuses is not None and latest_plugin_status in exclude_statuses:
                continue

            if latest_plugin_status not in result:
                result[latest_plugin_status] = {}

            result[latest_plugin_status][status.url] = result.get(latest_plugin_status, {}).get(status.url, []) + [
                plugin_name
            ]

    return result


async def get_asset_by_status(
    storage_client: StorageClient,
    path: str,
    endpoint_url: str,
    asset_formats: Optional[List[str]] = None,
    exclude_file_patterns: Optional[List[str]] = None,
    include_statuses: Optional[List[GenericPluginStatus]] = None,
    exclude_statuses: Optional[List[GenericPluginStatus]] = None,
    include_plugins: Optional[List[str]] = None,
    num_parallel_api_calls: int = 10,
    ignore_existing_statuses: bool = False,
) -> Dict[GenericPluginStatus, Dict[str, List[str]]]:
    asset_urls = await ls(storage_client=storage_client, path=path, verbose=False)

    if exclude_file_patterns is not None:
        asset_urls = [
            url for url in asset_urls if not any(fnmatch.fnmatch(url, pattern) for pattern in exclude_file_patterns)
        ]

    asset_urls = [url for url in asset_urls if asset_formats is None or os.path.splitext(url)[1][1:] in asset_formats]

    if ignore_existing_statuses:
        return {"force": {url: None for url in asset_urls}}

    return await group_assets_by_latest_status(
        asset_urls=asset_urls,
        endpoint_url=endpoint_url,
        include_statuses=include_statuses,
        exclude_statuses=exclude_statuses,
        include_plugins=include_plugins,
        num_parallel_api_calls=num_parallel_api_calls,
    )
