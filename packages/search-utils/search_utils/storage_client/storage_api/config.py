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
from typing import List, Optional

from pydantic import Field
from pydantic_settings.main import SettingsConfigDict

from search_utils.storage_client import StorageClientConfig

STORAGE_CREATED = "omni.storage.created"
STORAGE_DELETED = "omni.storage.deleted"
STORAGE_DIR_CREATED = "omni.storage.dir_created"
STORAGE_DIR_DELETED = "omni.storage.dir_deleted"

STORAGE_EVENTS = [
    STORAGE_CREATED,
    # STORAGE_DELETED,
    # STORAGE_DIR_CREATED,
    # STORAGE_DIR_DELETED,
]


class KnownStorageAPITypes(str, Enum):
    sevan = "sevan"


class ThumbnailStyle(str, Enum):
    nucleus = "nucleus"
    storage_api = "storage_api"


class StorageAPIStorageClientConfig(StorageClientConfig):
    grpc_endpoint: str = Field(default="localhost:50051", description="GRPC endpoint for the Storage API")
    token: Optional[str] = Field(default=None, description="Token for the Storage API")
    ssl: Optional[bool] = Field(default=False, description="Use SSL for Storage API")
    headers: Optional[dict] = Field(default=None, description="Metadata for Storage API")
    base_uri: Optional[str] = Field(default=None, description="Base URI for the Storage API")
    upload_preference: Optional[str] = Field(default=None, description="Upload preference for the Storage API")
    download_preference: Optional[str] = Field(default=None, description="Download preference for the Storage API")
    re_scan_timeout: Optional[float] = 86400  # in seconds (equivalent to 1 day)
    apply_url_quote: Optional[bool] = Field(default=False, description="Apply URL quote to the URI")
    storage_api_type: Optional[KnownStorageAPITypes] = Field(default=None, description="Storage API type")
    user_metadata_keys: Optional[List[str]] = Field(default=[], description="User metadata keys for the Storage API")
    list_queue_limit: int = Field(
        default=0,
        description="Limit the number of items in the list queue, 0 means no limit",
    )
    ignore_filefolder_api: bool = Field(default=False, description="Ignore filefolder API")
    thumbnail_style: ThumbnailStyle = Field(
        default=ThumbnailStyle.storage_api,
        description="Thumbnail style for the Storage API",
    )
    thumbnail_metadata_fields: List[str] = Field(
        default=["thumbnail_url"],
        description="Thumbnail metadata field for the Storage API",
    )

    # Notification service config
    notification_service_grpc_endpoint: Optional[str] = Field(
        default=None, description="Notification service endpoint for the Storage API"
    )
    notification_subscription_enabled: Optional[bool] = Field(
        default=False, description="Enable notification subscription"
    )

    # OpenID config
    openid_client_id: Optional[str] = Field(default=None, description="Client ID for the Storage API")
    openid_client_secret: Optional[str] = Field(default=None, description="Client secret for the Storage API")
    openid_token_url: Optional[str] = Field(default=None, description="OpenID token URL for the Storage API")
    openid_scope: Optional[str] = Field(default=None, description="OpenID scope for the Storage API")
    openid_grant_type: Optional[str] = Field(
        default="client_credentials",
        description="OpenID grant type for the Storage API",
    )
    token_refresh_interval: Optional[int] = Field(
        default=1800,
        description="Token refresh interval for the Storage API (in seconds)",
    )

    model_config = SettingsConfigDict(env_prefix="storage_api_")
