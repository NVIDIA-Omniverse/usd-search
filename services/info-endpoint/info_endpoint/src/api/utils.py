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
import asyncio
import base64
import logging
import os
from typing import Any, Awaitable, Dict, List, Optional

# local / proprietary modules
from cache.src import PluginItemStatus
from cache.src.client.redis import CacheClientRedis
from plugins import BasePlugin, Plugins

from search_utils.datetime_utils import date_from_timestamp
from search_utils.hashing_utils import get_hash
from search_utils.storage_client import AvailableStorageClients, StorageClient
from search_utils.storage_client.nucleus.client import NucleusStorageClient
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.storage_api.client import StorageAPIStorageClient

from .models import PluginInfo, PluginStatusType

logger = logging.getLogger(__name__)


async def get_plugin_status(
    url: str,
    active_plugins: List[BasePlugin],
    cache_client: CacheClientRedis,
    actual_hash_value: Optional[str],
) -> Dict[str, PluginInfo]:
    plugin_info_list: List[Optional[PluginInfo]] = await asyncio.gather(
        *[
            get_plugin_info(
                url=url,
                plugin=plugin,
                cache_client=cache_client,
                actual_hash_value=actual_hash_value,
            )
            for plugin in active_plugins
        ]
    )
    return {
        plugin.plugin_name: plugin_info
        for plugin, plugin_info in zip(active_plugins, plugin_info_list)
        if plugin_info is not None
    }


async def get_plugin_info(
    url: str,
    plugin: BasePlugin,
    cache_client: CacheClientRedis,
    actual_hash_value: Optional[str],
) -> Optional[PluginInfo]:
    ext = os.path.splitext(url)[1][1:]
    item_status_history: Optional[List[PluginItemStatus]] = None
    # if plugin cannot process this path - directly exit
    if not plugin.should_process(file_type=ext):
        return None
    try:
        stored_hash_value = base64.b64encode(
            (await cache_client.plugin_get_raw(dest=f"{plugin.plugin_name}_path_to_hash", key=url))
        )
    except KeyError:
        stored_hash_value = None

    asset_status = None
    try:
        asset_status = await cache_client.get_asset_status(plugin_name=plugin.plugin_name, uri=url)
        if len(asset_status.item_status_history) > 0:
            item_status_history = [
                PluginItemStatus(
                    status=item_status.status,
                    hash_value=base64.b64encode(get_hash(item_status.hash_value)),
                    processing_timestamp=date_from_timestamp(item_status.processing_timestamp),
                    exception=item_status.exception,
                )
                for item_status in asset_status.item_status_history
            ]
    except KeyError:
        pass

    if asset_status is None and stored_hash_value is None:
        return PluginInfo(indexing_status=PluginStatusType.not_found)

    return PluginInfo(
        indexing_status=(
            PluginStatusType.in_sync
            if actual_hash_value == stored_hash_value and stored_hash_value is not None
            else PluginStatusType.out_of_sync
        ),
        indexed_asset_hash=stored_hash_value,
        plugin_status_history=item_status_history,
    )


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Exclude healthchecks from access logs
        return record.getMessage().find("/health") == -1 and record.getMessage().find("/metrics") == -1


def get_storage_backend_type(storage_client: StorageClient) -> AvailableStorageClients:
    if isinstance(storage_client, NucleusStorageClient):
        return AvailableStorageClients.nucleus
    if isinstance(storage_client, S3StorageClient):
        return AvailableStorageClients.s3
    if isinstance(storage_client, StorageAPIStorageClient):
        return AvailableStorageClients.storage_api

    raise NotImplementedError(f"Unsupported client type: {type(storage_client)}")


async def default_on_exception(awaitable: Awaitable[Any], default: Optional[Any] = None) -> Optional[Any]:
    try:
        return await awaitable
    except Exception as exc:
        logger.exception(exc)
        return default


def get_plugin_names_with_descriptions() -> str:
    result = ""

    for plugin in sorted(Plugins.get_all_plugins(), key=lambda x: x.plugin_name):
        result += f"""
* **{plugin.plugin_name}**: {plugin.__doc__}
    * This plugin supports the following data types: *{', '.join(plugin.data_types)}*
"""
    return result
