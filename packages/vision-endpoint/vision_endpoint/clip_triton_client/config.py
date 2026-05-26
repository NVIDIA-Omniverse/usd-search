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
from typing import Optional

# third party modules
from pydantic import Field
from pydantic_settings import BaseSettings


class TritonClientSettings(BaseSettings):
    """TritonClient setting class"""

    triton_server_url: str = Field(default="0.0.0.0:8001", description="GPRC Triton server endpoint")
    triton_server_auth_token: Optional[str] = Field(default=None, description="Authentication token for Triton server")
    triton_server_ssl: Optional[bool] = Field(default=False, description="SSL for Triton server")
    triton_server_headers: Optional[dict] = Field(default=None, description="Metadata for Triton server")
    model_name: Optional[str] = Field(default=None, description="Name of the model to use for inference")
    model_version: Optional[str] = Field(default="1", description="Model version")
    request_input: Optional[str] = Field(default=None, description="Name of the input to use for inference")
    request_output: Optional[str] = Field(default=None, description="Name of the output to use for inference")
    infer_datatype: Optional[str] = Field(default=None, description="Data type for inference")
