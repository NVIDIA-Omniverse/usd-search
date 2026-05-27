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
from typing import Any, Dict, Optional

# local / proprietary modules
from cache.src import PluginItemStatus

# third party modules
from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict


class PluginProcessingResult(TypedDict):
    asset_status: PluginItemStatus
    search_backend_content: NotRequired[Dict[str, Any]]


class GenericPluginErrorItem(BaseModel):
    status: str = Field(..., description="error status")
    error_message: Optional[str] = Field(default=None, description="error message details")
