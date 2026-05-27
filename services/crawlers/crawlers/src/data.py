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

from datetime import datetime
from enum import Enum
from typing import Awaitable, List, Optional, TypedDict, Union

from prometheus_client import Gauge
from pydantic import BaseModel, Field


class PathMetaData(BaseModel):
    # required fields
    path: str = Field(..., description="Path to an asset")
    name: str = Field(..., description="Name of the asset")
    pathType: str = Field(..., description="Type of the asset")
    created_by: Optional[str] = Field(default=None, description="User ID, who created the asset")
    modified_by: Optional[str] = Field(default=None, description="User ID, who last modified the asset")
    created_timestamp: Optional[datetime] = Field(default=None, description="Date, when the file was created")
    modified_timestamp: Optional[datetime] = Field(..., description="Date, when the file was last modified")
    empty: Optional[bool] = Field(default=None, description="Flag to mark that the asset is empty")
    on_mount: bool = Field(..., description="Flag to know if the asset is on mount or not")
    size: Optional[int] = Field(default=None, description="Size of the asset")

    # optional fields
    etag: Optional[str] = Field(default=None, description="Asset's unique ID number")
    hash_type: Optional[str | list[str]] = Field(default=None, description="Type of hashing applied to the asset")
    hash_value: Optional[str] = Field(default=None, description="Hash value for the asset's content")
    hash_block_size: Optional[Union[int, str]] = Field(default=None, description="Hash block size")
    ext: Optional[str] = Field(default=None, description="Extension of the asset")
    status: Optional[str] = Field(default=None, description="Status of the asset")
    is_deleted: Optional[bool] = Field(default=None, description="Flag to know if asset was soft-deleted")
    deleted_by: Optional[str] = Field(
        default=None,
        description="User who deleted the asset last time (in case it was restored after deletion)",
    )
    deleted_timestamp: Optional[datetime] = Field(
        default=None,
        description="Date, when the asset was last deleted (in case it was restored after deletion)",
    )


class CrawlerServiceTasks(TypedDict):
    storage_connection_init: Awaitable[None]
    process_queue: Awaitable[None]
    collect_system_metrics: Optional[Awaitable[None]]


class CrawlerPromMetrics(TypedDict):
    progress_metric: Gauge
    queued_length_metric: Gauge
    processed_metric: Gauge
    cached_length_metric: Gauge
    backlog_length_metric: Gauge


class IndexerType(str, Enum):
    indexing = "indexing"
    tag_crawler = "tag_crawler"


class TagContent(TypedDict):
    tag: str
    namespace: str
    value: str


class TagDataContent(TypedDict):
    tags: List[TagContent]


class ActualizationStats(TypedDict):
    removed: float
    cache_size: int
