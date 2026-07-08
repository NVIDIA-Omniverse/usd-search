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

from pydantic_settings.main import SettingsConfigDict

from search_utils.storage_client import StorageClientConfig


class S3StorageClientConfig(StorageClientConfig):
    bucket_name: str
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    aws_endpoint_url: Optional[str] = None
    region_name: Optional[str] = None
    allow_system_writes: Optional[bool] = True
    allow_non_system_writes: Optional[bool] = True
    system_path_prefix: str = ".omniverse/deepsearch"
    re_scan_timeout: Optional[float] = 86400  # in seconds (equivalent to 1 day)
    # Size of the underlying HTTP connection pool. The botocore default is 10,
    # which becomes a bottleneck when many requests are issued concurrently
    # (e.g. several parallel monitor task processors sharing one client all
    # fetching thumbnails from S3 at once). Raise this to allow more in-flight
    # connections before requests start queueing for a free socket.
    max_pool_connections: int = 50

    model_config = SettingsConfigDict(env_prefix="s3_storage_")
