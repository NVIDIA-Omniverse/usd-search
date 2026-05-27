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

from typing import List, Optional, TypedDict

import numpy as np
from pydantic import Field

from ..farm.data import ResponseStatus
from ..models import DeepSearchRendererConfig, RendererType


class RenderingServiceConfig(DeepSearchRendererConfig):
    renderer_type: RendererType = RendererType.rendering_service
    rendering_service_url: str = Field(..., description="URL of the rendering service")
    endpoint: str = Field(default="/usdsearch/render", description="Endpoint of the rendering service")
    health_check_endpoint: str = Field(default="/health", description="Health check endpoint of the rendering service")
    readiness_endpoint: Optional[str] = Field(
        default="/readyz", description="Readiness endpoint of the rendering service"
    )
    force_render: bool = Field(default=True, description="Force rendering")
    enable_caching: bool = Field(default=False, description="Enable caching")
    extra_headers: Optional[dict] = Field(default=None, description="Extra headers to send to the rendering service")
    api_key: Optional[str] = Field(default=None, description="API key to send to the rendering service")
    maximum_parallel_requests: int = Field(
        default=10,
        description="Maximum number of parallel requests to the rendering service",
    )
    retry_timeout_on_busy: float = Field(default=5, description="Retry timeout on busy")
    connection_timeout: float = Field(
        default=30.0,
        description="Timeout in seconds for establishing a connection to the rendering service",
    )
    read_timeout: Optional[float] = Field(
        default=None,
        description="Timeout in seconds for establishing a connection to the rendering service",
    )
    nvcf_request_polling_endpoint: str = Field(
        default="https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/",
        description="Endpoint to poll the status of the rendering service",
    )


class RenderingResponse(TypedDict):
    images: List[np.ndarray]
    camera_metadata: Optional[List[dict]]
    status: ResponseStatus
