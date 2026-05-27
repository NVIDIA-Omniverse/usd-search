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

# standard modules
import base64
from typing import Annotated, List

# local / proprietary modules
from cache.src.client.redis import CacheClientRedis

# third party modules
from fastapi import APIRouter, Request
from fastapi.params import Query
from plugins import BasePlugin

from search_utils.storage_client import StorageClient

from .exceptions import InvalidURL
from .models import AssetStorageBackendInfo, BackendStatusType, StatusResult
from .utils import get_plugin_status

router = APIRouter(prefix="/indexing")


@router.get(
    "/asset/status",
    tags=["Asset"],
    summary="Check asset indexing status per plugin",
    description="""
Check whether a specific asset has been fully indexed by USD Search. Use this to verify if an asset
will appear in search results, or to diagnose why it might be missing.

For each URL the service checks caches of all plugins that support processing this asset and reports the following information:

* **indexing_status** [*not_found* / *in_sync* / *out_of_sync* ] - this parameter checks the difference between cached value of asset hash and the actual (up-to-date) asset hash from the storage backend.

    * if these two values match - then the asset is considered to be up-to-date, in other words *in_sync*
    * otherwise, the final version of the asset has not be processed yet.
    * The *not_found* status is assigned in case the asset has never been processed.

* **plugin_status_history** - is a list of last statuses that were assigned to the asset, while it was being processed. Each item of this list has the following structure:

    * **status** [*ok* / *processing* / *failed_retries_exhausted* / other string] - shows whether the asset was

        * *ok* - successfully processed
        * *processing* - processing for the asset has started
        * *failed_retries_exhausted* - processing of the asset failed and reached the retry limit
        * any other string - indicates that that processing has failed with this message.

    * **processing_timestamp** - the moment when the status was assigned
    * **exception** - optional exception explanation

The service could additionally report asset metadata from the storage backend if **return_asset_metadata** flag is set to *True*.
""",
)
async def get_asset_status(
    request: Request,
    url: Annotated[
        str,
        Query(description="Asset URL for which processing status needs to be retrieved"),
    ],
    return_asset_metadata: Annotated[bool, Query(description="Return metadata for the asset if set to True")] = False,
) -> StatusResult:
    # NOTE: _active_plugins parameter is created at FastAPI app's creation time in the lifespan function
    active_plugins: List[BasePlugin] = request.app.active_plugins
    cache_client: CacheClientRedis = request.app.cache_client
    storage_client: StorageClient = request.app.storage_client

    # check if URL is valid
    if not storage_client.is_valid_uri(url):
        raise InvalidURL(f"Invalid URL: '{url}'")

    exists, _ = await storage_client.check_if_exists(uri=url)
    item = None
    actual_hash_value = None
    if exists:
        try:
            item = await anext(storage_client.list_items(uri_list=[url], ignore_patterns=None))
        except StopAsyncIteration as e:
            raise InvalidURL(f"asset could not be found with list command: {url}") from e
        actual_hash_value = base64.b64encode(item.get_hashed_hash_value()) if item is not None else None

    storage_backend_info = AssetStorageBackendInfo(
        asset_status=(BackendStatusType.ok if exists else BackendStatusType.file_not_found),
        metadata=item if return_asset_metadata else None,
        storage_asset_hash=actual_hash_value,
    )

    plugin_status = await get_plugin_status(
        url=url,
        active_plugins=active_plugins,
        cache_client=cache_client,
        actual_hash_value=actual_hash_value,
    )

    return StatusResult(
        url=url,
        plugins_statuses=plugin_status,
        storage_backend_info=storage_backend_info,
    )
