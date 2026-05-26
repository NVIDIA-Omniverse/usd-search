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
import logging
from abc import ABC
from enum import Enum
from typing import Any

# third party modules
from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# local / proprietary modules
from .exceptions import VLMException

logger = logging.getLogger()


class VLMService(str, Enum):
    openai = "openai"
    anthropic = "anthropic"
    azure_openai = "azure_openai"
    mistralai = "mistralai"
    nim = "nim"
    google = "google"
    qwen = "qwen"
    qwen_alibaba = "qwen_alibaba"
    inference_hub = "inference_hub"


class VLMConfig(BaseSettings):
    api_key: str = Field()
    max_retries: int = Field(
        default=0,
        description="Max retries for the underlying LLM client on transient errors (e.g. 429, 500). "
        "Set to 0 to fail fast (recommended for async validation where retries are handled at a higher level).",
    )


class BaseVLM(ABC):
    def __init__(self, vlm: BaseChatModel, vlm_service: VLMService, model: str):
        self._base_vlm = vlm  # Store original model for re-use
        self._vlm = vlm
        self._vlm_service = vlm_service
        self._model = model

    @property
    def vlm(self) -> BaseChatModel:
        return self._vlm

    @property
    def vlm_service(self) -> VLMService:
        return self._vlm_service

    @property
    def model(self) -> str:
        return self._model

    def with_structured_output(self, base_model: BaseModel) -> None:
        """Configure structured output using the original model to allow multiple calls."""
        self._vlm = self._base_vlm.with_structured_output(schema=base_model)

    def image_to_messages(self, base64_images: list[str], prompt: str, system_prompt: str) -> list[dict]:
        """
        Create a message list from the base64 images and the image prompt.
        In the case of base64 images = None, only the image prompt is added to user content.

        Args:
            base64_images (list[str]): List of base64 images
            prompt (str): Image prompt
        """

        text_message = {"type": "text", "text": prompt}
        user_content = [text_message]

        if base64_images is not None:
            image_messages: list[dict] = []
            for base64_image in base64_images:
                image_messages.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}",
                            "detail": "high",
                        },
                    }
                )
            user_content.extend(image_messages)

        messages = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": user_content})

        return messages

    def invoke(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs) -> Any:
        try:
            return self._vlm.invoke(
                input=self.image_to_messages(base64_images, prompt, system_prompt),
                **kwargs,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            raise VLMException(f"Vision Model Exception: {str(e)}") from e

    async def ainvoke(self, prompt: str, system_prompt: str, base64_images: list[str] = None, **kwargs) -> Any:
        try:
            return await self._vlm.ainvoke(
                input=self.image_to_messages(base64_images, prompt, system_prompt),
                **kwargs,
            )
        except Exception as e:
            logger.error(e, exc_info=True)
            raise VLMException(f"Vision Model Exception: {str(e)}") from e
