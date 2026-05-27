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

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import TypedDict


class DeepSearchBackendConfig(BaseSettings):
    """Backend-side settings consumed by the deepsearch-api service.

    Field names ending in ``_n_*`` (e.g. ``asset_graph_service_n_retries``) are
    preserved verbatim from the legacy ``ng_search`` config to keep the
    ``DEEPSEARCH_BACKEND_*`` environment-variable surface backwards-compatible.
    A future migration may rename them to ``_max_*`` via ``Field(alias=...)``.
    """

    use_prom_metrics: bool = False
    max_queries: int = 150
    max_results_total: int = 10000
    log_level: str = "INFO"
    default_search_size: int = 64
    default_search_method: str = "exact"
    admin_access_key: Optional[str] = None
    backend_version: str = ""
    admin_source_text: str = "admin_access"
    asset_graph_service_url: Optional[str] = None
    asset_graph_service_n_parallel_requests: int = 25
    asset_graph_service_n_retries: int = 5
    max_pages: int = 20
    uploaded_image_search_limit: int = 10

    model_config = SettingsConfigDict(env_prefix="deepsearch_backend_")


class TelemetryContext(TypedDict):
    session_id: str
    app_name: str
    app_version: str
    ui_name: str
    ui_version: str
    kit_version: Optional[str]
    search_request_id: Optional[str]
