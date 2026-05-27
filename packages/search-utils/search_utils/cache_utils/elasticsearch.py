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

import asyncio
import hashlib
import json

# standard imports
import logging
import os
import time
from abc import abstractmethod
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Dict, List, Optional, Union

# third party modules
import xxhash
from elasticsearch import NotFoundError
from opensearchpy import NotFoundError as OSNotFoundError

# local / proprietary modules
import search_utils.opensearch_utils
from search_utils import elastic_utils as eu
from search_utils import observability_utils
from search_utils.cache_utils.config import SupportedStorageFields

# TODO (arozantsev): this is not great, but I use it here for backwards compatibility
from search_utils.log_utils import prepare_message
from search_utils.misc_utils import (
    DL_to_LD,
    LD_to_DL,
    array_to_base64,
    base64_to_list,
    compress_data,
    decompress_data,
    get_percentage_string,
    merge_dicts,
    normalize_embedding,
    str2bool,
)

from . import cache_utils_logger
from .config import IndexConfig

DEBUG_LOGGING = cache_utils_logger.isEnabledFor(logging.DEBUG)

BINARY_DATA = str2bool(os.getenv("EMBEDDING_BINARY_DATA", "True"))

MAX_CHUNK_BYTES = int(os.getenv("MAX_CHUNK_BYTES", 100 * 1024 * 1024))


class ReIndexingError(Exception):
    pass


class SearchCacheDict:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        index_name: str = "cache",
        index_fields: dict = {},
        analysis: dict = {},
        settings: dict = {},
        exist_ok: bool = False,
        es_observability: observability_utils.SearchBackendObservability = observability_utils.SearchBackendObservability(),
    ):
        self.index_name = index_name
        # initialize elastic backend
        self.search_backend = self.get_search_backend(host, port, es_observability)
        # create index to store data
        self.create_index(index_fields, analysis, settings, exist_ok)

    async def close(self):
        await self.search_backend.close()

    @staticmethod
    def get_hash(value: str) -> str:
        return xxhash.xxh128(value).hexdigest()

    @abstractmethod
    def get_search_backend(
        self, host, port, es_observability
    ) -> Union[eu.ESBackend, search_utils.opensearch_utils.OSBackend]: ...

    @abstractmethod
    def create_index(self, index_fields, analysis, settings, exist_ok): ...

    @contextmanager
    def context(self, *args, **kwargs):
        yield self.search_backend.es

    @asynccontextmanager
    async def async_context(self, *args, **kwargs):
        async with self.search_backend.async_context(*args, **kwargs) as es:
            yield es

    def __getitem__(self, key: Optional[str] = None, key_hash: Optional[str] = None, **kwargs) -> dict:
        key = key_hash or self.get_hash(key)
        try:
            return self.search_backend.get_item(self.index_name, key, **kwargs)
        except (NotFoundError, OSNotFoundError):
            raise KeyError(f"'{key}' not found in ES index")

    async def async_getitem(self, key: Optional[str] = None, key_hash: Optional[str] = None, **kwargs) -> dict:
        key = key_hash or self.get_hash(key)
        try:
            return await self.search_backend.async_get_item(self.index_name, key, **kwargs)
        except (NotFoundError, OSNotFoundError):
            raise KeyError(f"'{key}' not found in ES index")

    def __setitem__(self, key, content: dict):
        key = self.get_hash(key)
        self.search_backend.add_item(self.index_name, key, content)

    async def async_setitem(
        self,
        key: Optional[str] = None,
        content: Optional[Dict] = None,
        key_hash: Optional[str] = None,
        **kwargs,
    ):
        if content is None:
            content = {}
        key = key_hash or self.get_hash(key)
        await self.search_backend.add_item_async(self.index_name, key, content, **kwargs)

    def update(
        self,
        dictionary: Optional[dict] = None,
        dictionary_hashed_keys: Optional[dict] = None,
    ):
        dictionary = dictionary_hashed_keys or {self.get_hash(k): v for k, v in dictionary.items()}
        self.search_backend.update(self.index_name, dictionary)

    async def async_update(
        self,
        dictionary: Optional[dict] = None,
        dictionary_hashed_keys: Optional[dict] = None,
        context=None,
    ):
        dictionary = dictionary_hashed_keys or {self.get_hash(k): v for k, v in dictionary.items()}
        await self.search_backend.update_async(self.index_name, dictionary, context=context)

    def __delitem__(self, key):
        key = self.get_hash(key)
        self.search_backend.remove_item(self.index_name, key)

    async def async_delitem(self, key: Optional[str] = None, key_hash: Optional[str] = None, **kwargs):
        key = key_hash or self.get_hash(key)
        await self.search_backend.remove_item_async(self.index_name, key, **kwargs)

    def keys(self, max_requests: int = 5000):
        return self.search_backend.get_all_keys(self.index_name, max_requests=max_requests)

    async def async_keys(self, max_requests: int = 5000):
        return await self.search_backend.get_all_keys_async(self.index_name, max_requests=max_requests)

    async def async_keys_iter(self, max_requests: int = 5000, batch_mode: bool = False):
        res = []
        async for k in self.search_backend.get_all_keys_iter_async(self.index_name, max_requests=max_requests):
            if batch_mode:
                res.append(k)
                if len(res) >= max_requests:
                    yield res
                    res = []
            else:
                yield k

        if len(res) > 0:
            yield res

    def exists(self, key: Optional[List[str]] = None, key_hash: Optional[List[str]] = None) -> List[bool]:
        if not isinstance(key, list):
            key = [key]
        key = key_hash or [self.get_hash(k) for k in key]
        return [self.search_backend.es.exists(index=self.index_name, id=k) for k in key]

    async def exists_async(
        self,
        key: Optional[Union[str, List[str]]] = None,
        key_hash: Optional[List[str]] = None,
        batch_size: int = 5,
    ) -> List[bool]:
        if not isinstance(key, list):
            key = [key]

        key = key_hash or [self.get_hash(k) for k in key]

        res = []
        for ind in range(0, len(key), batch_size):
            es: eu.AsyncElasticsearch
            async with self.async_context() as es:
                res.extend(
                    await asyncio.gather(*[es.exists(index=self.index_name, id=k) for k in key[ind : ind + batch_size]])
                )

        return res

    def __len__(self):
        return int(self.search_backend.es.cat.count(index=self.index_name).strip().split(" ")[-1])

    def items(self, single_query: bool = False):
        for k, v in self.search_backend.get_all_items(self.index_name, single_query=single_query):
            yield (k, v)

    def get(self, item: Any, default: Any = None) -> Any:
        try:
            return self.__getitem__(item)
        except KeyError:
            return default

    async def async_get(self, item: Any, default: Any = None) -> Any:
        try:
            return await self.async_getitem(item)
        except KeyError:
            return default


