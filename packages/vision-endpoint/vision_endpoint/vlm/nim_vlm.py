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

UNSUPPORTED_SYSTEM_PROMPT_MODELS = [
    "meta/llama-3.2-90b-vision-instruct",
]


class NimVLMConfig(VLMConfig):
    api_key: str = Field()
    base_url: str = Field(default="https://integrate.api.nvidia.com/v1")
    model: str = Field(default="meta/llama-4-maverick-17b-128e-instruct")
    temperature: float = Field(default=0.0)
    max_tokens: int | None = Field(default=None)

    class Config:
        env_prefix = "nim_"


class NimVLM(BaseVLM):
    def __init__(self, vlm_config: Optional[NimVLMConfig] = None):
        if vlm_config is None:
            vlm_config = NimVLMConfig()
        vlm = ChatOpenAI(**vlm_config.model_dump())

        super().__init__(vlm=vlm, vlm_service=VLMService.nim, model=vlm_config.model)

    def invoke(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs):
        if self.model in UNSUPPORTED_SYSTEM_PROMPT_MODELS:
            system_prompt = None

        return super().invoke(base64_images=base64_images, prompt=prompt, system_prompt=system_prompt, **kwargs)

    async def invoke_async(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs):
        if self.model in UNSUPPORTED_SYSTEM_PROMPT_MODELS:
            system_prompt = None

        return await super().invoke_async(
            base64_images=base64_images, prompt=prompt, system_prompt=system_prompt, **kwargs
        )
