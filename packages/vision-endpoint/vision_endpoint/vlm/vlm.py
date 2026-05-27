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
from typing import Any, Optional

# third party modules
from pydantic import BaseModel

# local / proprietary modules
from .base_vlm import BaseVLM, VLMConfig, VLMService


class VLM:

    def __init__(
        self,
        vlm_service: VLMService,
        vlm_config: Optional[VLMConfig] = None,
        **kwargs,
    ):
        self._vlm_service: VLMService = vlm_service
        self._vlm_config: VLMConfig = vlm_config
        self._vlm: BaseVLM = None

        if vlm_service == VLMService.openai:
            from .openai_vlm import OpenAIVLM, OpenAIVLMConfig

            if vlm_config is None:
                vlm_config = OpenAIVLMConfig(**kwargs)

            self._vlm = OpenAIVLM(vlm_config)
        elif vlm_service == VLMService.anthropic:
            from .anthropic_vlm import AnthropicVLM, AnthropicVLMConfig

            if vlm_config is None:
                vlm_config = AnthropicVLMConfig(**kwargs)

            self._vlm = AnthropicVLM(vlm_config)
        elif vlm_service == VLMService.azure_openai:
            from .azure_openai_vlm import AzureOpenAIVLM, AzureOpenAIVLMConfig

            if vlm_config is None:
                vlm_config = AzureOpenAIVLMConfig(**kwargs)

            self._vlm = AzureOpenAIVLM(vlm_config)
        elif vlm_service == VLMService.mistralai:
            from .mistralai_vlm import MistralAIVLM, MistralAIVLMConfig

            if vlm_config is None:
                vlm_config = MistralAIVLMConfig(**kwargs)

            self._vlm = MistralAIVLM(vlm_config)
        elif vlm_service == VLMService.nim:
            from .nim_vlm import NimVLM, NimVLMConfig

            if vlm_config is None:
                vlm_config = NimVLMConfig(**kwargs)

            self._vlm = NimVLM(vlm_config)
        elif vlm_service == VLMService.google:
            from .google_vlm import GoogleVLM, GoogleVLMConfig

            if vlm_config is None:
                vlm_config = GoogleVLMConfig(**kwargs)

            self._vlm = GoogleVLM(vlm_config)
        elif vlm_service == VLMService.qwen:
            from .qwen_vlm import QwenVLM, QwenVLMConfig

            if vlm_config is None:
                vlm_config = QwenVLMConfig(**kwargs)

            self._vlm = QwenVLM(vlm_config)
        elif vlm_service == VLMService.qwen_alibaba:
            from .qwen_alibaba_vlm import QwenAlibabaVLM, QwenAlibabaVLMConfig

            if vlm_config is None:
                vlm_config = QwenAlibabaVLMConfig(**kwargs)

            self._vlm = QwenAlibabaVLM(vlm_config)
        else:
            raise ValueError(f"Invalid VLM Type: {vlm_service}")

    def with_structured_output(self, base_model: BaseModel) -> None:
        """Configure the VLM to use structured output with the given Pydantic model."""
        self._vlm.with_structured_output(base_model)

    def invoke(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs) -> Any:
        return self._vlm.invoke(prompt, system_prompt, base64_images, **kwargs)

    async def ainvoke(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs) -> Any:
        return await self._vlm.ainvoke(prompt, system_prompt, base64_images, **kwargs)
