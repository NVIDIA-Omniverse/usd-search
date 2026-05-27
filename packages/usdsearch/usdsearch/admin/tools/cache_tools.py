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

from typing import Optional

import redis.asyncio as aioredis


class CacheTools:
    """Admin utilities for inspecting and managing cache Redis streams.

    Args:
        redis_url: Redis connection URL.
        stream_name_prefix: Prefix shared by all cache streams (e.g. ``deepsearch``).
        cache_plugin_prefix: Key prefix used for plugin result storage.
    """

    def __init__(self, redis_url: str, stream_name_prefix: str, cache_plugin_prefix: str) -> None:
        self._redis_url = redis_url
        self._stream_name_prefix = stream_name_prefix
        self._cache_plugin_prefix = cache_plugin_prefix

    async def _get_processing_queues(self) -> None:
        """Print the total number of pending items across all cache streams."""
        r = aioredis.Redis.from_url(self._redis_url)
        try:
            keys = await r.keys(f"{self._stream_name_prefix}_*")
            total = 0
            for key in keys:
                try:
                    total += await r.xlen(key)
                except Exception:
                    pass
            print(f"Overall pending across all streams: {total}")
        finally:
            await r.aclose()

    async def _clear_processing_queues(self, dry_run: bool, plugin_name: Optional[str] = None) -> None:
        """Clear a cache stream.

        Args:
            dry_run: If ``True``, only print what would be cleared without modifying Redis.
            plugin_name: If provided, clear the job stream for this plugin.
                         If ``None``, clear the results stream.
        """
        r = aioredis.Redis.from_url(self._redis_url)
        try:
            if plugin_name is not None:
                stream_name = f"{plugin_name}_jobs"
            else:
                stream_name = "results"

            print(f"resetting stream: {stream_name}")

            if not dry_run:
                await r.delete(f"{self._stream_name_prefix}_{stream_name}")
        finally:
            await r.aclose()
