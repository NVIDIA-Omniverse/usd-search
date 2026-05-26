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
from typing import List, Optional

import httpx
from cache.src import GenericPluginStatus
from tqdm.asyncio import tqdm_asyncio

from search_utils.storage_client import StorageClient

from .list_asset_by_status import get_asset_by_status
from .utils import _make_request


async def process_asset(
    asset_url: str,
    api_semaphore: asyncio.Semaphore,
    endpoint_url: str,
    plugins: Optional[List[str]] = None,
    include_plugins: Optional[List[str]] = None,
    refresh_metadata: bool = True,
    refresh_tags: bool = False,
    refresh_plugins: bool = True,
):
    async with api_semaphore:
        async with httpx.AsyncClient() as client:
            request_params = dict(
                url=asset_url,
                refresh_metadata=refresh_metadata,
                refresh_tags=refresh_tags,
                refresh_plugins=refresh_plugins,
            )
            if plugins is not None:
                if include_plugins is not None and len(include_plugins) > 0:
                    included_plugins = [plugin for plugin in plugins if plugin in include_plugins]
                    request_params["plugins"] = included_plugins
                else:
                    request_params["plugins"] = plugins
            elif include_plugins is not None and len(include_plugins) > 0:
                request_params["plugins"] = include_plugins

            response = await _make_request(
                client=client,
                method="GET",
                url=f"{endpoint_url}/process/asset",
                params=request_params,
            )

            if response.status_code != 200:
                print(f"Error {response.status_code}: {response.text}")


async def reindex_assets(
    storage_client: StorageClient,
    path: str,
    endpoint_url: str = "http://localhost:8000",
    asset_formats: Optional[List[str]] = None,
    exclude_file_patterns: Optional[List[str]] = None,
    include_statuses: Optional[List[GenericPluginStatus]] = None,
    exclude_statuses: Optional[List[GenericPluginStatus]] = None,
    include_plugins: Optional[List[str]] = None,
    num_parallel_api_calls: int = 10,
    dry_run: bool = False,
    output_file: Optional[str] = None,
    ignore_existing_statuses: bool = False,
    refresh_metadata: bool = True,
    refresh_tags: bool = False,
    refresh_plugins: bool = True,
) -> None:
    res = await get_asset_by_status(
        storage_client=storage_client,
        path=path,
        endpoint_url=endpoint_url,
        asset_formats=asset_formats,
        exclude_file_patterns=exclude_file_patterns,
        include_statuses=include_statuses,
        exclude_statuses=exclude_statuses,
        include_plugins=include_plugins,
        num_parallel_api_calls=num_parallel_api_calls,
        ignore_existing_statuses=ignore_existing_statuses or not refresh_plugins,
    )

    if output_file is not None:
        with open(output_file, "w") as f:
            json.dump(res, f, indent=4)

    if dry_run:
        print(json.dumps(res, indent=4))
        print("- Summary --------------------------------")
        for status, assets in res.items():
            print(f"{status}: {len(assets)} asset(s)")
        print("------------------------------------------")
        return

    api_semaphore = asyncio.Semaphore(num_parallel_api_calls)

    for status, assets in res.items():
        await tqdm_asyncio.gather(
            *[
                process_asset(
                    asset_url=asset_url,
                    api_semaphore=api_semaphore,
                    endpoint_url=endpoint_url,
                    plugins=plugins,
                    include_plugins=include_plugins,
                    refresh_metadata=refresh_metadata,
                    refresh_tags=refresh_tags,
                    refresh_plugins=refresh_plugins,
                )
                for asset_url, plugins in assets.items()
            ],
            desc=f"triggering reindexing for status: '{status}'",
        )


def main(
    path: str,
    endpoint_url: str,
    storage_client: StorageClient,
    asset_formats: Optional[List[str]] = None,
    exclude_file_patterns: Optional[List[str]] = None,
    include_statuses: Optional[List[GenericPluginStatus]] = None,
    exclude_statuses: Optional[List[GenericPluginStatus]] = [GenericPluginStatus.ok],
    include_plugins: Optional[List[str]] = None,
    num_parallel_api_calls: int = 10,
    dry_run: bool = False,
    output_file: Optional[str] = None,
    ignore_existing_statuses: bool = False,
    refresh_metadata: bool = True,
    refresh_tags: bool = False,
    refresh_plugins: bool = True,
) -> None:
    asyncio.run(
        reindex_assets(
            storage_client=storage_client,
            path=path,
            endpoint_url=endpoint_url,
            asset_formats=asset_formats,
            exclude_file_patterns=exclude_file_patterns,
            include_statuses=include_statuses,
            exclude_statuses=exclude_statuses,
            include_plugins=include_plugins,
            num_parallel_api_calls=num_parallel_api_calls,
            dry_run=dry_run,
            output_file=output_file,
            ignore_existing_statuses=ignore_existing_statuses,
            refresh_metadata=refresh_metadata,
            refresh_tags=refresh_tags,
            refresh_plugins=refresh_plugins,
        )
    )
