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


class QwenVLMConfig(VLMConfig):
    api_key: str = Field(default="not-needed")
    base_url: str = Field(default="http://localhost:8000/v1")
    model: str = Field(default="Qwen/Qwen3.5-35B-A3B-FP8")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0)
    timeout: float = Field(default=30.0)

    class Config:
        env_prefix = "qwen_"


class QwenVLM(BaseVLM):
    def __init__(self, vlm_config: Optional[QwenVLMConfig] = None):
        if vlm_config is None:
            vlm_config = QwenVLMConfig()
        vlm_config_dump = vlm_config.model_dump()
        vlm_config_dump["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        vlm = ChatOpenAI(**vlm_config_dump)

        super().__init__(
            vlm=vlm,
            vlm_service=VLMService.qwen,
            model=vlm_config.model,
        )
