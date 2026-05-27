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
from langchain_anthropic import ChatAnthropic
from pydantic import Field

# local / proprietary modules
from .base_vlm import BaseVLM, VLMConfig


class AnthropicVLMConfig(VLMConfig):
    api_key: str = Field()
    model: str = Field(default="claude-3-5-sonnet-latest")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0)

    class Config:
        env_prefix = "anthropic_"


class AnthropicVLM(BaseVLM):
    def __init__(self, vlm_config: Optional[AnthropicVLMConfig] = None):
        if vlm_config is None:
            vlm_config = AnthropicVLMConfig()
        vlm = ChatAnthropic(**vlm_config.model_dump())

        super().__init__(
            vlm=vlm,
            vlm_service="anthropic",
            model=vlm_config.model,
        )
