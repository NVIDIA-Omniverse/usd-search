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
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SupportedStorageFields(str, Enum):
    image = "image"
    pointcloud = "pointcloud"


class IndexConfig(BaseSettings):
    embedding_field_name: str = Field(default="siglip2-embedding", description="Name of the embedding field")
    embedding_field_dim: int = Field(default=1536, description="Dimensionality of the embedding field")
    supported_storage_fields: List[SupportedStorageFields] = Field(
        default=[SupportedStorageFields.image], description="Supported storage fields"
    )

    model_config = SettingsConfigDict(env_prefix="index_config_")
