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

import os
from enum import Enum
from typing import AsyncGenerator, Dict, List

import numpy as np
from ngsearch_backend.backend import EmbedBackend
from ngsearch_backend.data import ProcessedQuery, SearchConfigParams
from numpy.typing import NDArray
from siglip2_triton_client.client import (
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
)

from search_utils.cache_utils.elasticsearch import (
    NestedMetaCacheDict,
    NestedMetaESCacheDict,
)
from search_utils.observability_utils import SearchBackendObservability


class BackendResponseStatus(str, Enum):
    preview_missing = "preview_missing"


class ElasticSearchBackend(EmbedBackend):
    def __init__(
        self,
        es_observability: SearchBackendObservability,
        index_name: str = os.getenv("ES_NAME", "siglip2-embedding"),
        host: str = os.getenv("ES_HOST", "localhost"),
        port: int = os.getenv("ES_PORT", "9200"),
        dim: int = int(os.getenv("ES_DIM", "1536")),
        **kwargs,
    ) -> None:
        # initialize embedding cache
        self.search_cache = self.get_search_cache(host, port, index_name, dim, es_observability)
        self.counter = 0

    def get_search_cache(
        self,
        host: str,
        port: int,
        index_name: str,
        dim: int,
        es_observability: SearchBackendObservability,
    ) -> NestedMetaCacheDict:
        return NestedMetaESCacheDict(
            host=host,
            port=port,
            name=index_name,
            dim=dim,
            es_observability=es_observability,
        )

    def process_search_item(self, item: dict, only_key: bool = False) -> ProcessedQuery:
        """Convert dictionary returned from ES engine to a tuple of required values."""

        if only_key:
            return dict(path=item["path"], score=item["score"], source=item["_source"])

        return dict(
            path=item["path"],
            score=item["score"],
            image_key=item["content"].get("image"),
            embedding=item["embedding"],
            source=item["_source"],
        )

    async def search_async(
        self, query_feats: NDArray[np.float32], N: int, **kwargs
    ) -> AsyncGenerator[List[ProcessedQuery], None]:
        """Run asynchronous search query."""
        if query_feats is not None:
            query_feats = query_feats.reshape((-1,))
            query_feats = query_feats / np.linalg.norm(query_feats)

        async for item in self.search_cache.search_async(query_feats, N, return_dict=True, return_all=True, **kwargs):
            yield [self.process_search_item(it) for it in item]

    async def search_streaming_async(
        self,
        query_feats: NDArray[np.float32],
        N: int,
        search_config: SearchConfigParams,
        **kwargs,
    ) -> AsyncGenerator[List[ProcessedQuery], None]:
        """Run streaming asynchronous search query."""
        if query_feats is not None:
            query_feats = query_feats.reshape((-1,))
            query_feats = query_feats / np.linalg.norm(query_feats)

        async for item in self.search_cache.search_streaming_async(
            query_feats,
            size=N,
            return_dict=search_config.return_dict,
            return_all=search_config.return_all,
            source_filter=search_config.source_filter,
            only_key=search_config.only_key,
            searchable_items_subset=search_config.searchable_items_subset,
            **kwargs,
        ):
            yield [self.process_search_item(it, search_config.only_key) for it in item]

    def get_source_filter(
        self, noembeddings: bool = True, noimages: bool = True, only_key: bool = False
    ) -> SearchConfigParams:
        """Prepare source filter to return only relevant data

        Args:
            noembeddings (bool, optional): if True - do not return embeddings. Defaults to ``True``.
            noimages (bool, optional): if True - do not return images. Defaults to ``True``.

        Returns:
            source filter that is applied to ES query
        """

        source_filter = ["vision_generated_*"] + list(self.search_cache.meta_data.keys())

        if only_key:
            return SearchConfigParams(
                only_key=True,
                return_dict=False,
                return_all=True,
                source_filter=source_filter,
            )
        source_filter = {"includes": ["base_key"] + source_filter}
        if not noembeddings:
            source_filter["includes"].append(f"{self.search_cache.name}.embedding")
        if not noimages:
            source_filter["includes"].append(f"{self.search_cache.name}.image")

        return SearchConfigParams(source_filter=source_filter, return_dict=True, return_all=True)

    async def async_get_image(self, key: str) -> str:
        try:
            return await self.search_cache.storage["image"].async_getitem(key_hash=key)
        except KeyError:
            return BackendResponseStatus.preview_missing

    @staticmethod
    async def get_pred(
        embed: np.array,
        embedding_client: TritonEnsembleImageClient | TritonEnsembleTextClient,
    ) -> List[Dict[str, str]]:
        response = await embedding_client.predict(embed)
        return response

    def __len__(self, embeddings: bool = True):
        # Instead of listing complete es_cache, which may content items without embeddings
        # > list only the
        if embeddings:
            return len(self.search_cache.storage["image"])
        else:
            return len(self.search_cache)

    def keys(self):
        for k in self.search_cache.keys():
            yield k

    def list_keywords(self, **kwargs):
        return self.search_cache.list_keywords(**kwargs)

    async def async_list_keywords(self, **kwargs):
        return await self.search_cache.async_list_keywords(**kwargs)
