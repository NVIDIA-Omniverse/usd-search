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

from pydantic import BaseModel, Field


class RenderingPostRequest(BaseModel):
    url: str = Field(description="URL of an asset that needs to be rendered")
    force_render: bool = Field(default=False, description="Force render the asset")
    enable_caching: bool = Field(default=True, description="Enable caching")
    asset_rendering_timeout: Optional[float] = Field(default=None, description="Asset rendering timeout")
    kit_worker_memory_limit: Optional[int] = Field(default=None, description="Kit worker memory limit in MB")
    storage_api_url: Optional[str] = Field(
        default=None,
        description="Storage API gRPC endpoint to open the asset from (Storage API backend only)",
    )
