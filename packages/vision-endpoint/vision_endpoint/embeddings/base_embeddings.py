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
from typing import Optional

# third party modules
from openai import AsyncOpenAI, OpenAI
from pydantic import Field
from pydantic_settings import BaseSettings

# local / proprietary modules
from .exceptions import EmbeddingsException

logger = logging.getLogger()


class EmbeddingsService(str, Enum):
    openai = "openai"
    azure_openai = "azure_openai"
    mistralai = "mistralai"
    nim = "nim"
    inference_hub = "inference_hub"
    qwen = "qwen"


class EmbeddingsConfig(BaseSettings):
    api_key: str = Field()
    model: str = Field()
    base_url: str | None = Field(default=None)


class BaseEmbeddings(ABC):
    def __init__(
        self,
        embeddings_service: EmbeddingsService,
        model: str,
        client: Optional[OpenAI] = None,
        async_client: Optional[AsyncOpenAI] = None,
    ):
        self._client = client
        self._async_client = async_client
        self._embeddings_service = embeddings_service
        self._model = model

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            raise NotImplementedError("Sync client is not supported for this embeddings service")
        return self._client

    @property
    def async_client(self) -> AsyncOpenAI:
        if self._async_client is None:
            raise NotImplementedError("Async client is not supported for this embeddings service")
        return self._async_client

    @property
    def embeddings_service(self) -> EmbeddingsService:
        return self._embeddings_service

    @property
    def model(self) -> str:
        return self._model

    def embed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
        try:
            res = self.client.embeddings.create(model=self._model, input=texts, **kwargs)
            return [r.embedding for r in res.data]
        except Exception as e:
            logger.error(e, exc_info=True)
            raise EmbeddingsException(f"Error embedding documents: {str(e)}") from e

    async def aembed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
        try:
            res = await self.async_client.embeddings.create(model=self._model, input=texts, **kwargs)
            return [r.embedding for r in res.data]
        except Exception as e:
            logger.error(e, exc_info=True)
            raise EmbeddingsException(f"Error embedding documents: {str(e)}") from e

    def embed_query(self, text: str, **kwargs) -> list[float]:
        try:
            res = self.client.embeddings.create(model=self._model, input=text, **kwargs)

            return res.data[0].embedding
        except Exception as e:
            logger.error(e, exc_info=True)
            raise EmbeddingsException(f"Error embedding query: {str(e)}") from e

    async def aembed_query(self, text: str, **kwargs) -> list[float]:
        try:
            res = await self.async_client.embeddings.create(model=self._model, input=text, **kwargs)
            return res.data[0].embedding
        except Exception as e:
            logger.error(e, exc_info=True)
            raise EmbeddingsException(f"Error embedding query: {str(e)}") from e
