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

# standard modules
from enum import Enum
from typing import Any, List, Optional, TypedDict, Union

# third party modules
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings
from typing_extensions import NotRequired

END = b"GENERATOR_FINISHED"


class JobItemType(str, Enum):
    normal = "normal"
    priority = "priority"
    none = "none"


class ResultItem(TypedDict):
    uri: str
    hash_value: str
    prediction: dict
    asset_data: dict
    retry_count: NotRequired[int]
    asset_status: NotRequired[Any]


class JobItem(TypedDict):
    uri: str
    plugin_name: str
    hash_value: NotRequired[Optional[str]]
    job_type: NotRequired[Union[JobItemType, str]]


class CacheConnectionError(ConnectionError):
    pass


class PluginCacheConfig(BaseSettings):
    plugin_status_history_length: int = 5


class GenericPluginStatus(str, Enum):
    ok = "ok"
    queued = "queued"
    processing = "processing"
    failed = "failed"
    failed_retries_exhausted = "failed_retries_exhausted"


class PluginItemStatus(BaseModel):
    status: str = Field(..., description="asset status")
    hash_value: Optional[Union[str, bytes]] = Field(default=None, description="hash of the asset")
    processing_timestamp: Union[float, str] = Field(..., description="processing date")
    exception: Optional[str] = Field(default=None, description="reason for the Non Ok status")


class PluginItemStatusHistory(BaseModel):
    item_status_history: List[PluginItemStatus] = Field(..., description="list of asset statuses")

    class Config:
        history_length: int = PluginCacheConfig().plugin_status_history_length

    @field_validator("item_status_history")
    def history_length_validation(cls, v: List[PluginItemStatus]) -> List[PluginItemStatus]:
        if len(v) > cls.Config.history_length:
            v = v[: cls.Config.history_length]
        return v
