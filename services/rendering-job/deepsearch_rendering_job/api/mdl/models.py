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

from pydantic import BaseModel, Field


class BaseObjectType(str, Enum):
    sphere = "sphere"
    shaderknob = "shaderknob"


class MDLRenderingPostRequest(BaseModel):
    url: str = Field(description="URL of an asset that needs to be rendered")
    mtl_names: Optional[Optional[List[str]]] = Field(default=None, description="MTL name that need to be rendered.")
    width: int = Field(default=448, gt=0, description="Width of the thumbnail")
    height: int = Field(default=448, gt=0, description="Height of the thumbnail")
    base_object_type: Optional[BaseObjectType] = Field(
        default=None, description="Base object type that need to be rendered."
    )
    mdl_template_url: Optional[str] = Field(default=None, description="Template URL that need to be rendered.")
    mdl_stdin: Optional[str] = Field(default=None, description="STDIN that need to be rendered.")
