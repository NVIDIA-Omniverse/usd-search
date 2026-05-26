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
import socket

# third party modules
from pydantic import Field
from pydantic_settings import BaseSettings


class DeepSearchCrawlerConfig(BaseSettings):
    omni_service: str = Field(..., alias="ov_service")
    stream_group_name: str = Field(..., alias="ov_instance")
    redis_url: str = Field(default="redis://redis", alias="redis_url")
    log_level: str = "INFO"
    prom_metrics_port: int = Field(default=8000)
    use_prom_metrics: bool = True
    metric_name: str
    omni_instance: str = socket.gethostname()
    storage_service_host: str = Field(default="localhost", alias="ngsearch_storage_host")
    storage_service_port: int = Field(default=3703, alias="ngsearch_storage_port")
    idle_timeout: float = 1
    exclude_uri_substrings: str = Field(default='["/.thumbs/", ".__omni_channel__"]', alias="ov_exclude_path_indexing")
    metadata_redis_dict_database: int
    metadata_redis_check_timeout: int = 86400  # 1 day (in seconds)
    verify_asset_existence: bool = False
    existence_check_before_metadata_extraction: bool = False
    processing_batch_size: int = 1


class DeepSearchIndexingConfig(DeepSearchCrawlerConfig):
    omni_service: str = "deepsearch-nucleus-indexing"
    stream_group_name: str = "indexing-service"
    metric_name: str = "indexing"
    metadata_redis_dict_database: int = 3
    verify_asset_existence: bool = True


class DeepSearchTagCrawlerConfig(DeepSearchCrawlerConfig):
    omni_service: str = "deepsearch-tag-crawler"
    stream_group_name: str = "tag-crawler-service"
    metric_name: str = "tag_crawler"
    metadata_redis_dict_database: int = 1
    verify_asset_existence: bool = (
        False  # This parameter allows verifying asset's existence after asset metadata is prepared
    )
    existence_check_before_metadata_extraction: bool = True
