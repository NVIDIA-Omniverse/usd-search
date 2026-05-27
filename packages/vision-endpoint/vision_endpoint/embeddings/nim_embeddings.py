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
from openai import AsyncOpenAI, OpenAI
from pydantic import Field

# local / proprietary modules
from .base_embeddings import BaseEmbeddings, EmbeddingsConfig, EmbeddingsService


class NimEmbeddingsConfig(EmbeddingsConfig):
    api_key: str = Field()
    base_url: str = Field(default="https://integrate.api.nvidia.com/v1")
    model: str = Field(default="nvidia/nv-embedqa-e5-v5")

    class Config:
        env_prefix = "embeddings_nim_"


class NimEmbeddings(BaseEmbeddings):
    def __init__(self, embeddings_config: Optional[NimEmbeddingsConfig] = None):
        if embeddings_config is None:
            embeddings_config = NimEmbeddingsConfig()

        client = OpenAI(
            api_key=embeddings_config.api_key,
            base_url=embeddings_config.base_url,
        )
        async_client = AsyncOpenAI(
            api_key=embeddings_config.api_key,
            base_url=embeddings_config.base_url,
        )

        super().__init__(
            embeddings_service=EmbeddingsService.nim,
            model=embeddings_config.model,
            client=client,
            async_client=async_client,
        )
