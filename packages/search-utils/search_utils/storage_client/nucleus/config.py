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

from typing import Optional, Union

from pydantic import Field

from search_utils.storage_client import StorageClientConfig
from search_utils.storage_client.nucleus.auth import NucleusAuth, NucleusAuthEnv


class NucleusStorageConfig(StorageClientConfig):
    ov_server: str
    timeout: float = Field(
        default=3600,
        alias="ov_conn_timeout_s",
        description="Nucleus connection timeout",
    )
    auth: Union[NucleusAuthEnv, NucleusAuth] = Field(
        default_factory=NucleusAuthEnv, description="Nucleus authentication"
    )
    user_agent: Optional[str] = None
    skip_mounts: bool = False