class ESCacheDict(SearchCacheDict):
    def get_search_backend(self, host, port, es_observability) -> eu.ESBackend:
        return eu.ESBackend(host=host, port=port, es_observability=es_observability)

    def create_index(self, index_fields, analysis, settings, exist_ok):
        self.search_backend.create_index(
            self.index_name,
            index_fields=index_fields,
            analysis=analysis,
            settings=settings,
            exist_ok=exist_ok,
        )


class OSCacheDict(SearchCacheDict):
    def get_search_backend(self, host, port, es_observability) -> search_utils.opensearch_utils.OSBackend:
        from search_utils.opensearch_utils import OpenSearchIndexSettings, OSBackend

        return OSBackend(
            host=host,
            port=port,
            es_observability=es_observability,
            index_settings=OpenSearchIndexSettings(),
        )

    def create_index(self, index_fields, analysis, settings, exist_ok):
        self.search_backend.create_index(
            self.index_name,
            index_fields=index_fields,
            analysis=analysis,
            settings=settings,
            exist_ok=exist_ok,
        )


class EmbedCacheDict:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        index_name: str = "siglip2-embedding",
        name: str = "siglip2-embedding",
        version: str = None,
        es_dims: int = 512,
        es_type: str = "dense_vector",
        meta_data: dict = {},
        binary_data: bool = False,
        analysis: dict = {},
        encoder: callable = None,
        decoder: callable = None,
        main_index_kwargs: dict = {},
        number_of_shards: int = int(os.getenv("NUMBER_OF_SHARDS", "20")),
        es_observability: observability_utils.SearchBackendObservability = observability_utils.SearchBackendObservability(),
    ):
        self.index_name = f"{index_name}{'' if version is None else version}-cache"
        self.name = name
        self._fallback_name = index_name
        self.es_type = es_type
        self.binary_data = binary_data
        if binary_data:
            index_fields = {
                self.name: {"type": "binary", "doc_values": True},
                **meta_data,
            }
        else:
            index_fields = {
                self.name: {"type": self.es_type, **main_index_kwargs},
                **meta_data,
            }
            if es_dims is not None:
                index_fields[self.name]["dims"] = es_dims

        self.encoder = encoder
        self.decoder = decoder

        super().__init__(
            host,
            port,
            index_name=self.index_name,
            index_fields=index_fields,
            analysis=analysis,
            settings={"index": {"number_of_shards": number_of_shards}},
            exist_ok=True,
            es_observability=es_observability,
        )

    def encode_data(self, value):
        if self.binary_data:
            value = array_to_base64(value)
        elif self.encoder is not None:
            value = self.encoder(value)
        return value

    def decode_data(self, value):
        if self.binary_data:
            value = base64_to_list(value)
        elif self.decoder is not None:
            value = self.decoder(value)
        return value

    def __setitem__(self, key, value, meta: dict = {}):
        super().__setitem__(key, {self.name: self.encode_data(value), **meta})

    async def async_setitem(self, key, value, meta: dict = {}, **kwargs):
        await super().async_setitem(key, {self.name: self.encode_data(value), **meta}, **kwargs)

    def prepare_update_dict(self, dictionary: dict, meta: dict = None) -> dict:
        if meta is not None:
            assert len(meta) == len(dictionary)
            dct = {k: {self.name: self.encode_data(v), **meta[k]} for k, v in dictionary.items()}
        else:
            dct = {k: {self.name: self.encode_data(v)} for k, v in dictionary.items()}
        return dct

    def update(self, dictionary: dict, meta: dict = None):
        super().update(self.prepare_update_dict(dictionary, meta))

    async def async_update(self, dictionary: dict, meta: dict = None, context=None):
        await super().async_update(self.prepare_update_dict(dictionary, meta), context=context)

    def __getitem__(self, key, raw: bool = False):
        item = super().__getitem__(key)
        # get proper field name
        field_name = self.name
        if field_name not in item.keys():
            field_name = self._fallback_name
        if raw:
            item[field_name] = self.decode_data(item[field_name])
            return item
        else:
            return self.decode_data(item[field_name])

    def getitem(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        raw: bool = False,
        **kwargs,
    ):
        item = super().__getitem__(key=key, key_hash=key_hash, **kwargs)
        # get proper field name
        field_name = self.name
        if field_name not in item.keys():
            field_name = self._fallback_name

        if raw:
            item[field_name] = self.decode_data(item[field_name])
            return item
        else:
            return self.decode_data(item[field_name])

    async def async_getitem(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        raw: bool = False,
        **kwargs,
    ):
        item = await super().async_getitem(key=key, key_hash=key_hash, **kwargs)
        # get proper field name
        field_name = self.name
        if field_name not in item.keys():
            field_name = self._fallback_name

        if raw:
            item[field_name] = self.decode_data(item[field_name])
            return item
        else:
            return self.decode_data(item[field_name])

    def items(self, single_query: bool = False):
        for k, v in super().items(single_query=single_query):
            yield (k, v[self.name])

    def search(self, embed, size: int = None, **kwargs) -> tuple:
        if self.es_type == "dense_vector":
            for r in self.search_backend.find_embedding(
                self.index_name,
                field_name=self.name,
                query_embed=embed,
                size=size,
                binary_data=self.binary_data,
                **kwargs,
            ):
                yield [(item["_id"], self.decode_data(item["_source"][self.name])) for item in r]
        else:
            raise NotImplementedError("Currently only 'dense_vector' field type is supported for searching")

    async def search_async(self, embed, size: int = None, **kwargs) -> tuple:
        if self.es_type == "dense_vector":
            async for r in self.search_backend.find_embedding_async(
                self.index_name,
                field_name=self.name,
                query_embed=embed,
                size=size,
                binary_data=self.binary_data,
                **kwargs,
            ):
                yield [(item["_id"], self.decode_data(item["_source"][self.name])) for item in r]
        else:
            raise NotImplementedError("Currently only 'dense_vector' field type is supported for searching")


