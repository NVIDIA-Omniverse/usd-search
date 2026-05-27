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

import socket
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings
from pydantic_settings.main import SettingsConfigDict

from search_utils.streams import AvailableStreamTypes


class BaseConfig(BaseSettings):
    stream_name: str = "deepsearch-crawler"
    log_level: str = "INFO"
    stream_type: AvailableStreamTypes = AvailableStreamTypes.redis  # type: ignore[no-any-unimported]  # missing stubs
    use_prom_metrics: bool = True
    metric_name: str
    prom_metrics_port: int = 8000
    metrics_collect_timeout: float = 5
    stream_connection_timeout: float = 5
    omni_service: str = Field(alias="ov_service", default="deepsearch-crawler")
    omni_instance: str = Field(alias="ov_instance", default=socket.gethostname())
    model_config = SettingsConfigDict(env_prefix="deepsearch_crawler_")


class ConsumerConfig(BaseConfig):
    stream_group_name: str = "default-group-reader"
    stream_consumer_name: str = "default-stream-consumer"
    metric_name: str = "deepsearch-consumer"


class ExtraCrawlerConfig(BaseSettings, extra="allow"):
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None


class CrawlerConfig(BaseConfig):
    path: str = "/"
    ignore_patterns: str = '["/.thumbs/"]'
    stream_group_str: Optional[str] = None
    stream_group_file: Optional[str] = None
    reset_on_startup: bool = False
    trim_tail_timeout: float = 300
    mount_check_timeout: float = 3600
    mount_list_timeout: float = 86400
    metric_name: str = "deepsearch_crawler"
    recreate_subscription_on_error: bool = True
    extra_config_file: Optional[str] = None
