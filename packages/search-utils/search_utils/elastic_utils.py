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

# standard imports
import asyncio
import json
import logging
import os
from ast import literal_eval as make_tuple
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from time import time
from typing import Callable, Optional, Tuple

# third party modules
import numpy as np
from elasticsearch import AsyncElasticsearch, Elasticsearch
from elasticsearch import JSONSerializer as ESJSONSerializer
from elasticsearch import helpers

# local/ proprietary modules
from opentelemetry import trace

from . import observability_utils
from .misc_utils import none_on_empty_string, str2bool, str2list

elastic_utils_logger = logging.getLogger(__name__)

ES_SEARCH_METHOD = os.getenv("ES_SEARCH_METHOD", "exact")  # "lsh"
ES_MAX_INNER_RESULT_WINDOW = int(os.getenv("ES_MAX_INNER_RESULT_WINDOW", "100"))

ES_TIMEOUT = float(os.getenv("ES_TIMEOUT", "30"))
ES_MAX_RETRIES = int(os.getenv("ES_MAX_RETRIES", "5"))

tracer = trace.get_tracer(__name__)
EXTENDED_TRACING = str2bool(os.getenv("EXTENDED_TRACING", "False"))
VERBOSE_ES_LOGGING = str2bool(os.getenv("VERBOSE_ES_LOGGING", "False"))

if VERBOSE_ES_LOGGING:
    elastic_utils_logger.warning("Search backend verbose logging enabled, query performance will be degraded.")


@dataclass
class ESConfig:
    username: str = none_on_empty_string(os.getenv("ES_USERNAME"))
    password: str = none_on_empty_string(os.getenv("ES_PASSWORD"))
    cloud_id: str = none_on_empty_string(os.getenv("ES_CLOUD_ID"))
    bearer_auth: str = none_on_empty_string(os.getenv("ES_BEARER_AUTH"))
    opaque_id: str = none_on_empty_string(os.getenv("ES_OPAQUE_ID"))
    api_key_env: str = none_on_empty_string(os.getenv("ES_API_KEY"))
    hosts_env: str = none_on_empty_string(os.getenv("ES_HOSTS"))

    @property
    def basic_auth(self):
        if self.username is not None:
            return (self.username, self.password)
        else:
            return None

    @property
    def http_auth(self):
        if self.username is not None:
            return (self.username, self.password)
        else:
            return None

    @property
    def api_key(self):
        if self.api_key_env is not None:
            return make_tuple(self.api_key_env)
        else:
            return self.api_key_env

    @property
    def hosts(self):
        if self.hosts_env is None:
            return []
        else:
            return str2list(self.hosts_env)