class EmbedESCacheDict(EmbedCacheDict, ESCacheDict):
    pass


class EmbedOSCacheDict(EmbedCacheDict, OSCacheDict):
    pass


class NestedMetaCacheDict:
    def generate_path_query(self, path: str, name="path", boost=1.0):
        if str(self.version) == "3.0":
            q = {
                "regexp": {
                    "base_key": {
                        "value": f"{path}.*",
                        "flags": "ALL",
                        "case_insensitive": True,
                        "max_determinized_states": 10000,
                        "rewrite": "constant_score",
                        "_name": name,
                        "boost": boost,
                    }
                }
            }
            return q
        elif float(self.version) >= 4.0:
            return {"term": {"path.tree": {"value": path, "boost": boost, "_name": name}}}
        else:
            raise NotImplementedError(f"Version '{self.version}' is not supported")

    @staticmethod
    def none_wrapper(f: callable) -> Any:
        """Function wrapper that will return None is the input is None and do processing otherwise

        Args:
            f (callable): function that need to do processing

        Returns:
            processed value or None
        """
        return lambda x: (f(x) if x is not None else None)

    @staticmethod
    def keys_intersection(dict1: dict, dict2: dict) -> list:
        dict1_set = set(dict1.keys())
        dict2_set = set(dict2.keys())
        return list(dict1_set & dict2_set)

    def preprocess_setitem(self, key: str = None, values: dict = None, meta: dict = {}) -> dict:
        if values is None:
            values = {}
        valid_keys = self.keys_intersection(self.properties, values)
        res = {
            self.name: [
                {k: self.encoder.get(k, lambda x: x)(val.get(k)) for k in valid_keys} for val in DL_to_LD(values)
            ],
            **meta,
        }
        if key is not None:
            res["base_key"] = key
        return res

    def postprocess_getitem(self, item: dict, raw: bool = False) -> dict:
        # decode content coming from ES engine
        embedding_content = item.get(self.name, [])

        if len(embedding_content) > 0:
            valid_keys = embedding_content[0].keys()
        else:
            valid_keys = []

        decoded_content = LD_to_DL(
            [{k: self.decoder.get(k, lambda x: x)(it.get(k)) for k in valid_keys} for it in embedding_content]
        )
        # return either raw content (with all the meta data) or only nested content
        if raw:
            res_item = {**item}
            res_item[self.name] = decoded_content
            return res_item
        else:
            return decoded_content

    # basic setting functionality

    def __setitem__(self, key, values: dict, meta: dict = {}) -> None:
        # prepare update dict
        self.update({key: values}, {key: meta})

    @contextmanager
    def context(self, *args, **kwargs):
        yield self.search_backend.es

    @asynccontextmanager
    async def async_context(self, *args, **kwargs):
        async with self.search_backend.async_context(*args, **kwargs) as es:
            yield es

    def prepare_bulk_update(
        self,
        update_dict: dict,
        meta: dict = {},
        original_keys: Optional[List[str]] = None,
    ) -> list:
        content = {
            key: self.preprocess_setitem(original_key, val, meta.get(key, {}))
            for (key, val), original_key in zip(update_dict.items(), original_keys)
        }
        # prepare bulk insert for searchable fields
        bulk_content = self.search_backend.prepare_bulk_insert(self.index_name, content)

        # prepare bulk insert for non-searchable fields
        for item in update_dict.keys():
            for sf in self.storage_fields:
                item_content = LD_to_DL(content[item][self.name])
                if sf in item_content.keys():
                    dct = self.storage[sf].prepare_update_dict(
                        {key: val for key, val in zip(item_content[sf], update_dict[item][sf])}
                    )
                    bulk_content += self.storage[sf].search_backend.prepare_bulk_insert(
                        self.storage[sf].index_name, dct
                    )

        return bulk_content

    def update(self, update_dict: dict, meta: dict = {}):
        # get bulk content for update
        prepared_update_dict = {self.get_hash(k): v for k, v in update_dict.items()}
        prepared_meta = {self.get_hash(k): v for k, v in meta.items()}
        bulk_content = self.prepare_bulk_update(prepared_update_dict, prepared_meta, update_dict.keys())
        # use bulk API to set item content
        with self.context() as es:
            self.helpers.bulk(es, bulk_content, max_retries=5)

    def __getitem__(self, key, raw: bool = False, skip_storage: bool = False) -> dict:
        # key_hash = self.get_hash(key)
        # get searchable fields
        result = self.postprocess_getitem(super().__getitem__(key), raw=raw)
        # decode content of the information stored in ES engine
        if not skip_storage:
            for sf in self.storage_fields:
                if sf in result.keys():
                    result[sf] = [self.storage[sf].getitem(key_hash=key) for key in result[sf]]
        return result

    def getmeta(self, key, metadata_key_list: list = []):
        if len(metadata_key_list) > 0:
            return super().__getitem__(key, _source_includes=",".join(metadata_key_list))
        else:
            return super().__getitem__(key, _source_excludes=self.name)

    def copyitem(self, src_key: str, tgt_key: str) -> None:
        item = self.__getitem__(src_key)
        self.__setitem__(tgt_key, item)

    async def async_setitem(
        self,
        key: Optional[str] = None,
        values: Optional[dict] = None,
        meta: Optional[dict] = None,
        key_hash: Optional[str] = None,
    ) -> None:
        if meta is None:
            meta = {}
        if values is None:
            values = {}
        # prepare update dict and update
        if key_hash is not None:
            await self.async_update(
                update_dict_hashed_keys={key_hash: values},
                meta_hashed_keys={key_hash: meta},
            )
        else:
            await self.async_update(update_dict={key: values}, meta={key: meta})

    async def async_getitem(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        raw: bool = False,
        skip_storage: bool = False,
    ) -> dict:
        result = self.postprocess_getitem(await super().async_getitem(key=key, key_hash=key_hash), raw=raw)
        # decode content of the information stored in ES engine
        if not skip_storage:
            for sf in self.storage_fields:
                if sf in result.keys():
                    result[sf] = await asyncio.gather(
                        *[self.storage[sf].async_getitem(key_hash=key) for key in result[sf]]
                    )
        return result

    async def async_getmeta(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        metadata_key_list: list = [],
    ) -> dict:
        if len(metadata_key_list) > 0:
            return await super().async_getitem(key=key, key_hash=key_hash, _source_includes=",".join(metadata_key_list))
        else:
            return await super().async_getitem(key, key_hash=key_hash, _source_excludes=self.name)

    async def async_copyitem(self, src_key: str, tgt_key: str) -> None:
        item = await self.async_getitem(src_key)
        await self.async_setitem(tgt_key, item)

    async def async_update(
        self,
        update_dict: Optional[dict] = None,
        meta: Optional[dict] = None,
        update_dict_hashed_keys: Optional[dict] = None,
        meta_hashed_keys: Optional[dict] = None,
    ):
        if meta is None:
            meta = {}
        # get bulk content for update
        if update_dict is not None:
            prepared_update_dict = {self.get_hash(k): v for k, v in update_dict.items()}
        else:
            prepared_update_dict = update_dict_hashed_keys
        if meta is not None:
            prepared_meta = {self.get_hash(k): v for k, v in meta.items()}
        else:
            prepared_meta = meta_hashed_keys
        bulk_content = self.prepare_bulk_update(
            prepared_update_dict,
            prepared_meta,
            original_keys=(update_dict.keys() if update_dict else [None] * len(prepared_update_dict)),
        )

        # use bulk API to set item content
        async with self.async_context() as es:
            bg = time.time()
            async for ok, result in self.helpers.async_streaming_bulk(
                es, bulk_content, max_chunk_bytes=MAX_CHUNK_BYTES
            ):
                action, result = result.popitem()
                if not ok:
                    cache_utils_logger.exception("failed to %s document %s" % (action, result))
                    raise Exception("failed to %s document %s" % (action, result))
                cache_utils_logger.info(f"bulk chunk processed successfully in {time.time() - bg} seconds")
                bg = time.time()
            # await self.helpers.async_bulk(es, bulk_content, max_retries=5)

    def updateitem(self, key, values: dict, meta: dict = {}) -> None:
        key = self.get_hash(key)
        self.updateitems({key: values}, meta={key: meta})

    def updateitems(self, update_dict: dict, meta: dict = {}) -> None:
        # prepared_dict = {}
        bulk_content = []
        for key, val in update_dict.items():
            key_hash = self.get_hash(key)
            try:
                content = self.__getitem__(key, raw=True)
                old_vals = content[self.name]
                del content[self.name]
                values = merge_dicts(old_vals, val)
                content.update(meta.get(key, {}))
                bulk_content += self.prepare_bulk_update({key_hash: values}, {key_hash: content}, [key])
            except KeyError:
                bulk_content += self.prepare_bulk_update({key_hash: val}, {key_hash: meta.get(key, {})}, [key])

        # use bulk API to set item content
        with self.context() as es:
            self.helpers.bulk(es, bulk_content, max_retries=5)

    def update_meta(self, key, meta: dict):
        raise NotImplementedError

    async def async_update_meta(self, key, meta: dict):
        raise NotImplementedError

    async def async_updateitem(self, key, values: dict, meta: dict = {}) -> None:
        cache_utils_logger.info(f"Updating item {key}")
        bg = time.time()
        await self.async_updateitems({key: values}, meta={key: meta})
        cache_utils_logger.info(f"Item {key} updated in {time.time() - bg} seconds")

    async def async_updateitems(self, update_dict: dict, meta: dict = {}) -> None:
        """Asynchronous bulk of items."""
        bulk_content = []
        contents = await asyncio.gather(
            *[self.async_getitem(key=key, raw=True) for key in update_dict],
            return_exceptions=True,
        )
        old_content = {k: c for k, c in zip(update_dict.keys(), contents) if isinstance(c, dict)}

        for key, val in update_dict.items():
            hashed_key = self.get_hash(key)
            try:
                content = old_content[key]
                old_vals = content[self.name]
                del content[self.name]
                values = merge_dicts(old_vals, val)
                content.update(meta.get(key, {}))
                bulk_content += self.prepare_bulk_update(
                    update_dict={hashed_key: values},
                    meta={hashed_key: content},
                    original_keys=[key],
                )
            except KeyError:
                bulk_content += self.prepare_bulk_update(
                    update_dict={hashed_key: val},
                    meta={hashed_key: meta.get(key, {})},
                    original_keys=[key],
                )

        # prepare bulk insert
        # bulk_content = self.esb.prepare_bulk_insert(self.index_name, prepared_dict)
        # use bulk API to set item content
        async with self.async_context() as es:
            bg = time.time()
            async for ok, result in self.helpers.async_streaming_bulk(
                es, bulk_content, max_chunk_bytes=MAX_CHUNK_BYTES
            ):
                action, result = result.popitem()
                if not ok:
                    cache_utils_logger.exception("failed to %s document %s" % (action, result))
                    raise Exception("failed to %s document %s" % (action, result))
                cache_utils_logger.info(f"bulk chunk processed successfully in {time.time() - bg} seconds")
                bg = time.time()
            # await self.helpers.async_bulk(es, bulk_content, max_retries=5)

    def postprocess_search_results(self, r: dict, return_dict: bool = False, only_key: bool = False):
        """Postprocess search results coming from ES engine.

        Args:
            r (dict): raw content dictionary
            return_dict (bool, optional): if True - return all the sample content. Defaults to ``False``.

        Returns:
            processed file content
        """
        # postprocess the resultss and return either dictionary or tuple of processed data
        if only_key:
            return {
                "path": r["_source"]["base_key"],
                "score": r["_score"],
                "_source": r["_source"],
            }

        # check if inner hit is available and if yes - return it
        if r.get("inner_hits", {}).get(self.name, None) is not None:
            inner_hit = r["inner_hits"][self.name]["hits"]["hits"][0]
        else:
            inner_hit = {"_source": {}, "_score": r["_score"]}

        if return_dict:
            valid_keys = self.keys_intersection(self.properties, inner_hit["_source"])
            content = {k: self.decoder.get(k, lambda x: x)(inner_hit["_source"].get(k)) for k in valid_keys}
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

    def search_streaming(self, *args, size: int = 100, scroll: str = "2m", collapse_field=None, **kwargs):
        # cannot use collapse together with scroll context
        if collapse_field is not None:
            cache_utils_logger.warning("Cannot use collapse together with scroll context, ignoring")
        # run streaming search
        for it in self.search(*args, size=size, scroll=scroll, collapse_field=None, **kwargs):
            yield it

    def search(
        self,
        embed=None,
        size: int = None,
        base_key_filter: str = None,
        regexp: str = None,
        collapse_field: str = None,
        scroll: str = None,
        scroll_kwargs: dict = {},
        kw_must: list = None,
        kw_must_not: list = None,
        return_dict: bool = False,
        force_nested_filter: dict = {},
        force_global_filter: dict = {},
        force_query_params: dict = {},
        candidates: int = 500,
        only_key: bool = False,
        source_filter: dict = None,
        return_raw: bool = False,
        **kwargs,
    ) -> tuple:
        """Synchronous search given the embedding query.

        Args:
            embed ([type]): input embedding that need to be searched for
            size (int, optional): number of elements that is returned in chunk. Defaults to 100.
            base_key_filter (str, optional): if provided - adds additional filtering of the results based on base_key. Deafults to None.
            collapse_field (str, optional): if provided - collapse results by the provided field. Defaults to ``"hash"``.
            scroll (str, optional): time to keep ES cursor in memory. Defaults to ``None``.
            kw_must (list, optional): list of keywords that must be included in the results. Defaults to ``None``.
            kw_must_not (list, optional): list of keywords that must not be included in the results. Defaults to ``None``.

        Yields:
            Iterator[tuple]: base key, embedding
        """

        # prepare nested custom filter
        if force_nested_filter == {}:
            nested_custom_filter = self.prepare_custom_filter(
                kw_field=f"{self.name}.keyword",
                kw_must=kw_must,
                kw_must_not=kw_must_not,
            )
        else:
            nested_custom_filter = force_nested_filter
        # prepare global custom filter
        if force_global_filter == {}:
            global_custom_filter = self.prepare_custom_filter(base_key_filter, regexp)
        else:
            global_custom_filter = force_global_filter

        if force_query_params == {}:
            query_params = self.prepare_query_params(collapse_field)
        else:
            query_params = force_query_params

        # prepare source filter
        if source_filter is None:
            source_filter = "base_key" if only_key else None
        # run search
        for r in self.search_backend.find_embedding(
            self.index_name,
            nested=True,
            query_embed=embed,
            nested_field_name=self.name,
            field_name=f"{self.name}.embedding",
            size=size,
            scroll=scroll,
            scroll_kwargs=scroll_kwargs,
            nested_custom_filter=nested_custom_filter,
            global_custom_filter=global_custom_filter,
            query_params=query_params,
            binary_data=self.binary_data,
            candidates=candidates,
            source_filter=source_filter,
            **kwargs,
        ):
            if return_raw:
                yield r
            else:
                yield [self.postprocess_search_results(item, return_dict, only_key) for item in r]

    async def search_async(
        self,
        embed=None,
        searchable_items_subset: Optional[list[str]] = None,
        size: int = None,
        base_key_filter: str = None,
        regexp: str = None,
        collapse_field: str = None,
        scroll: str = None,
        scroll_kwargs: dict = {},
        kw_must: list = None,
        kw_must_not: list = None,
        return_dict: bool = False,
        force_nested_filter: dict = {},
        force_global_filter: dict = {},
        force_query_params: dict = {},
        candidates: int = 500,
        only_key: bool = False,
        source_filter: dict = None,
        return_raw: bool = False,
        **kwargs,
    ):
        """Asyncronous search given the embedding query.

        Args:
            embed ([type]): input embedding that need to be searched for
            searchable_items_subset(list[str], optional): if set, limits search to items (base keys) from the list
            size (int, optional): number of elements that need to be returned. Defaults to None.
            base_key_filter(str, optional): if provided - adds additional filtering of the results based on base_key. Deafults to None.
            collapse_field (str, optional): if provided - collapse results by the provided field. Defaults to ``"hash"``.
            scroll (str, optional): time to keep ES cursor in memory. Defaults to ``None``.
            kw_must (list, optional): list of keywords that must be included in the results. Defaults to ``None``.
            kw_must_not (list, optional): list of keywords that must not be included in the results. Defaults to ``None``.

        Yields:
            Iterator[tuple]: base key, embedding
        """

        # prepare nested custom filter
        if force_nested_filter == {}:
            nested_custom_filter = self.prepare_custom_filter(
                kw_field=f"{self.name}.keyword",
                kw_must=kw_must,
                kw_must_not=kw_must_not,
            )
        else:
            nested_custom_filter = force_nested_filter
        # prepare global custom filter
        if force_global_filter == {}:
            global_custom_filter = self.prepare_custom_filter(base_key_filter, regexp)
        else:
            global_custom_filter = force_global_filter

        if force_query_params == {}:
            query_params = self.prepare_query_params(collapse_field)
        else:
            query_params = force_query_params

        bg = time.time()
        first = True
        # prepare source filter
        if source_filter is None:
            source_filter = "base_key" if only_key else None
        # run search
        async for r in self.search_backend.find_embedding_async(
            self.index_name,
            nested=True,
            query_embed=embed,
            nested_field_name=self.name,
            field_name=f"{self.name}.embedding",
            size=size,
            scroll=scroll,
            scroll_kwargs=scroll_kwargs,
            nested_custom_filter=nested_custom_filter,
            global_custom_filter=global_custom_filter,
            query_params=query_params,
            binary_data=self.binary_data,
            candidates=candidates,
            source_filter=source_filter,
            searchable_items_subset=searchable_items_subset,
            **kwargs,
        ):
            if first:
                first = False
                if DEBUG_LOGGING:
                    cache_utils_logger.debug(f"first results in: {time.time() - bg}")

            if return_raw:
                yield r
            else:
                yield [self.postprocess_search_results(item, return_dict, only_key) for item in r]

    async def search_streaming_async(
        self,
        *args,
        size: int = 100,
        scroll: str = "2m",
        collapse_field: str = None,
        **kwargs,
    ):
        # cannot use collapse together with scroll context
        if collapse_field is not None:
            cache_utils_logger.warning("Cannot use collapse together with scroll context, ignoring")

        async for it in self.search_async(*args, size=size, scroll=scroll, collapse_field=None, **kwargs):
            yield it

    def prepare_custom_filter(
        self,
        base_key_filter: str = None,
        regexp: str = None,
        mode: str = "startswith",
        **kwargs,
    ) -> dict:
        """Prepare custom filter for the embeddings

        Args:
            base_key_filter (str, optional): if not None - add filter on the base key (normally the USD path). Defaults to ``None``.

        Returns:
            dict: resulting custom ES filter
        """

        custom_filter = {"filter": []}

        if base_key_filter is not None:
            if mode == "startswith":
                value = f'"{base_key_filter}".*'
            elif mode == "contains":
                value = f'.*"{base_key_filter}".*'
            elif mode == "endswith":
                value = f'.*"{base_key_filter}"'
            else:
                raise NotImplementedError("Unknown mode")

            custom_filter["filter"].append({"regexp": {"base_key": {"value": value, "flags": "ALL"}}})

        if regexp is not None:
            custom_filter["filter"].append({"regexp": {"base_key": {"value": regexp}}})

        # add filtering options
        kw_filter = self.keywords_filter(**kwargs)
        if kw_filter is not None:
            custom_filter["filter"].extend(kw_filter["filter"])

        if len(custom_filter["filter"]) == 0:
            custom_filter = None

        return custom_filter

    # @staticmethod
    # def prepare_custom_nested_filter(nested_field:str, query:dict = {}, score_mode: str = "max", inner_hits:dict = {}):
    #     return {"must": [{
    #         "nested": {
    #             "path": nested_field,
    #             "score_mode": score_mode,
    #             "inner_hits": inner_hits,
    #             "query": query
    #         }}]}

    def keywords_filter(self, kw_field: str = "keyword", kw_must: list = None, kw_must_not: list = None) -> dict:
        custom_filter = {"filter": []}
        if kw_must is not None:
            custom_filter["filter"].append({"bool": {"must": [{"exists": {"field": kw_field}}]}})
            kw_must = kw_must if isinstance(kw_must, list) else [kw_must]
            custom_filter["filter"][0]["bool"]["must"].extend([{"match_phrase": {kw_field: kw}} for kw in kw_must])
        if kw_must_not is not None:
            # make sure it is list
            custom_filter["filter"].append({"bool": {}})
            kw_must_not = kw_must_not if isinstance(kw_must_not, list) else [kw_must_not]
            custom_filter["filter"][0]["bool"]["must_not"] = custom_filter["filter"][0]["bool"].get("must_not", [])
            custom_filter["filter"][0]["bool"]["must_not"].extend(
                [{"match_phrase": {kw_field: kw}} for kw in kw_must_not]
            )
        if len(custom_filter["filter"]) == 0:
            custom_filter = None

        return custom_filter

    @staticmethod
    def prepare_query_params(collapse_field: str = None) -> dict:
        """Prepare custom filter for the embeddings

        Args:
            collapse_field (str, optional): if not None - collapse results according to the value of this field. Defaults to ``None``.

        Returns:
            dict: resulting custom ES filter
        """

        if collapse_field is not None:
            query_params = {"collapse": {"field": collapse_field}}
        else:
            query_params = {}

        return query_params

    def list_keywords(
        self,
        base_key_filter: str = None,
        regexp: str = None,
        kw_must: list = None,
        kw_must_not: list = None,
    ):
        return self.search_backend.list_all_keywords(
            self.index_name,
            nested=True,
            nested_field_name=self.name,
            keyword_field=f"{self.name}.keyword",
            nested_custom_filter=self.prepare_custom_filter(
                kw_field=f"{self.name}.keyword",
                kw_must=kw_must,
                kw_must_not=kw_must_not,
            ),
            global_custom_filter=self.prepare_custom_filter(base_key_filter, regexp),
        )

    async def async_list_keywords(
        self,
        base_key_filter: str = None,
        regexp: str = None,
        kw_must: list = None,
        kw_must_not: list = None,
    ):
        return await self.search_backend.list_all_keywords_async(
            self.index_name,
            nested=True,
            nested_field_name=self.name,
            keyword_field=f"{self.name}.keyword",
            nested_custom_filter=self.prepare_custom_filter(
                kw_field=f"{self.name}.keyword",
                kw_must=kw_must,
                kw_must_not=kw_must_not,
            ),
            global_custom_filter=self.prepare_custom_filter(base_key_filter, regexp),
        )

    def get_keys_for_datatype(
        self,
        data_type: str,
        base_key_filter: str = None,
        regexp: str = None,
        kw_must: list = None,
        kw_must_not: list = None,
    ):
        if data_type not in self.properties.keys():
            return []
        else:
            return self.search_backend.list_all_keywords(
                self.index_name,
                nested=True,
                nested_field_name=self.name,
                keyword_field=f"{self.name}.{data_type}",
                nested_custom_filter=self.prepare_custom_filter(
                    kw_field=f"{self.name}.keyword",
                    kw_must=kw_must,
                    kw_must_not=kw_must_not,
                ),
                global_custom_filter=self.prepare_custom_filter(base_key_filter, regexp),
                return_ids=True,
            )

    async def async_get_keys_for_datatype(
        self,
        data_type: str,
        base_key_filter: str = None,
        regexp: str = None,
        kw_must: list = None,
        kw_must_not: list = None,
    ):
        if data_type not in self.properties.keys():
            return []
        else:
            return await self.search_backend.list_all_keywords_async(
                self.index_name,
                nested=True,
                nested_field_name=self.name,
                keyword_field=f"{self.name}.{data_type}",
                nested_custom_filter=self.prepare_custom_filter(
                    kw_field=f"{self.name}.keyword",
                    kw_must=kw_must,
                    kw_must_not=kw_must_not,
                ),
                global_custom_filter=self.prepare_custom_filter(base_key_filter, regexp),
                return_ids=True,
            )

    async def async_get_keys_for_datatype_iter(
        self,
        data_type: str,
        base_key_filter: str = None,
        regexp: str = None,
        kw_must: list = None,
        kw_must_not: list = None,
        max_requests: int = 1000,
        batch_mode: bool = False,
    ):
        if data_type in self.properties.keys():
            res = []
            async for it in self.search_backend.list_all_keywords_iter_async(
                self.index_name,
                nested=True,
                nested_field_name=self.name,
                keyword_field=f"{self.name}.{data_type}",
                nested_custom_filter=self.prepare_custom_filter(
                    kw_field=f"{self.name}.keyword",
                    kw_must=kw_must,
                    kw_must_not=kw_must_not,
                ),
                global_custom_filter=self.prepare_custom_filter(base_key_filter, regexp),
                return_ids=True,
                max_requests=max_requests,
            ):
                if batch_mode:
                    res.append(it)
                    if len(res) >= max_requests:
                        yield res
                        res = []
                else:
                    yield it

            if len(res) > 0:
                yield res

    async def actualize_storage(
        self,
        logging_timeout: float = 20,
        dry_run: bool = False,
        max_requests=20,
        lock=None,
    ):
        if lock is None:
            lock = asyncio.Lock()

        async def wrapper(gen):
            return [it async for it in gen]

        async def verify_storage(storage_type: str, storage: ESCacheDict) -> dict:
            bg = time.time()
            valid_keys = []
            storage_keys = []
            counter = 0
            storage_size = len(storage)
            async for keys in storage.async_keys_iter(max_requests=max_requests, batch_mode=True):
                storage_keys.extend(keys)
                counter += len(keys)
                async with lock:
                    search_res = await asyncio.gather(
                        *[
                            wrapper(
                                self.search_async(
                                    force_nested_filter=self.prepare_custom_filter(
                                        kw_field=f"{self.name}.{storage_type}",
                                        kw_must=[k],
                                    ),
                                    size=1,
                                )
                            )
                            for k in keys
                        ]
                    )

                    valid_keys.extend([k for s, k in zip(search_res, keys) if len(s) > 0])

                    if not dry_run:
                        # delete missing items
                        await asyncio.gather(
                            *[storage.async_delitem(key_hash=k) for s, k in zip(search_res, keys) if len(s) == 0]
                        )

                if time.time() - bg > logging_timeout:
                    cache_utils_logger.info(
                        f"verified ('{storage_type}'): {get_percentage_string(counter, storage_size)}"
                    )
                    bg = time.time()

            # storage_keys = list(await storage.async_keys())
            if dry_run:
                prepare_message(
                    msg=f"stats for '{storage_type}'",
                    item_list=[
                        f"valid items: {len(set(valid_keys))}",
                        f"total items in storage: {len(set(storage_keys))}",
                        f"to be removed: {len(set(storage_keys) - set(valid_keys))}",
                    ],
                    logger=cache_utils_logger.info,
                )
            return dict(valid=set(valid_keys), total=set(storage_keys), dry_run=dry_run)

        # get storage types
        results = await asyncio.gather(
            *[verify_storage(storage_type, storage) for storage_type, storage in self.storage.items()]
        )

        return {s: r for r, s in zip(results, self.storage)}

    @property
    def signature(self) -> dict:
        return {
            "host": self.search_backend.host,
            "port": self.search_backend.port,
            "name": self.name,
            "index_name": self.index_name,
        }

    @property
    def signature_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.signature).encode("latin1")).hexdigest()

    def __repr__(self):
        header = prepare_message(
            msg="Object",
            item_list=[
                f"class: {self.__class__.__module__}.{self.__class__.__name__}",
                f"address: {hex(id(self))}",
            ],
        )

        es = prepare_message(msg="ES engine", item_list=[f"{k}: {v}" for k, v in self.signature.items()])

        return header[1:] + es


