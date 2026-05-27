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
from typing import List, Optional, Union

from pydantic import BaseModel, Field

from ..models import RenderingStatus


class HealthStatus(str, Enum):
    OK = "ok"


class ReadinessStatus(str, Enum):
    OK = "ok"
    NOT_READY = "not_ready"


class HealthResponse(BaseModel):
    status: HealthStatus = Field(..., title="status of the service")


class ReadinessResponse(BaseModel):
    status: ReadinessStatus = Field(..., title="status of the service")
    reason: Optional[str] = Field(default=None, title="reason for the status")


class KitProcessInfo(BaseModel):
    worker_id: str = Field(..., title="worker ID")
    pid: int = Field(..., title="process ID")
    memory_usage: int = Field(..., title="memory usage in MB")
    memory_limit: Optional[int] = Field(default=None, title="memory limit in MB (unlimited if None)")
    memory_usage_percentage: Optional[float] = Field(default=None, title="memory usage percentage (None if unlimited)")


class WorkerInfo(BaseModel):
    active_requests: int = Field(..., title="number of active requests")
    max_requests: int = Field(..., title="maximum number of requests")
    waiting_requests: int = Field(..., title="number of waiting requests")
    kit_processes: Optional[List[KitProcessInfo]] = Field(default=None, title="list of kit processes")


class GeneralInfo(BaseModel):
    version: str = Field(..., title="version of the service")
    name: str = Field(default="USD Search Rendering Service", title="name of the service")
    worker_info: WorkerInfo = Field(..., title="worker information")


class URLType(str, Enum):
    omniverse = "omniverse"
    s3 = "s3"


class ContentType(BaseModel):
    path: str = Field(..., title="URL of the asset that is being loaded")
    content: str = Field(..., title="serialized content of rendered data")
    exception: Optional[str] = Field(default=None, title="exception message")
    traceback: Optional[str] = Field(default=None, title="traceback of the exception")


class SupportedMediaTypes(str, Enum):
    json = "application/json"
    zip = "application/zip"


class RenderResponse(BaseModel):
    images: Optional[Union[str, List[str]]] = Field(default=None, title="rendered data")
    camera_metadata: Optional[List[str]] = Field(default=None, title="camera metadata")
    status: RenderingStatus = Field(default=RenderingStatus.success, title="status of the request")
