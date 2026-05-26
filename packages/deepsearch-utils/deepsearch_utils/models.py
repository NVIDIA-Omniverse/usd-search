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

from pydantic_settings import BaseSettings, SettingsConfigDict


class RendererType(str, Enum):
    farm = "farm"
    k8s = "k8s"
    rendering_service = "rendering_service"


class DeepSearchRendererConfig(BaseSettings):
    renderer_type: RendererType = RendererType.k8s
    clear_rendering_stream_on_startup: bool = False
    pending_job_limit: int = -1
    model_config = SettingsConfigDict(env_prefix="deepsearch_renderer_config_")