class NestedMetaESCacheDict(NestedMetaCacheDict, ESCacheDict):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        name: str = "nested-metadata",
        binary_data: bool = BINARY_DATA,
        version: str = "5.0",
        number_of_shards: int = int(os.getenv("NUMBER_OF_SHARDS", "20")),
        es_observability: observability_utils.SearchBackendObservability = observability_utils.SearchBackendObservability(),
        index_config: Optional[IndexConfig] = None,
        **kwargs,
    ):

        if index_config is None:
            index_config = IndexConfig()

        self._index_config = index_config

        self.helpers = eu.helpers
        # prepare index name
        self.name = index_config.embedding_field_name
        self.dim = self._index_config.embedding_field_dim

        self.version = version
        # update name
        self.storage_index_name = f"{name}-ver4.0"
        self.index_name = f"{name}{'' if version is None else f'-ver{version}'}"
        self.binary_data = binary_data
        # prepare nested properties
        self.properties = {}
        self.encoder = {}
        self.decoder = {}
        #  > setting up embedding property
        if binary_data:
            self.properties["embedding"] = {"type": "binary", "doc_values": True}
            self.properties["embedding"] = {
                "type": "elastiknn_dense_float_vector",
                "elastiknn": {
                    "dims": self.dim,
                    "model": "lsh",
                    "similarity": "cosine",
                    "L": 99,
                    "k": 1,
                },
            }
            settings = {"index": {"number_of_shards": number_of_shards, "elastiknn": True}}
            # self.encoder["embedding"] = self.none_wrapper(lambda x:x)
            self.encoder["embedding"] = self.none_wrapper(normalize_embedding)
            self.decoder["embedding"] = self.none_wrapper(lambda x: x)
        else:
            settings = {"index": {"number_of_shards": number_of_shards}}
            self.properties["embedding"] = {
                "type": "dense_vector",
                # "index": True,
                # "similarity": "cosine",
            }
            if self.dim is not None:
                self.properties["embedding"]["dims"] = self.dim

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
        # add posisbility to add keywords per view
        self.properties["keyword"] = {"type": "keyword"}

        self.storage_fields = {}

        for sf in self._index_config.supported_storage_fields:
            if sf == SupportedStorageFields.image:
                self.properties[sf.value] = {"type": "keyword"}
                self.storage_fields[sf.value] = {}
                self.encoder["image"] = self.none_wrapper(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
            elif sf == SupportedStorageFields.image:
                self.properties[sf] = {"type": "keyword"}
                self.encoder["pointcloud"] = self.none_wrapper(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
                self.storage_fields[sf.value] = (
                    {
                        "encoder": self.none_wrapper(compress_data),
                        "decoder": self.none_wrapper(decompress_data),
                    },
                )
            else:
                raise ValueError(f"Unsupported storage field: {sf}")

        self.storage: Dict[str, EmbedCacheDict] = {
            sf: EmbedESCacheDict(
                host=host,
                port=port,
                index_name=f"{self.storage_index_name}-{sf}",
                name=f"siglip2-embedding-ver3.0-{sf}",
                es_type="object",
                es_dims=None,
                encoder=val.get("encoder", None),
                decoder=val.get("decoder", None),
                number_of_shards=number_of_shards,
                main_index_kwargs={
                    "enabled": False,
                    # "index": False,               # deprecated in latest ES
                    # "norms": False,               # deprecated in latest ES
                    # "index_options": "freqs",     # deprecated in latest ES
                    # "index.codec": "best_compression", # TODO (arozantsev): commented this out as speed for retrieving images may be important
                },
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
        # update path varible
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

        # prepare index fields
        index_fields = {
            self.name: {"type": "nested", "properties": {**self.properties}},
            **self.meta_data,
            **self.tags_meta_data,
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

    def update_meta(self, key, meta: dict):
        with self.context() as es:
            key_hashed = self.get_hash(key)
            if es.exists(index=self.index_name, id=key_hashed):
                es.update(index=self.index_name, id=key_hashed, doc=meta)
            else:
                # except NotFoundError:
                self.__setitem__(key, {}, meta)

    async def async_update_meta(
        self,
        key: Optional[str] = None,
        key_hash: Optional[str] = None,
        meta: Optional[dict] = None,
    ):
        if meta is None:
            meta = {}

        async with self.async_context() as es:
            _key = key_hash or self.get_hash(key)
            if await es.exists(index=self.index_name, id=_key):
                await es.update(index=self.index_name, id=_key, doc=meta)
            else:
                # except NotFoundError:
                await self.async_setitem(key=key, values={}, meta=meta, key_hash=key_hash)
