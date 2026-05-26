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
from langchain_openai import AzureChatOpenAI
from pydantic import Field

# local / proprietary modules
from .base_vlm import BaseVLM, VLMConfig, VLMService


class AzureOpenAIVLMConfig(VLMConfig):
    """
    https://oneapi-doc.perflab.nvidia.com/docs/getting_started/hello_world_example
    """

    api_key: str = Field()
    model: str = Field(default="gemini-3-flash-preview")
    api_version: str = Field(default="2025-02-01-preview")
    azure_endpoint: str = Field(default="https://llm-proxy.perflab.nvidia.com")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0)
    azure_deployment: str | None = None
    reasoning_models: tuple[str, ...] = Field(default=("o3", "o4", "gpt-5"))

    class Config:
        env_prefix = "azure_openai_"


class AzureOpenAIVLM(BaseVLM):
    def __init__(self, vlm_config: Optional[AzureOpenAIVLMConfig] = None):
        if vlm_config is None:
            vlm_config = AzureOpenAIVLMConfig()

        vlm_config_dump = self.check_config(vlm_config)
        vlm = AzureChatOpenAI(**vlm_config_dump)

        super().__init__(
            vlm=vlm,
            vlm_service=VLMService.azure_openai,
            model=vlm_config.model,
        )

    def check_config(self, vlm_config: AzureOpenAIVLMConfig):
        vlm_config.azure_deployment = vlm_config.model
        vlm_config_dump = vlm_config.model_dump()
        for reasoning_model in vlm_config.reasoning_models:
            if vlm_config_dump["model"].startswith(reasoning_model):
                print(f"Updating config for reasoning model: {reasoning_model}")
                vlm_config_dump["temperature"] = 1.0
                vlm_config_dump["max_completion_tokens"] = vlm_config_dump["max_tokens"]
                del vlm_config_dump["max_tokens"]
                break
        del vlm_config_dump["reasoning_models"]
        return vlm_config_dump
