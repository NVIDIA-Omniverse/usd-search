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
from openai import AsyncAzureOpenAI, AzureOpenAI
from pydantic import Field

# local / proprietary modules
from .base_embeddings import BaseEmbeddings, EmbeddingsConfig, EmbeddingsService


class AzureOpenAIEmbeddingsConfig(EmbeddingsConfig):
    """
    https://confluence.nvidia.com/pages/viewpage.action?spaceKey=PERFLABGRP&title=Perflab+OneAPI
    """

    api_key: str = Field()
    model: str = Field(default="text-embedding-3-large")
    api_version: str = Field(default="2025-03-01-preview")
    azure_endpoint: str = Field(default="https://llm-proxy.perflab.nvidia.com")

    class Config:
        env_prefix = "embeddings_azure_openai_"


class AzureOpenAIEmbeddings(BaseEmbeddings):
    def __init__(self, embeddings_config: Optional[AzureOpenAIEmbeddingsConfig] = None):
        if embeddings_config is None:
            embeddings_config = AzureOpenAIEmbeddingsConfig()

        client = AzureOpenAI(
            api_key=embeddings_config.api_key,
            api_version=embeddings_config.api_version,
            azure_endpoint=embeddings_config.azure_endpoint,
        )
        async_client = AsyncAzureOpenAI(
            api_key=embeddings_config.api_key,
            api_version=embeddings_config.api_version,
            azure_endpoint=embeddings_config.azure_endpoint,
        )

        super().__init__(
            embeddings_service=EmbeddingsService.azure_openai,
            model=embeddings_config.model,
            client=client,
            async_client=async_client,
        )
