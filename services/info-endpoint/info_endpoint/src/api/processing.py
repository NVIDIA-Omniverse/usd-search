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
import os
from typing import Annotated, List, Optional

# third party modules
from aiohttp.client_exceptions import ClientConnectorError
from cache.src import JobItem, JobItemType
from cache.src.client.redis import CacheClientRedis

# local / proprietary modules
from crawlers.src.indexing import IndexingService
from crawlers.src.tag_crawler import TagCrawlerService
from fastapi import APIRouter, Request
from fastapi.params import Query
from plugins import BasePlugin, Plugins
from storage.src.client import NGSearchStorageClient, Status, StorageClientInput
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from search_utils.storage_client import PathType, StorageClient

from ..config import INFOEndpointServiceConfig
from .clients import get_storage_client
from .exceptions import (
    AssetNotFoundError,
    EmptyPluginList,
    InvalidURL,
    NGSearchStorageConnectionError,
)
from .models import AssetProcessingResponse, ProcessingStatus
from .utils import get_plugin_names_with_descriptions

router = APIRouter(prefix="/process")


@router.get(
    "/asset",
    tags=["Asset"],
    description=f"""
USD Search processes all assets on the storage backend in the background. This, however, may
take time depending on the amount of data on the storage backend and the amount of available resources,
which could lead to delays in specific assets appearing in the search index. In order to address this
and prioritize processing of specific assets, it is possible to use this endpoint to trigger
indexing of a specific asset on demand.

When triggering processing of a specific asset URL the user could decide, with which plugin the
asset needs to be processed. By default, when no plugin is selected - the service will trigger
processing for all plugins that could work with this asset type. Please find below the list of
supported plugins:
{get_plugin_names_with_descriptions()}

**NOTE**: If some of the plugins are not enabled for the USD Search instance, selecting them for the
*plugins* parameter setting will have not effect. Please reach out to your USD Search service administrator
if you would like to enable certain plugin functionality. The list of plugins that are enabled for
this USD Search instance could be retrieved using **/info/plugins** endpoint.
    """,
    summary="On-demand asset processing",
)
async def submit_for_processing(
    request: Request,
    url: Annotated[
        str,
        Query(description="Asset URL which should be submitted for priority processing"),
    ],
    plugins: Annotated[
        Optional[List[Plugins]],
        Query(description="List of plugins for which indexing needs to be re-done"),
    ] = None,
    refresh_plugins: Annotated[bool, Query(description="re-enqueue plugin processing")] = True,
    refresh_metadata: Annotated[bool, Query(description="refresh asset metadata")] = False,
    refresh_tags: Annotated[bool, Query(description="refresh asset tags")] = False,
    priority: Annotated[Optional[JobItemType], Query(description="processing job type")] = JobItemType.priority,
):

    active_plugins: List[BasePlugin] = request.app.active_plugins
    cache_client: CacheClientRedis = request.app.cache_client
    storage_client: StorageClient = request.app.storage_client
    search_backend_config: NGSearchStorageSearchBackendConfig = request.app.search_backend_config
    service_config: INFOEndpointServiceConfig = request.app.service_config

    # get the list of plugins that are active and also can process the given URL
    plugins_to_be_reset = [
        plugin.plugin_name for plugin in active_plugins if plugin.should_process(os.path.splitext(url)[1][1:])
    ]
    if plugins is not None:
        plugins_to_be_reset = [plugin_name for plugin_name in plugins_to_be_reset if plugin_name in plugins]

    if refresh_plugins and len(plugins_to_be_reset) == 0:
        raise EmptyPluginList("Empty list of plugins that require to be reset")

    # check if URL is valid
    if not storage_client.is_valid_uri(url):
        raise InvalidURL(f"Invalid URL: '{url}'")

    # check if asset exists on the storage backend
    exists, _ = await storage_client.check_if_exists(url)
    if not exists:
        raise AssetNotFoundError(f"Asset with URL: {url} is missing on the storage backend")

    path_item: PathType = await anext(storage_client.list_items(uri_list=[url]))

    metadata_refreshed = False
    tags_refreshed = False

    # re-set plugins for the given URL (optional)
    if refresh_plugins and len(plugins_to_be_reset) > 0:
        # clear files from redis cache
        await asyncio.gather(
            *[
                cache_client.plugin_del(dest=f"{plugin_name}_path_to_hash", keys=[url])
                for plugin_name in plugins_to_be_reset
            ]
        )

        # add to processing stream with priority
        hash_value = path_item.get_hash()
        await asyncio.gather(
            *[
                cache_client.enqueue_plugin_job(
                    plugin_name=plugin_name,
                    content=JobItem(
                        uri=url,
                        hash_value=hash_value,
                        plugin_name=plugin_name,
                        job_type=priority,
                    ),
                )
                for plugin_name in plugins_to_be_reset
            ]
        )

    ignored_plugins = list(set(Plugins.get_plugin_names()) - set(plugins_to_be_reset))

    if refresh_metadata or refresh_tags:
        try:
            ngsearch_storage_client = await asyncio.wait_for(
                NGSearchStorageClient.get_service(
                    search_backend_config=search_backend_config,
                ),
                timeout=service_config.search_backend_timeout,
            )
            # connect to the storage client context
            async with ngsearch_storage_client as ngsearch_storage_client_context:
                # make sure storage client is ready
                await ngsearch_storage_client_context.readyz()
                # update metadata
                if refresh_metadata:
                    meta_dict = await IndexingService.prepare_meta_dict(storage_client, path_item)
                    response = await ngsearch_storage_client_context.update_meta(
                        StorageClientInput(key=path_item.uri, meta=meta_dict),
                        backend_name=None,
                    )
                    assert response.status == Status.ok
                    metadata_refreshed = True

                if refresh_tags:
                    _storage_client = get_storage_client()
                    async with _storage_client.connection_context_with_tagging() as _client:
                        meta_dict = await TagCrawlerService.prepare_meta_dict(_client, path_item)
                        if meta_dict is not None:
                            response = await ngsearch_storage_client_context.update_meta(
                                StorageClientInput(key=path_item.uri, meta=meta_dict),
                                backend_name=None,
                            )
                            assert response.status == Status.ok
                            tags_refreshed = True

        except (
            ConnectionError,
            ClientConnectorError,
            asyncio.TimeoutError,
        ) as exc_info:
            raise NGSearchStorageConnectionError(exc_info) from exc_info

    return AssetProcessingResponse(
        status=ProcessingStatus.submitted,
        plugins=plugins_to_be_reset,
        ignored_plugins=ignored_plugins,
        metadata_refreshed=metadata_refreshed,
        tags_refreshed=tags_refreshed,
    )
