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
from langchain_core.embeddings import Embeddings

# local / proprietary modules
from .base_embeddings import BaseEmbeddings, EmbeddingsConfig, EmbeddingsService


class VEEmbeddings(Embeddings):
    """
    VEEmbeddings is a class that embeds text using a specified embeddings service.
    """

    def __init__(
        self,
        embeddings_service: EmbeddingsService,
        embeddings_config: Optional[EmbeddingsConfig] = None,
        **kwargs,
    ):
        self._embeddings_config: Optional[EmbeddingsConfig] = embeddings_config
        self._embeddings_service: EmbeddingsService = embeddings_service
        self._embeddings: Optional[BaseEmbeddings] = None
        self._extra_body: dict[str, Any] = {}

        if embeddings_service == EmbeddingsService.openai:
            from .openai_embeddings import OpenAIEmbeddings, OpenAIEmbeddingsConfig

            if embeddings_config is None:
                embeddings_config = OpenAIEmbeddingsConfig(**kwargs)

            self._embeddings = OpenAIEmbeddings(embeddings_config)
        elif embeddings_service == EmbeddingsService.azure_openai:
            from .azure_openai_embeddings import (
                AzureOpenAIEmbeddings,
                AzureOpenAIEmbeddingsConfig,
            )

            if embeddings_config is None:
                embeddings_config = AzureOpenAIEmbeddingsConfig(**kwargs)

            self._embeddings = AzureOpenAIEmbeddings(embeddings_config)
        elif embeddings_service == EmbeddingsService.nim:
            from .nim_embeddings import NimEmbeddings, NimEmbeddingsConfig

            if embeddings_config is None:
                embeddings_config = NimEmbeddingsConfig(**kwargs)

            self._embeddings = NimEmbeddings(embeddings_config)
            self._extra_body = {"extra_body": {"input_type": "passage", "truncate": "NONE"}}
        elif embeddings_service == EmbeddingsService.inference_hub:
            from .inference_hub_embeddings import (
                InferenceHubEmbeddings,
                InferenceHubEmbeddingsConfig,
            )

            if embeddings_config is None:
                embeddings_config = InferenceHubEmbeddingsConfig()

            self._embeddings = InferenceHubEmbeddings(embeddings_config)
        elif embeddings_service == EmbeddingsService.qwen:
            from .qwen_embeddings import QwenEmbeddings, QwenEmbeddingsConfig

            if embeddings_config is None:
                embeddings_config = QwenEmbeddingsConfig(**kwargs)

            self._embeddings = QwenEmbeddings(embeddings_config)
        else:
            raise ValueError(f"Invalid embeddings service: {embeddings_service}")

    @property
    def embeddings(self) -> BaseEmbeddings:
        if self._embeddings is None:
            raise ValueError("Embeddings not initialized")
        return self._embeddings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embeddings.embed_documents(texts, **self._extra_body)

    def embed_query(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text, **self._extra_body)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self.embeddings.aembed_documents(texts, **self._extra_body)

    async def aembed_query(self, text: str) -> list[float]:
        return await self.embeddings.aembed_query(text, **self._extra_body)
