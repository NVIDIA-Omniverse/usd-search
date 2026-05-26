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

from .azure_openai_embeddings import AzureOpenAIEmbeddings, AzureOpenAIEmbeddingsConfig
from .base_embeddings import EmbeddingsConfig
from .embeddings import BaseEmbeddings, EmbeddingsService, VEEmbeddings
from .inference_hub_embeddings import (
    InferenceHubEmbeddings,
    InferenceHubEmbeddingsConfig,
)
from .nim_embeddings import NimEmbeddings, NimEmbeddingsConfig
from .openai_embeddings import OpenAIEmbeddings, OpenAIEmbeddingsConfig
from .qwen_embeddings import QwenEmbeddings, QwenEmbeddingsConfig

__all__ = [
    "EmbeddingsService",
    "BaseEmbeddings",
    "EmbeddingsConfig",
    "AzureOpenAIEmbeddings",
    "OpenAIEmbeddings",
    "NimEmbeddings",
    "InferenceHubEmbeddings",
    "InferenceHubEmbeddingsConfig",
    "VEEmbeddings",
    "AzureOpenAIEmbeddingsConfig",
    "OpenAIEmbeddingsConfig",
    "NimEmbeddingsConfig",
    "QwenEmbeddings",
    "QwenEmbeddingsConfig",
]
