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
import hashlib
import os
from typing import Any, Callable, Dict, Optional, TypedDict, Union

# third party modules
from opensearchpy import AsyncOpenSearch, OpenSearch, helpers
from pydantic_settings.main import BaseSettings, SettingsConfigDict
from typing_extensions import NotRequired

# local / proprietary modules
from search_utils import observability_utils
from search_utils.cache_utils.elasticsearch import (
    EmbedOSCacheDict,
    NestedMetaCacheDict,
    OSCacheDict,
)
from search_utils.misc_utils import (
    compress_data,
    decompress_data,
    normalize_embedding,
    str2bool,
)

from .config import IndexConfig, SupportedStorageFields

BINARY_DATA = str2bool(os.getenv("EMBEDDING_BINARY_DATA", "True"))


class OSBackendSettings(BaseSettings):
    retry_on_conflict: int = 5

    model_config = SettingsConfigDict(env_prefix="os_backend_settings_")


class StorageFieldConfig(TypedDict):
    encoder: NotRequired[Callable[[Any], Union[str, bytes]]]
    decoder: NotRequired[Callable[[Union[str, bytes]], Any]]


class EncoderDecoderCollection(TypedDict):
    embedding: Callable[[Any], Any]
    image: Callable[[Any], Any]
    pointcloud: Callable[[Any], Any]


