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
from langchain_openai import ChatOpenAI
from pydantic import Field

# local / proprietary modules
from .base_vlm import BaseVLM, VLMConfig, VLMService


class InferenceHubVLMConfig(VLMConfig):
    api_key: str = Field()
    model: str = Field(default="gcp/google/gemini-3-flash-preview")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0)
    base_url: str = Field(default="https://inference-api.nvidia.com")

    class Config:
        env_prefix = "inference_hub_"


class InferenceHubVLM(BaseVLM):
    def __init__(self, vlm_config: Optional[InferenceHubVLMConfig] = None):
        if vlm_config is None:
            vlm_config = InferenceHubVLMConfig()
        vlm = ChatOpenAI(**vlm_config.model_dump())

        super().__init__(
            vlm=vlm,
            vlm_service=VLMService.inference_hub,
            model=vlm_config.model,
        )
