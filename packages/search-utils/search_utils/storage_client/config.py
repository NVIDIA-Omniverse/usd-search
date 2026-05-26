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
from typing import Type

from pydantic.config import ConfigDict
from pydantic_settings.main import BaseSettings


class AvailableStorageClients(str, Enum):
    nucleus = "nucleus"
    s3 = "s3"
    storage_api = "storage_api"


class StorageConfig(BaseSettings):
    storage_backend_type: AvailableStorageClients = AvailableStorageClients.nucleus


class StorageClientConfig(BaseSettings):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


def get_backend_config_class(
    backend_type: AvailableStorageClients,
) -> Type[StorageClientConfig]:
    if backend_type == AvailableStorageClients.nucleus:
        from search_utils.storage_client.nucleus.config import NucleusStorageConfig

        return NucleusStorageConfig
    elif backend_type == AvailableStorageClients.s3:
        from search_utils.storage_client.s3.config import S3StorageClientConfig

        return S3StorageClientConfig
    elif backend_type == AvailableStorageClients.storage_api:
        from search_utils.storage_client.storage_api.config import (
            StorageAPIStorageClientConfig,
        )

        return StorageAPIStorageClientConfig
    else:
        raise NotImplementedError(f"Backend {backend_type} is not supported")
