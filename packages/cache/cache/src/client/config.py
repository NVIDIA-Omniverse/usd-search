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
    farm_job_autoclaim_min_idle_time: int = 3 * 60 * 60_000  # hrs - mins - ms
    non_farm_job_autoclaim_min_idle_time: int = 3 * 60 * 60_000  # hrs - mins - ms
    results_autoclaim_min_idle_time: int = 3 * 60 * 60_000  # hrs - mins - ms
    job_autoclaim_n_retries: int = 5  # default number of retries for the job