class NestedMetaOSCacheDict(NestedMetaCacheDict, OSCacheDict):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        name: str = "nested-metadata",
        binary_data: bool = BINARY_DATA,
        version: str = "5.0",
        number_of_shards: int = int(os.getenv("NUMBER_OF_SHARDS", "20")),
        es_observability: observability_utils.SearchBackendObservability = observability_utils.SearchBackendObservability(),
        os_backend_settings: OSBackendSettings = OSBackendSettings(),
        index_config: Optional[IndexConfig] = None,
        **kwargs,
    ):
        if index_config is None:
            index_config = IndexConfig()

        self._index_config = index_config

        self.helpers = helpers
        # prepare index name
        self.name = index_config.embedding_field_name
        self.dim = self._index_config.embedding_field_dim

        self.version = version
        self._os_backend_settings = os_backend_settings
        # update name
        self.storage_index_name = f"{name}-ver4.0"
        # self.index_name = f"{name}{'' if version is None else f'-ver{version}'}" #TODO
        self.index_name = self.get_index_name(name, version)
        self.binary_data = binary_data
        # prepare nested properties
        self.properties = {}
        # define encoder for different data modalities
        self.encoder = EncoderDecoderCollection(
            embedding=self.none_wrapper(normalize_embedding),
            image=self.none_wrapper(lambda x: hashlib.sha256(str(x).encode()).hexdigest()),
            pointcloud=self.none_wrapper(lambda x: hashlib.sha256(str(x).encode()).hexdigest()),
        )
        # define decoder for different data modalities
        self.decoder = EncoderDecoderCollection(embedding=lambda x: x, image=lambda x: x, pointcloud=lambda x: x)
        #  > setting up embedding property

        if not binary_data:
            raise NotImplementedError("Only binary data is supported")
        # TODO: Validate if knn engine parameters are meeting our requirements
        self.properties["embedding"] = {
            "type": "knn_vector",
            "dimension": self.dim,
            "method": {
                "name": "hnsw",
                "space_type": "innerproduct",
                "engine": "faiss",
                "parameters": {"ef_construction": 2048, "ef_search": 2048, "m": 64},
            },
        }
        settings = {"index": {"number_of_shards": number_of_shards, "knn": True}}

        if float(version) >= 4.0:
            settings.update(
                {
                    "analysis": {
                        "analyzer": {
                            "custom_path_tree": {"tokenizer": "custom_hierarchy"},
                            "custom_path_tree_reversed": {"tokenizer": "custom_hierarchy_reversed"},
                        },
                        "tokenizer": {
                            "custom_hierarchy": {
                                "type": "path_hierarchy",
                                "delimiter": "/",
                            },
                            "custom_hierarchy_reversed": {
                                "type": "path_hierarchy",
                                "delimiter": "/",
                                "reverse": "true",
                            },
                        },
                    }
                }
            )

        #  > setting up label property
        self.properties["label"] = {"type": "text"}
        # add possibility to add keywords per view
        self.properties["keyword"] = {"type": "keyword"}

        self.storage_fields: Dict[str, Dict[str, Optional[Callable]]] = {}
        for sf in self._index_config.supported_storage_fields:
            if sf == SupportedStorageFields.image:
                self.properties[sf.value] = {"type": "keyword"}
                self.storage_fields[sf.value] = {}
            elif sf == SupportedStorageFields.pointcloud:
                self.properties[sf.value] = {"type": "keyword"}
                self.storage_fields[sf.value] = {
                    "encoder": self.none_wrapper(compress_data),
                    "decoder": self.none_wrapper(decompress_data),
                }
            else:
                raise ValueError(f"Unsupported storage field: {sf}")

        # defining storage fields
        self.storage = {
            sf: EmbedOSCacheDict(
                host=host,
                port=port,
                index_name=f"{self.storage_index_name}-{sf}",
                name=f"siglip2-embedding-ver3.0-{sf}",
                es_type="object",
                es_dims=None,
                encoder=val.get("encoder", None),
                decoder=val.get("decoder", None),
                number_of_shards=number_of_shards,
                main_index_kwargs={"enabled": False},
                es_observability=es_observability,
            )
            for sf, val in self.storage_fields.items()
        }

        # prepare metadata
        self.meta_data = {
            # added fields
            "base_key": {"type": "keyword"},
            "tag": {"type": "keyword"},
            "text": {"type": "text"},
            # nucleus fields
            "path": {"type": "keyword"},
            "name": {
                "type": "keyword",
                "fields": {
                    "standard": {"type": "text", "analyzer": "standard"},
                    "simple": {"type": "text", "analyzer": "simple"},
                },
            },
            "ext": {"type": "keyword"},
            "pathType": {"type": "keyword"},
            "created_by": {"type": "keyword"},
            "created_timestamp": {"type": "date"},
            "modified_by": {"type": "keyword"},
            "modified_timestamp": {"type": "date"},
            "empty": {"type": "boolean"},
            "etag": {"type": "keyword"},
            "hash_type": {"type": "keyword"},
            "hash_value": {"type": "keyword"},
            "hash_block_size": {"type": "long"},
            "on_mount": {"type": "boolean"},
            "size": {"type": "long"},
            "status": {"type": "keyword"},
            "statusDescription": {"type": "text"},
        }
        # update path variable
        if float(version) >= 4.0:
            self.meta_data["path"] = {
                "type": "keyword",
                "fields": {
                    "tree": {"type": "text", "analyzer": "custom_path_tree"},
                    "tree_reversed": {
                        "type": "text",
                        "analyzer": "custom_path_tree_reversed",
                    },
                },
            }
            self.meta_data.update(
                {
                    "is_deleted": {"type": "boolean"},
                    "deleted_by": {"type": "keyword"},
                    "deleted_timestamp": {"type": "date"},
                }
            )

        # tags
        self.tags_meta_data = {
            "tags": {
                "type": "nested",
                "include_in_root": True,
                "properties": {
                    "tag": {"type": "keyword"},
                    "namespace": {"type": "keyword"},
                    "value": {"type": "keyword"},
                },
            }
        }

        # USD properties
        # - fix for the case when date value is passed
        self.usd_properties_meta_data = {
            "usd_properties": {
                "type": "nested",
                "properties": {
                    "name": {"type": "keyword"},
                    "name_sayt": {
                        "type": "search_as_you_type",
                        "doc_values": False,
                        "max_shingle_size": 3,
                    },
                    "value": {"type": "keyword"},
                    "value_sayt": {
                        "type": "search_as_you_type",
                        "doc_values": False,
                        "max_shingle_size": 3,
                    },
                },
            }
        }

        # prepare index fields
        index_fields = {
            self.name: {"type": "nested", "properties": {**self.properties}},
            **self.meta_data,
            **self.tags_meta_data,
            **self.usd_properties_meta_data,
        }

        super().__init__(
            host=host,
            port=port,
            index_name=self.index_name,
            index_fields=index_fields,
            settings=settings,
            exist_ok=True,
            es_observability=es_observability,
        )

    @staticmethod
    def get_index_name(name: str, version: str = "5.0") -> str:
        return f"{name}{'' if version is None else f'-ver{version}'}"

    def update_meta(self, key: str, meta: dict) -> None:
        key_hashed = self.get_hash(key)
        es: OpenSearch
        with self.context() as es:
            if es.exists(index=self.index_name, id=key_hashed):
                es.update(
                    index=self.index_name,
                    id=key_hashed,
                    body={"doc": meta},
                    params=dict(retry_on_conflict=self._os_backend_settings.retry_on_conflict),
                )
            else:
                self.__setitem__(key, {}, meta)

    async def async_update_meta(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        meta: Optional[dict] = None,
    ) -> None:
        if meta is None:
            meta = {}
        es: AsyncOpenSearch
        async with self.async_context() as es:
            _key = key_hash or self.get_hash(key)
            if await es.exists(index=self.index_name, id=_key):
                await es.update(
                    index=self.index_name,
                    id=_key,
                    body={"doc": meta},
                    params=dict(retry_on_conflict=self._os_backend_settings.retry_on_conflict),
                )
            else:
                await self.async_setitem(key=key, key_hash=key_hash, values={}, meta=meta)

    def postprocess_search_results(self, r: dict, return_dict: bool = False, only_key: bool = False) -> dict:
        """Postprocess search results coming from ES engine.

        Args:
            r (dict): raw content dictionary
            return_dict (bool, optional): if True - return all the sample content. Defaults to ``False``.

        Returns:
            processed file content
        """
        # post-process the results and return either dictionary or tuple of processed data
        if only_key:
            return {
                "path": r["_source"]["base_key"],
                "score": r["_score"],
                "_source": r["_source"],
            }

        # check if inner hit is available and if yes - return it
        if (
            r.get("inner_hits", {}).get(self.name, None) is not None
            and len(r["inner_hits"][self.name]["hits"]["hits"]) > 0
        ):
            inner_hit = r["inner_hits"][self.name]["hits"]["hits"][0]
        elif r.get("inner_hits", {}).get("filter") is not None and len(r["inner_hits"]["filter"]["hits"]["hits"]) > 0:
            inner_hit = r["inner_hits"]["filter"]["hits"]["hits"][0]
        else:
            inner_hit = {"_source": {}, "_score": r["_score"]}

        if return_dict:
            content = {}
            for k, v in inner_hit["_source"].items():
                if k in self.properties:
                    content[k] = self.decoder.get(k, lambda x: x)(v)

            return {
                "path": r["_source"]["base_key"],
                "embedding": content.get("embedding"),
                "content": content,
                "score": inner_hit["_score"],
                "_source": r["_source"],
            }
        else:
            return (
                r["_source"]["base_key"],
                self.decoder.get("embedding", lambda x: x)(inner_hit.get("_source", {}).get("embedding")),
                r["_source"]["base_key"],
            )
