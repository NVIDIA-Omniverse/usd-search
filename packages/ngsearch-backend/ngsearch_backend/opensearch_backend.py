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

from typing import Optional

from ngsearch_backend.data import SearchConfigParams
from ngsearch_backend.elasticsearch_backend import ElasticSearchBackend

from search_utils.cache_utils.elasticsearch import NestedMetaCacheDict
from search_utils.cache_utils.opensearch import NestedMetaOSCacheDict
from search_utils.observability_utils import SearchBackendObservability


class OpenSearchBackend(ElasticSearchBackend):
    def get_search_cache(
        self,
        host: str,
        port: int,
        index_name: str,
        dim: int,
        es_observability: SearchBackendObservability,
    ) -> NestedMetaCacheDict:
        return NestedMetaOSCacheDict(
            host=host,
            port=port,
            name=index_name,
            dim=dim,
            es_observability=es_observability,
        )

    def get_source_filter(
        self,
        noembeddings: bool = True,
        noimages: bool = True,
        only_key: bool = False,
        searchable_items_subset: Optional[list[str]] = None,
    ):
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
                searchable_items_subset=searchable_items_subset,
            )
        source_filter = ["base_key"] + source_filter
        if not noembeddings:
            source_filter.append(f"{self.search_cache.name}.embedding")
        if not noimages:
            source_filter.append(f"{self.search_cache.name}.image")

        return SearchConfigParams(
            source_filter=source_filter,
            return_dict=True,
            return_all=True,
            searchable_items_subset=searchable_items_subset,
        )
