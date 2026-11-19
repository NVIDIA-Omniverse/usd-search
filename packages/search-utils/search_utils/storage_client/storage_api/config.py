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

import logging
from enum import Enum
from typing import List, Optional

from pydantic import Field, ValidationInfo, field_validator, model_validator
from pydantic_settings.main import SettingsConfigDict

from search_utils.storage_client import StorageClientConfig

logger = logging.getLogger(__name__)

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
    token_file: Optional[str] = Field(
        default=None,
        description=(
            "Path to a file containing the bearer token for the Storage API. When set, the "
            "token is read from this file and re-read every `token_refresh_interval` seconds."
        ),
    )
    ssl: Optional[bool] = Field(default=False, description="Use SSL for Storage API")
    headers: Optional[dict] = Field(default=None, description="Metadata for Storage API")
    base_uri: Optional[str] = Field(
        default=None,
        description=(
            "Base URI (namespace root) for the Storage API. Optional and authoritative: when set, the "
            "client is scoped to this single namespace. When unset (or blank), backends are discovered "
            "via ListTopLevelAddresses (a deployment may serve several buckets); if the server does not "
            "implement that call, base_uri must be provided."
        ),
    )
    allowed_top_level_addresses: List[str] = Field(
        default=[],
        description=(
            "Restrict operation to this subset of discovered top-level addresses (buckets / namespace "
            "roots). Empty (default) uses every address ListTopLevelAddresses reports. Ignored (with a "
            "warning) when base_uri is set."
        ),
    )
    top_level_addresses_ttl: float = Field(
        default=0,
        description=(
            "Seconds after which the discovered top-level addresses are re-read via ListTopLevelAddresses, "
            "so roots the server starts serving later are picked up without a restart. 0 (default) resolves "
            "them once per process. Ignored when base_uri is set."
        ),
    )
    top_level_addresses_drop_after_misses: int = Field(
        default=2,
        ge=1,
        description=(
            "Drop a known top-level address only after this many consecutive refreshes (see "
            "top_level_addresses_ttl) without it, so a Storage API restarting with a partially loaded "
            "catalog cannot shrink the list -- which, with unsupported-URI removal enabled in the storage "
            "cron, would delete that root's assets from the index. 1 drops it at the first miss."
        ),
    )
    top_level_addresses_timeout: float = Field(
        default=30,
        gt=0,
        description=(
            "Deadline in seconds for a ListTopLevelAddresses call. A call that exceeds it is treated like "
            "any other failed discovery: the initial resolution leaves the roots unresolved, a refresh "
            "keeps the known ones, so a hung Storage API cannot stall callers waiting on the refresh."
        ),
    )
    upload_preference: Optional[str] = Field(default=None, description="Upload preference for the Storage API")
    download_preference: Optional[str] = Field(default=None, description="Download preference for the Storage API")
    full_listing_enabled: bool = Field(default=True, description="List the whole backend on startup and every re-scan")
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

    @field_validator("grpc_endpoint", "notification_service_grpc_endpoint")
    @classmethod
    def _bare_grpc_target(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        """gRPC targets must be a bare `host:port`.

        grpc-python does not accept an `http://` / `https://` target: the channel is created
        without complaint and then never connects, so a scheme here shows up as a hang rather
        than an error. TLS is selected by `ssl`, not by the endpoint string.
        """
        if v is not None and "://" in v:
            raise ValueError(
                f"{info.field_name} must be a bare 'host:port' without a scheme (got {v!r}); "
                "grpc-python never connects to a scheme-prefixed target. Use `ssl` to select TLS."
            )
        return v

    @model_validator(mode="after")
    def _warn_plaintext_on_443(self) -> "StorageAPIStorageClientConfig":
        """Flag the one endpoint form no `kit_storage_api_url` spelling can rescue."""
        if not self.ssl and self.grpc_endpoint.rsplit(":", 1)[-1] == "443":
            logger.warning(
                "Storage API ssl is off but grpc_endpoint %r is on port 443: omni.client keeps "
                "port 443 on TLS whatever the scheme, so the Kit workers (asset-graph builder, "
                "rendering) cannot reach this deployment. Serve plaintext on another port, or "
                "enable ssl.",
                self.grpc_endpoint,
            )
        return self

    @model_validator(mode="after")
    def _warn_no_source_of_items(self) -> "StorageAPIStorageClientConfig":
        """Flag the combination that leaves the crawler with nothing to index."""
        if not self.full_listing_enabled and not self.notification_subscription_enabled:
            logger.warning(
                "Storage API full_listing_enabled and notification_subscription_enabled are both off, so the "
                "crawler has no source of items. Enable one of them, or index by hand."
            )
        return self

    @property
    def kit_storage_api_url(self) -> str:
        """`grpc_endpoint` in the form Kit needs, for the services that hand it to `omni.client`.

        Kit (the graph-builder and rendering-job workers) registers the Storage API through
        `omni.client.register_storage_direct`, which never sees `ssl`: it infers TLS from the
        endpoint string alone. A bare `host:port` means TLS for every host except `localhost` /
        `127.0.0.1` and port 80, so a plaintext deployment fails the handshake. An explicit
        `http://` scheme says plaintext -- except on port 443, which omni.client keeps secure
        regardless, so a plaintext server there is still out of reach from Kit (hence the
        warning from `_warn_plaintext_on_443`).

        grpc-python needs a bare target, so `grpc_endpoint` stays scheme-less (enforced by
        `_bare_grpc_target`) and only this Kit-bound copy carries the scheme.
        """
        return self.grpc_endpoint if self.ssl else f"http://{self.grpc_endpoint}"
