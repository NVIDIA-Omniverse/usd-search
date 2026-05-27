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

from typing import Awaitable, Optional, TypedDict

from cache.src.client.redis_metrics import RedisCacheMetrics
from prometheus_client import Gauge


class MonitorServiceTasks(TypedDict):
    storage_connection_init: Awaitable[None]
    process_queue: Awaitable[None]
    collect_system_metrics: Optional[Awaitable[None]]
    collect_cache_metrics: Optional[Awaitable[None]]
    initial_queues_cleanup: Optional[Awaitable[None]]


class MonitorPromMetrics(TypedDict):
    redis_cache_metrics: Optional[RedisCacheMetrics]
    processed_metric: Gauge
    queued_length_metric: Gauge
    progress_metric: Gauge
