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

from typing import List, Optional

from deepsearch_api.models import Prim
from pydantic import BaseModel
from typing_extensions import NotRequired, TypedDict


class AGSAssetData(BaseModel):
    instance_prims: Optional[List[Prim]] = None
    root_prims: Optional[List[Prim]] = None
    default_prims: Optional[List[Prim]] = None


class TelemetryContext(BaseModel):
    session_id: str
    app_name: str
    app_version: str
    ui_name: str
    ui_version: str
    kit_version: Optional[str] = None
    search_request_id: Optional[str] = None


class TelemetryExtraFields(TypedDict):
    source: NotRequired[str]
    user_initiated: NotRequired[str]
    deepsearch_session_id: NotRequired[str]
    session_id: NotRequired[str]
    appName: NotRequired[str]
    appVersion: NotRequired[str]
    uiName: NotRequired[str]
    uiVersion: NotRequired[str]
    app: NotRequired[str]
    kitVersion: NotRequired[str]
