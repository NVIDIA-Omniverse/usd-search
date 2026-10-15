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

from pydantic import Field
from pydantic_settings import BaseSettings


class RedisCacheConfig(BaseSettings):
    url: str = Field(default="redis://localhost:6379", alias="redis_url")
    stream_name_prefix: str = "deepsearch"
    consumer_group: str = Field(default="deepsearch-worker-pool", alias="cache_consumer_group")
    results_consumer_group: str = "deepsearch-worker-pool"
    consumer_name_prefix: str = "deepsearch-worker"
    plugin_prefix: bytes = Field(default=b"p", alias="cache_plugin_prefix")
    auto_trim_timeout: float = Field(default=5, alias="cache_auto_trim_timeout")
    reset_stream_on_corruption: bool = True
    # How long an item may be in flight before another worker is allowed to claim
    # it. This is the recovery path for a worker that *died* mid-item (a worker
    # that fails and stays alive requeues the item straight away - see
    # ``RedisStreamConfig.requeue_failed_items``), so the value only has to exceed
    # the longest a healthy worker can legitimately hold one item.
    farm_job_autoclaim_min_idle_time: int = 3 * 60 * 60_000  # 3 hrs: a render can take that long
    # Long enough to cover the slowest non-render plugin: asset-graph generation
    # allows 30 min to build the graph plus 30 min to store it.
    non_farm_job_autoclaim_min_idle_time: int = 90 * 60_000  # 90 min
    # The writer only upserts a document per result, so anything idle for minutes
    # is stuck rather than busy.
    results_autoclaim_min_idle_time: int = 5 * 60_000  # 5 min
    # Attempts an item gets before it is reported and dropped from its stream. This
    # is one budget for both ways an item can fail - the worker raised, or it died
    # holding the item - because the attempt count is carried on the queued item.
    # Set to -1 to keep retrying forever: nothing is ever dropped, at the cost of
    # reprocessing an item that cannot succeed for as long as it keeps failing.
    job_autoclaim_n_retries: int = 5
    # Results are far more expensive to recreate than to retry (the asset has to be
    # crawled and inferred again), so -1 is a defensible setting here - but it is
    # not the default: a document the search backend will never accept would then
    # occupy the writer indefinitely.
    results_autoclaim_n_retries: int = 5