class ESBackend:
    def __init__(
        self,
        es_observability: observability_utils.SearchBackendObservability,
        host: str = os.getenv("ES_HOST", "localhost"),
        port: int = int(os.getenv("ES_PORT", "9200")),
        protocol: str = os.getenv("ES_PROTOCOL", "http"),
        config: ESConfig = ESConfig(),
    ):
        # save server parameters
        self.host = host
        self.port = port
        self.protocol = protocol
        self.config = config
        # create instance of Elastic Search
        self.es = Elasticsearch(
            **self.es_args,
            timeout=ES_TIMEOUT,
            max_retries=ES_MAX_RETRIES,
            retry_on_timeout=True,
            http_compress=True,
        )
        self.async_es = AsyncElasticsearch(
            **self.es_args,
            timeout=ES_TIMEOUT,
            max_retries=ES_MAX_RETRIES,
            retry_on_timeout=True,
            http_compress=True,
        )
        self.observability = es_observability
        self.helpers = helpers

    async def close(self):
        await self.async_es.close()

    @property
    def es_args(self):
        return dict(
            hosts=[f"{self.protocol}://{self.host}:{self.port}"] + self.config.hosts,
            cloud_id=self.config.cloud_id,
            api_key=self.config.api_key,
            basic_auth=self.config.basic_auth,
            http_auth=self.config.http_auth,
            bearer_auth=self.config.bearer_auth,
            opaque_id=self.config.opaque_id,
        )

    def create_index(
        self,
        index_name: str,
        index_fields: dict = {},
        analysis: dict = {},
        settings: dict = {},
        exist_ok: bool = False,
    ):
        """Create index in elastic search DB.

        Args:
            index_name (str): name of the index that needs to be created
            index_fields (dict, optional): fields of the index that need to be created. Defaults to {}.
            exist_ok (bool, optional): if `True` - ignore index exist check error. Defaults to ``False``.
        """
        # additional arguments
        # kwargs = {}
        body = {"settings": {}}
        if exist_ok:
            body["ignore"] = 400
        if len(index_fields) > 0:
            body["mappings"] = {"properties": index_fields}
        if analysis != {}:
            body["settings"].update({"analysis": analysis})
        if settings != {}:
            body["settings"].update(settings)

        # create index
        r = self.es.indices.create(index=index_name, **body)
        if r.get("status") == 400:
            # update indec mappings
            r = self.es.indices.put_mapping(index=index_name, body=body["mappings"], ignore=[400])

    def add_item(self, index_name: str, key, content: dict):
        """Add item to index.

        Args:
            index_name (str): name of the index to which item should be added
            key: item key
            content (dict): item content
        """
        self.es.index(index=index_name, id=key, document=content)

    async def add_item_async(self, index_name: str, key, content: dict, context=None):
        """Add item to index.

        Args:
            index_name (str): name of the index to which item should be added
            key: item key
            content (dict): item content
        """
        async with self.async_context(context) as es:
            await es.index(index=index_name, id=key, document=content)

    def prepare_bulk_insert(self, index_name: str, update_dict: dict) -> list:
        """Prepare the list of items that is passed to bulk insert function.

        Args:
            index_name (str): name of the index, where items will be inserted
            update_dict (dict): dictionary with content

        Returns:
            list: list of items that will be bulk inserted into Elastic search engine
        """
        return [{"_index": index_name, "_id": k, "_source": v} for k, v in update_dict.items()]

    def update(self, index_name: str, update_dict: dict):
        self.helpers.bulk(self.es, self.prepare_bulk_insert(index_name, update_dict), max_retries=5)

    async def update_async(self, index_name: str, update_dict: dict, context=None):
        async with self.async_context(context) as es:
            async for ok, result in self.helpers.async_streaming_bulk(
                es, self.prepare_bulk_insert(index_name, update_dict)
            ):
                action, result = result.popitem()
                if not ok:
                    elastic_utils_logger.exception("failed to %s document %s" % (action, result))
                    raise Exception("failed to %s document %s" % (action, result))
            # await self.helpers.async_bulk(es, self.prepare_bulk_insert(index_name, update_dict), max_retries=5)

    def remove_item(self, index_name: str, key, removed_ok: bool = True):
        """Remove ID from index

        Args:
            index_name (str): name of index
            key: key that needs to be removed
            removed_ok (bool): if ``True`` - ignore missing keys
        """
        kwargs = {}
        if removed_ok:
            kwargs["ignore"] = [404]
        # remove index
        self.es.delete(index=index_name, id=key, **kwargs)

    async def remove_item_async(self, index_name: str, key, removed_ok: bool = True, context=None):
        """Remove ID from index

        Args:
            index_name (str): name of index
            key: key that needs to be removed
            removed_ok (bool): if ``True`` - ignore missing keys
        """
        kwargs = {}
        if removed_ok:
            kwargs["ignore"] = 404
        # remove index
        async with self.async_context(context) as es:
            await es.delete(index=index_name, id=key, **kwargs)

    def get_item(self, index_name: str, key, **kwargs) -> dict:
        """Get an element from elastic search index by key

        Args:
            index_name (str): name of index
            key: key of the element that needs to be retrieved

        Returns:
            dict: dictionary of results
        """
        return self.es.get(index=index_name, id=key, **kwargs)["_source"]

    async def async_get_item(self, index_name: str, key, context=None, **kwargs) -> dict:
        """Get an element from elastic search index by key

        Args:
            index_name (str): name of index
            key: key of the element that needs to be retrieved

        Returns:
            dict: dictionary of results
        """
        async with self.async_context(context=context) as es:
            item = await es.get(index=index_name, id=key, **kwargs)
        return item["_source"]

    @asynccontextmanager
    async def async_context(self, context=None):
        if context is None:
            yield self.async_es
        else:
            yield context

    @staticmethod
    def prepare_embedding_query(
        field_name: str,
        query_embed: np.ndarray,
        size: int = None,
        custom_filter: dict = None,
        query_params: dict = {},
        binary_data: bool = False,
        max_size: int = 10000,
        source_filter=None,
    ) -> dict:
        """Prepare query for the embedding search request

        Args:
            field_name (str): name of the field with embeddings
            query_embed (np.ndarray): query embedding that need to be looked for
            size (int): number of returned elements
            custom_filter (dict): custom filtering ES setting
            query_params (dict): additional query params
            binary_data (bool, optional): flag to specify if embedding is provided as binary blob. Defaults to ``False``.
            max_size (int, optional): maximum number of results. Defaults to ``10000``.
            source_filter (optional): additional source data filter. Defaults to ``None``.

        Returns:
            dict: body of the ES query
        """

        if binary_data:
            query = {
                "script_score": {
                    "query": {"bool": {"must": [{"exists": {"field": field_name}}]}},
                    "script": {
                        "source": "binary_vector_score",
                        "lang": "knn",
                        "params": {
                            "cosine": True,
                            "field": field_name,
                            "vector": query_embed,
                        },
                    },
                }
            }
            if custom_filter is not None:
                query["script_score"]["query"]["bool"].update(custom_filter)
        else:
            query = {
                "script_score": {
                    "query": {"bool": {"must": [{"exists": {"field": field_name}}]}},
                    "script": {
                        "source": f"(1.0+cosineSimilarity(params.query_vector, '{field_name}'))",
                        "params": {"query_vector": query_embed},
                    },
                }
            }
            if custom_filter is not None:
                query["script_score"]["query"]["bool"].update(custom_filter)

            # query = {"bool": {"must": []}}

            # if custom_filter:
            #     query["bool"].update(custom_filter)

            # query["bool"]["must"].append(
            #     {
            #         "function_score": {
            #             "script_score": {
            #                 "script": {
            #                     "source": f"(1.0+cosineSimilarity(params.query_vector, '{field_name}'))",
            #                     "params": {"query_vector": query_embed},
            #                 }
            #             }
            #         }
            #     }
            # )

        query_body = {"query": query}

        # add size constraint
        if size is not None:
            if size > max_size:
                elastic_utils_logger.warning(f"Requested: {size} items from index, which is higher than: {max_size}")
                query_body["size"] = max_size
            else:
                query_body["size"] = size

        query_body.update(query_params)
        if source_filter is not None:
            query_body["_source"] = source_filter
        return query_body

    def prepare_nested_embedding_query(
        self,
        nested_field_name: str,
        field_name: str,
        query_embed: np.ndarray = None,
        nested_score_mode: str = "max",
        size: int = None,
        nested_custom_filter: dict = None,
        global_custom_filter: dict = None,
        query_params: dict = {},
        binary_data: bool = False,
        max_size: int = 10000,
        candidates: int = 500,
        source_filter=None,
        search_method: str = ES_SEARCH_METHOD,
        inner_hits: str = {},
        minimum_should_match: int = 1,
    ) -> dict:
        """Prepare query for the embedding search request

        Args:
            field_name (str): name of the field with embeddings
            query_embed (np.ndarray): query embedding that need to be looked for
            size (int): number of returned elements
            custom_filter (dict): custom filtering ES setting
            query_params (dict): additional query params
            binary_data (bool, optional): flag to specify if embedding is provided as binary blob. Defaults to ``False``.
            max_size (int, optional): maximum number of results. Defaults to ``10000``.
            source_filter (optional): additional source data filter. Defaults to ``None``.

        Returns:
            dict: body of the ES query
        """
        if search_method == "approximate":
            search_method = "lsh"
        # if query_embed is None or not binary_data:
        query_body = {"bool": {"must": []}}
        # else:
        #     query_body = {"script_score": {"query": {"bool": {"must": []}}}}
        # prepare nested query
        if query_embed is not None or nested_custom_filter is not None:
            query = self.prepare_custom_nested_filter(
                nested_field_name,
                {},
                nested_score_mode,
                inner_hits=inner_hits,
                name="embedding",
            )
        else:
            query = None
        # search for embedding
        if query_embed is not None:
            # query["nested"]["query"]["bool"] = {
            #     "must": [{"exists": {"field": field_name}}]
            # }
            if binary_data:
                query["nested"]["query"]["bool"] = {
                    "must": [
                        {
                            "elastiknn_nearest_neighbors": {
                                "field": field_name,
                                "vec": {"values": query_embed},
                                "model": search_method,
                                "similarity": "cosine",
                                "candidates": candidates,
                            }
                        }
                    ]
                }
            else:
                query["nested"]["query"]["bool"] = {
                    "must": [
                        {
                            "function_score": {
                                "script_score": {
                                    "script": {
                                        "source": f"(1.0+cosineSimilarity(params.query_vector, '{field_name}'))",
                                        "params": {"query_vector": query_embed},
                                    }
                                }
                            }
                        }
                    ]
                }
            # add cutom filtering on the nested field
            if nested_custom_filter is not None:
                query["nested"]["query"]["bool"].update(nested_custom_filter)
            else:
                # remove the unused bool query from the request
                query["nested"]["query"] = query["nested"]["query"]["bool"]["must"][0]

            if global_custom_filter is not None:
                query_body["bool"].update(global_custom_filter)

            query_body["bool"]["should"] = query_body["bool"].get("should", []) + [query]
            query_body["bool"]["minimum_should_match"] = minimum_should_match

        # custom filtering on the field
        else:
            if nested_custom_filter is not None:
                if "bool" not in query["nested"]["query"]:
                    query["nested"]["query"]["bool"] = {}
                query["nested"]["query"]["bool"].update(nested_custom_filter)

            if global_custom_filter is not None:
                query_body["bool"].update(global_custom_filter)

            if query is not None:
                query_body["bool"]["must"].append(query)

        query_body = {"query": query_body}

        # add size constraint
        if size is not None:
            if size > max_size:
                elastic_utils_logger.warning(f"Requested: {size} items from index, which is higher than: {max_size}")
                query_body["size"] = max_size
            else:
                query_body["size"] = size

        query_body.update(query_params)
        if source_filter is not None:
            query_body["_source"] = source_filter

        if VERBOSE_ES_LOGGING:
            elastic_utils_logger.debug(query_body)

        return query_body

    def find_embedding(
        self,
        index_name: str,
        scroll: str = None,
        scroll_kwargs: dict = {},
        nested: bool = False,
        return_all: bool = False,
        **kwargs,
    ):
        """Sort embeddings in index according to cosine distance to the provided query

        Args:
            index_name (str): name of the index, where to search
            scroll (str, optional): time to keep cursor in ES memory. Defaults to None.
            return_all (bool): If ``True`` yield all samples received from ES at once, instead of per sample yield

        Yields:
            dict: search item
        """
        # select the correct function for query preparation
        if nested:
            query_func = self.prepare_nested_embedding_query
        else:
            query_func = self.prepare_embedding_query
        # prepare embedding query
        query_kwargs = dict(index=index_name, **query_func(**kwargs))

        if scroll is None:
            request_start_time = time()
            es_response = self.es.search(**query_kwargs)
            total_query_time = time() - request_start_time
            self.observability.observe_query(
                observability_utils.get_query_type(kwargs.get("search_method"), self.es),
                query_kwargs.get("size", -1),
                len(es_response["hits"]["hits"]),
                es_response["took"] / 1000,
                total_query_time,
                scroll=False,
            )

            if return_all:
                yield es_response["hits"]["hits"]
            else:
                for item in es_response["hits"]["hits"]:
                    yield [item]
        else:
            request_start_time = time()
            es_response = self.es.search(**query_kwargs, scroll=scroll)
            total_query_time = time() - request_start_time
            self.observability.observe_query(
                observability_utils.get_query_type(kwargs.get("search_method"), self.es),
                query_kwargs.get("size", -1),
                len(es_response["hits"]["hits"]),
                es_response["took"] / 1000,
                total_query_time,
                scroll=False,
            )

            scroll_id = es_response.get("_scroll_id")

            while scroll_id and es_response["hits"]["hits"]:
                if return_all:
                    yield es_response["hits"]["hits"]
                else:
                    for hit in es_response["hits"]["hits"]:
                        yield [hit]

                es_response = self.es.scroll(scroll_id=scroll_id, scroll=scroll, **scroll_kwargs)
                scroll_id = es_response.get("_scroll_id")

    async def find_embedding_async(
        self,
        index_name: str,
        scroll: str = None,
        scroll_kwargs: dict = {},
        nested: bool = False,
        context=None,
        return_all: bool = False,
        searchable_items_subset: Optional[list[str]] = None,
        **kwargs,
    ) -> list:
        """Sort embeddings in index according to cosine distance to the provided query

        Args:
            index_name (str): name of the index, where to search
            field_name (str): name of the field with embeddings
            query_embed (np.ndarray): query embedding that need to be looked for
            scroll (str, optional): time to keep cursor in ES memory. Defaults to None.
            context (optional): asynchronous ES context. Defaults to None.
            return_all (bool): If ``True`` yield all samples received from ES at once, instead of per sample yield

        Yields:
            list: list of responses from Elastic search engine
        """
        # select the correct function for query preparation
        if nested:
            query_func = self.prepare_nested_embedding_query
        else:
            query_func = self.prepare_embedding_query

        # prepare embedding query
        query_kwargs = dict(index=index_name, **query_func(**kwargs))
        query_size = query_kwargs.get("size", -1)

        if searchable_items_subset is not None:
            terms_filter = {"query": {"bool": {"filter": [{"terms": {"base_key": searchable_items_subset}}]}}}
            if "body" in query_kwargs:
                # In the OS backend query in nested under `body` key
                query_kwargs["body"].update(terms_filter)
            else:
                query_kwargs.update(terms_filter)

        # print final query
        if VERBOSE_ES_LOGGING:
            elastic_utils_logger.debug(f"query_kwargs: '{ESJSONSerializer().dumps(query_kwargs)}'")

        async with self.async_context(context=context) as es:
            if scroll is None:
                request_start_time = time()
                with tracer.start_as_current_span("es_query") as span:
                    es_response = await es.search(**query_kwargs)
                    span.set_attribute("es_query_took", es_response["took"])
                    span.set_attribute("es_query_size", query_size)
                    if EXTENDED_TRACING:
                        span.set_attribute("query", ESJSONSerializer().dumps(query_kwargs))
                        span.set_attribute("result", json.dumps(es_response))
                if VERBOSE_ES_LOGGING:
                    elastic_utils_logger.debug(f"query result: '{ESJSONSerializer().dumps(es_response)}'")
                total_query_time = time() - request_start_time
                self.observability.observe_query(
                    observability_utils.get_query_type(kwargs.get("search_method"), es),
                    query_kwargs.get("size", -1),
                    len(es_response["hits"]["hits"]),
                    es_response["took"] / 1000,
                    total_query_time,
                    scroll=False,
                )
                if return_all:
                    yield es_response["hits"]["hits"]
                else:
                    for item in es_response["hits"]["hits"]:
                        yield [item]
            else:
                request_start_time = time()
                with tracer.start_as_current_span("es_query") as span:
                    es_response = await es.search(**query_kwargs, scroll=scroll)
                    span.set_attribute("es_query_took", es_response["took"])
                    span.set_attribute("es_query_size", query_size)
                    if EXTENDED_TRACING:
                        span.set_attribute("query", ESJSONSerializer().dumps(query_kwargs))
                        span.set_attribute("result", json.dumps(es_response))
                if VERBOSE_ES_LOGGING:
                    elastic_utils_logger.debug(f"query result: '{ESJSONSerializer().dumps(es_response)}'")
                total_query_time = time() - request_start_time
                self.observability.observe_query(
                    observability_utils.get_query_type(kwargs.get("search_method"), es),
                    query_size,
                    len(es_response["hits"]["hits"]),
                    es_response["took"] / 1000,
                    total_query_time,
                    scroll=False,
                )
                try:
                    scroll_id = es_response.get("_scroll_id")
                    while scroll_id and es_response["hits"]["hits"]:
                        if return_all:
                            yield es_response["hits"]["hits"]
                        else:
                            for hit in es_response["hits"]["hits"]:
                                yield [hit]

                        if len(es_response["hits"]["hits"]) < query_size:
                            # Break as fetching the next page won't return any results anyway
                            break

                        with tracer.start_as_current_span("es_query_scroll") as span:
                            es_response = await es.scroll(scroll_id=scroll_id, scroll=scroll, **scroll_kwargs)
                            self.observability.observe_query(
                                observability_utils.get_query_type(kwargs.get("search_method"), es),
                                query_size,
                                len(es_response["hits"]["hits"]),
                                es_response["took"] / 1000,
                                total_query_time,
                                scroll=True,
                            )
                            span.set_attribute("es_query_took", es_response["took"])
                            if EXTENDED_TRACING:
                                span.set_attribute("result", json.dumps(es_response))
                            if VERBOSE_ES_LOGGING:
                                elastic_utils_logger.debug(f"query result: '{ESJSONSerializer().dumps(es_response)}'")
                        scroll_id = es_response.get("_scroll_id")
                finally:
                    # Clear scroll context in the background
                    asyncio.create_task(es.clear_scroll(scroll_id=scroll_id))

    def search(self, index_name: str, query_body: dict):
        return self.es.search(index=index_name, **query_body)

    async def search_async(self, index_name: str, query_body: dict, context=None):
        async with self.async_context(context=context) as es:
            return await es.search(index=index_name, **query_body)

    def get_all_keys(self, index_name: str, max_requests: int = 5000) -> list:
        """Get all keys from elastic search index

        Args:
            index_name (str): name of the index

        Returns:
            list: list of keys that are stored in it
        """
        # get total number of items
        hits = self.helpers.scan(
            self.es,
            query={"_source": False, "query": {"match_all": {}}},
            scroll="1m",
            size=max_requests,
            index=index_name,
        )
        # return their indices
        return [h["_id"] for h in hits]

    async def get_all_keys_async(self, index_name: str, max_requests: int = 5000, context=None) -> list:
        """Get all keys from elastic search index

        Args:
            index_name (str): name of the index

        Returns:
            list: list of keys that are stored in it
        """
        # get total number of items
        async with self.async_context(context=context) as es:
            hits = [
                h
                async for h in self.helpers.async_scan(
                    es,
                    query={"_source": False, "query": {"match_all": {}}},
                    scroll="1m",
                    size=max_requests,
                    index=index_name,
                )
            ]
        # return their indices
        return [h["_id"] for h in hits]

    async def get_all_keys_iter_async(self, index_name: str, max_requests: int = 5000, context=None) -> list:
        """Get all keys from elastic search index

        Args:
            index_name (str): name of the index

        Returns:
            list: list of keys that are stored in it
        """
        # get total number of items
        async with self.async_context(context=context) as es:
            async for h in self.helpers.async_scan(
                es,
                query={"_source": False, "query": {"match_all": {}}},
                scroll="10m",
                size=max_requests,
                index=index_name,
            ):
                yield h["_id"]

    def get_all_items(self, index_name: str, single_query: bool = False) -> tuple:
        """Get all items one by one

        Args:
            index_name (str): name of the index, for which items need to be retrieved
            single_query (bool, optional): if ``True`` - get results in a single query (might occupy a lot of memory). Defaults to ``False``.

        Yields:
            tuple: item key and value
        """
        if single_query:
            es_reponse = self.es.search(index=index_name, query={"match_all": {}})
            hits = es_reponse["hits"]["hits"]
            for h in hits:
                yield (h["_id"], h["_source"])
        else:
            keys = self.get_all_keys(index_name)
            for k in keys:
                yield (k, self.get_item(index_name, k))

    def get_keyword_retrieval_query(self, keyword_field: str, custom_filter: dict = {}) -> dict:
        bool_query = {} if custom_filter is None else custom_filter
        bool_query["must"] = bool_query.get("must", []) + [{"exists": {"field": keyword_field}}]
        return {"query": {"bool": bool_query}, "_source": [keyword_field]}

    def get_keyword_retrieval_nested_query(
        self,
        nested_field_name: str,
        keyword_field: str,
        nested_score_mode: str = "max",
        max_inner_result_window: int = ES_MAX_INNER_RESULT_WINDOW,
        nested_custom_filter: dict = None,
        global_custom_filter: dict = None,
        return_ids: bool = False,
        **kwargs,
    ) -> dict:
        """Function that prepares nested keywork retrieval query

        Args:
            nested_field_name (str): nested field name
            keyword_field (str): keyword field inside the nested field
            nested_score_mode (str, optional): scoring mode of the inner hits under nested query. Defaults to `"max"`.
            max_inner_result_window (int, optional): maximum items in inner hits (). Defaults to 100.
            nested_custom_filter (dict, optional): filtering query applied to the nested field. Defaults to None.
            global_custom_filter (dict, optional): filtering query applied globally. Defaults to None.
            return_ids (bool, optional): if `True` will only return element IDs (no source). Defaults to `False`.

        Returns:
            dict: query that is then passed to the ES engine

        max_inner_result_window can be increased as follows (source: https://stackoverflow.com/questions/63337121/elasticsearch-unlimited-size-inner-hits-elasticsearch):
        ```
        PUT your-index/_settings
        {
        "index.max_inner_result_window": 1000
        }
        ```
        default maximum is `100`.

        """

        query_body = {"query": {"bool": {"must": []}}}

        nested_query = {"nested": {"path": nested_field_name, "query": {"bool": {"must": []}}}}
        if not return_ids:
            nested_query["nested"].update(
                {
                    "score_mode": nested_score_mode,
                    "inner_hits": {
                        "_source": False,
                        "size": max_inner_result_window,
                        "docvalue_fields": [keyword_field],
                    },
                }
            )

        # add cutom filtering on the nested field
        if nested_custom_filter is not None:
            nested_query["nested"]["query"]["bool"].update(nested_custom_filter)

        # add global filter
        if global_custom_filter is not None:
            query_body["query"]["bool"].update(global_custom_filter)

        nested_query["nested"]["query"]["bool"]["must"].append({"exists": {"field": keyword_field}})
        # append nested query
        query_body["query"]["bool"]["must"].append(nested_query)
        # finalize ES query
        return {**query_body, "_source": False if return_ids else ["inner_hits"]}

    @staticmethod
    def prepare_custom_nested_filter(
        nested_field: str,
        query: dict = {},
        score_mode: str = "max",
        inner_hits: dict = {},
        name: str = "nested-query",
    ) -> dict:
        """Wrapper for the nested query

        Args:
            nested_field (str): nested field in ES index.
            query (dict, optional): query that is applied to nested fields. Defaults to {}.
            score_mode (str, optional): scoring mode of the nested field elements. Defaults to "max".
            inner_hits (dict, optional): which inner hits should be returned. Defaults to {}.

        Returns:
            dict: nested query, wrapped into a must constuct
        """
        return {
            "nested": {
                "path": nested_field,
                "score_mode": score_mode,
                "inner_hits": inner_hits,
                "_name": name,
                "query": query,
            }
        }

    @staticmethod
    def process_keyword_retrieval_query(x: dict, keyword_field: str, return_ids: bool = False, **kwargs):
        if return_ids:
            return x["_id"]
        else:
            return x["_source"][keyword_field]

    @staticmethod
    def process_keyword_retrieval_nested_query(
        x: dict,
        keyword_field: str,
        nested_field_name: str,
        return_ids: bool = False,
        return_all: bool = False,
        **kwargs,
    ):
        if return_ids:
            return x["_id"]
        elif return_all:
            return [h["fields"][keyword_field] for h in x["inner_hits"][nested_field_name]["hits"]["hits"]]
        else:
            return x["inner_hits"][nested_field_name]["hits"]["hits"][0]["fields"][keyword_field]

    def get_list_keywords_func(self, nested: bool = False, **kwargs) -> Tuple[Callable, Callable]:
        """Get query and post-processing functionality for list_keywords ES response processing."""
        if nested:
            query_func = self.get_keyword_retrieval_nested_query
            process_func = partial(self.process_keyword_retrieval_nested_query, **kwargs)
        else:
            query_func = self.get_keyword_retrieval_query
            process_func = partial(self.process_keyword_retrieval_query, **kwargs)

        def processing_fn(h):
            processed_h = process_func(h)
            # organize keywords in the dictionary
            if not isinstance(processed_h, list):
                content = [processed_h]
            else:
                content = processed_h
            return content

        return query_func, processing_fn

    def list_all_keywords(self, index_name: str, max_requests: int = 1000, nested: bool = False, **kwargs) -> dict:
        """List of keywords that are there in ES engine for a specific field.

        Args:
            index_name (str): index name that needs to be processed.
            keyword_field (str): name of the keyword field
            custom_filter (dict, optional): additional filtering that is applied to the query. Defaults to `{}`.
            max_requests (int, optional): maximum number of requests. Defaults to `1000`.

        Returns:
            dict: mapping from a keyword to the number of documents that contain it.
        """
        # Get query and post-processing functionality for list_keywords ES response processing.
        query_func, process_func = self.get_list_keywords_func(nested=nested, **kwargs)

        results = {}
        for h in self.helpers.scan(
            self.es,
            query=query_func(**kwargs),
            request_timeout=30,
            size=max_requests,
            index=index_name,
        ):
            # organize keywords in the dictionary
            results = self.postprocess_list_results(h, process_func, results)

        return results

    async def list_all_keywords_async(
        self,
        index_name: str,
        max_requests: int = 1000,
        nested: bool = False,
        context=None,
        **kwargs,
    ) -> dict:
        """Asynchronous listing of keywords that are there in ES engine for a specific field.

        Args:
            index_name (str): index name that needs to be processed.
            keyword_field (str): name of the keyword field
            custom_filter (dict, optional): additional filtering that is applied to the query. Defaults to `{}`.
            max_requests (int, optional): maximum number of requests. Defaults to `1000`.
            context (optional): elastic search context. Defaults to `None`.

        Returns:
            dict: mapping from a keyword to the number of documents that contain it.
        """
        # Get query and post-processing functionality for list_keywords ES response processing.
        query_func, process_func = self.get_list_keywords_func(nested=nested, **kwargs)

        async with self.async_context(context=context) as es:
            results = {}
            async for h in self.helpers.async_scan(
                es,
                query=query_func(**kwargs),
                scroll="1m",
                size=max_requests,
                index=index_name,
            ):
                # organize keywords in the dictionary
                results = self.postprocess_list_results(h, process_func, results)

        return results

    async def list_all_keywords_iter_async(
        self,
        index_name: str,
        max_requests: int = 1000,
        nested: bool = False,
        context=None,
        **kwargs,
    ) -> dict:
        """Asynchronous listing of keywords that are there in ES engine for a specific field.

        Args:
            index_name (str): index name that needs to be processed.
            keyword_field (str): name of the keyword field
            custom_filter (dict, optional): additional filtering that is applied to the query. Defaults to `{}`.
            max_requests (int, optional): maximum number of requests. Defaults to `1000`.
            context (optional): elastic search context. Defaults to `None`.

        Returns:
            dict: mapping from a keyword to the number of documents that contain it.
        """
        # Get query and post-processing functionality for list_keywords ES response processing.
        query_func, process_func = self.get_list_keywords_func(nested=nested, **kwargs)

        async with self.async_context(context=context) as es:
            returned = set([])
            async for h in self.helpers.async_scan(
                es,
                query=query_func(**kwargs),
                scroll="1m",
                size=max_requests,
                index=index_name,
            ):
                for k in process_func(h):
                    if not isinstance(k, list):
                        k = [k]
                    for item in k:
                        if item not in returned:
                            yield item
                            returned.add(item)

    @staticmethod
    def postprocess_list_results(h, process_func: callable, results: dict = {}) -> dict:
        for k in process_func(h):
            if not isinstance(k, list):
                k = [k]
            for item in k:
                results[item] = results.get(item, 0) + 1
        return results
