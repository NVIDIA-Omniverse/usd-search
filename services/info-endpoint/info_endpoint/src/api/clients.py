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

# standard imports
import logging
from typing import List

# local / proprietary imports
from cache.src.client.config import RedisCacheConfig
from cache.src.client.redis import CacheClientRedis
from monitor.src.config import DeepSearchMonitorConfig
from plugins import BasePlugin, Plugins

from search_utils.storage_client import StorageClient, get_client
from search_utils.storage_client.config import StorageConfig

# import asyncio


logger = logging.getLogger(__name__)


async def get_cache_client() -> CacheClientRedis:
    """Get Redis Cache client

    Returns:
        CacheClientRedis: Cache client
    """
    config = RedisCacheConfig(cache_auto_trim_timeout=-1)
    cache_client = CacheClientRedis(config=config)
    await cache_client.ready.wait()
    return cache_client


def get_active_plugins() -> List[BasePlugin]:
    """Get a list of active plugins

    Returns:
        List[BasePlugin]: List of active plugins
    """
    return Plugins.get_active_plugins(config_path=DeepSearchMonitorConfig().plugins_config_path)


def get_storage_client() -> StorageClient:
    """Get storage client

    Returns:
        StorageClient: storage client
    """

    return get_client(client_type=StorageConfig().storage_backend_type)
