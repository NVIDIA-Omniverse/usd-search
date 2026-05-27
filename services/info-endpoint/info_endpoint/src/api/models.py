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

from enum import Enum
from typing import Any, Dict, List, Optional

from cache.src import PluginItemStatus
from plugins import Plugins
from pydantic import BaseModel, Field

from search_utils.storage_client import AvailableStorageClients, PathType


class PluginStatusType(str, Enum):
    in_sync = "in_sync"
    out_of_sync = "out_of_sync"
    out_of_sync_and_failed_indexing = "out_of_sync_and_failed_indexing"
    failed_indexing = "failed_indexing"
    not_found = "not_found"


class BackendStatusType(str, Enum):
    ok = "ok"
    file_not_found = "file_not_found"


class ProcessingStatus(str, Enum):
    submitted = "submitted"
    invalid_url = "invalid_url"
    no_assets_to_process = "no_assets_to_process"


class HealthStatus(str, Enum):
    healthy = "healthy"
    unhealthy = "unhealthy"


class PluginInfo(BaseModel):
    indexing_status: PluginStatusType = Field(..., description="Indexing status of the asset for a given plugin")
    indexed_asset_hash: Optional[str] = Field(
        default=None,
        description="Hash of the indexed asset. If equal to the hash of the asset in storage, the indexed asset is up to date.",
    )
    plugin_status_history: Optional[List[PluginItemStatus]] = Field(
        default=None, description="status history for plugins"
    )


class AssetStorageBackendInfo(BaseModel):
    asset_status: BackendStatusType = Field(..., description="Status of the asset in the storage backend")
    storage_asset_hash: Optional[str] = Field(default=None, description="Current hash value of the asset in storage")
    metadata: Optional[PathType] = Field(default=None, description="asset metadata")


class StatusResult(BaseModel):
    url: str = Field(..., description="URL of the asset")
    plugins_statuses: Dict[str, PluginInfo] = Field(..., description="Indexing status of the asset for each plugin")
    storage_backend_info: AssetStorageBackendInfo = Field(..., description="Status of the asset on the storage backend")


class HealthResponse(BaseModel):
    status: HealthStatus = Field(..., description="service health status")


class StorageBackendItemInfo(BaseModel):
    storage_backend_type: AvailableStorageClients
    base_url: str
    s3_endpoint_url: Optional[str] = None
    available: Optional[bool] = None


class StorageBackendInfo(BaseModel):
    backends: Dict[str, StorageBackendItemInfo]


class AssetProcessingResponse(BaseModel):
    status: ProcessingStatus = Field(..., description="Asset processing status")
    plugins: List[Plugins] = Field(
        ...,
        description="List of plugins for which re-indexing of the asset was triggered",
    )
    ignored_plugins: List[Plugins] = Field(
        ...,
        description="Plugins omnitted from processing due to user selection or being inactive",
    )
    metadata_refreshed: bool = Field(default=False, description="Whether asset metadata was refreshed")
    tags_refreshed: bool = Field(default=False, description="Whether asset tags were refreshed")


class PluginDescription(BaseModel):
    """Description of an asset processing plugin available on this USD Search instance."""

    name: str = Field(description="Plugin identifier (e.g., 'siglip2_embedding', 'thumbnail', 'usd_metadata', 'tags')")
    description: str = Field(description="Human-readable description of what this plugin processes and produces")
    data_types: List[str] = Field(
        description="File extensions this plugin can process (e.g., ['usd', 'usda', 'usdc', 'usdz', 'jpg', 'png'])"
    )
    requires_rendering: bool = Field(
        description="Whether this plugin requires GPU rendering (Omniverse Kit) to process assets. If true, processing may be slower."
    )
    active: bool = Field(
        description="Whether this plugin is currently enabled and processing assets on this USD Search instance"
    )
    config: Dict[str, Any] = Field(
        description="Plugin-specific configuration parameters (model names, batch sizes, etc.)"
    )
