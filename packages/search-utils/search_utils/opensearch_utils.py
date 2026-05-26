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

import logging

# standard modules
import os
from enum import Enum

# third party modules
import numpy as np
import orjson
from opensearchpy import AsyncOpenSearch, OpenSearch, helpers
from opensearchpy.serializer import JSONSerializer, SerializationError, string_types
from opentelemetry import trace
from pydantic import Field
from pydantic_settings import BaseSettings

# local/ proprietary modules
from search_utils import observability_utils
from search_utils.elastic_utils import (
    ES_MAX_RETRIES,
    ES_SEARCH_METHOD,
    ES_TIMEOUT,
    ESBackend,
    ESConfig,
)

tracer = trace.get_tracer(__name__)


class ORJSONSerializer(JSONSerializer):
    def dumps(self, data):
        with tracer.start_as_current_span("orjson_serialize"):
            # don't serialize strings
            if isinstance(data, string_types):
                return data

            try:
                return orjson.dumps(
                    data,
                    option=orjson.OPT_SERIALIZE_NUMPY,
                    default=self.default,
                ).decode("utf-8")
            except (ValueError, TypeError) as e:
                raise SerializationError(data, e)

    def loads(self, data):
        with tracer.start_as_current_span("orjson_deserialize"):
            try:
                return orjson.loads(data)
            except (ValueError, TypeError) as e:
                raise SerializationError(data, e)


try:
    from ngsearch_backend.opensearch_transport import InstrumentedAsyncTransport
except ImportError:
    InstrumentedAsyncTransport = None

logger = logging.getLogger(__name__)


class AvailableSerializers(str, Enum):
    orjson = "orjson"
    json = "json"


class OSBackendSettings(BaseSettings):
    os_serializer: AvailableSerializers = Field(default=AvailableSerializers.orjson)


def get_serializer(serializer: str):
    if serializer is None:
        return JSONSerializer()
    elif serializer == AvailableSerializers.orjson:
        if ORJSONSerializer is not None:
            return ORJSONSerializer()
        else:
            return JSONSerializer()
    elif serializer == AvailableSerializers.json:
        return JSONSerializer()
    else:
        raise ValueError(f"Unknown serializer: {serializer}")


class OpenSearchIndexSettings(BaseSettings):
    vision_generated_dynamic_templates_suffix: str = Field(
        default="vlm_generated",
        description="suffix for the vision generated dynamic templates",
    )


class OSBackend(ESBackend):
    def __init__(
        self,
        es_observability: observability_utils.SearchBackendObservability,
        host: str = os.getenv("ES_HOST", "localhost"),
        port: int = int(os.getenv("ES_PORT", "9200")),
        protocol: str = os.getenv("ES_PROTOCOL", "http"),
        config: ESConfig = ESConfig(),
        index_settings: OpenSearchIndexSettings = OpenSearchIndexSettings(),
        os_backend_settings: OSBackendSettings | None = None,
    ):
        # save server parameters
        self.host = host
        self.port = port
        self.protocol = protocol
        self.config = config
        self._index_settings = index_settings
        if os_backend_settings is None:
            os_backend_settings = OSBackendSettings()
        self._os_backend_settings = os_backend_settings
        # create instance of Open Search
        self.es = OpenSearch(
            **self.es_args,
            timeout=ES_TIMEOUT,
            max_retries=ES_MAX_RETRIES,
            retry_on_timeout=True,
            http_compress=True,
            serializer=get_serializer(os_backend_settings.os_serializer),
        )
        async_transport_kwargs = {}

        if InstrumentedAsyncTransport is not None:
            async_transport_kwargs["transport_class"] = InstrumentedAsyncTransport

        self.async_es = AsyncOpenSearch(
            **self.es_args,
            timeout=ES_TIMEOUT,
            max_retries=ES_MAX_RETRIES,
            retry_on_timeout=True,
            http_compress=True,
            serializer=get_serializer(os_backend_settings.os_serializer),
            **async_transport_kwargs,
        )

        logger.info("Using serializer: %s", os_backend_settings.os_serializer.value)

        self.observability = es_observability
        self.helpers = helpers

    def create_index(
        self,
        index_name: str,
        index_fields: dict = {},
        analysis: dict = {},
        settings: dict = {},
        exist_ok: bool = False,
    ):
        """Create index in opensearch DB.

        Args:
            index_name (str): name of the index that needs to be created
            index_fields (dict, optional): fields of the index that need to be created. Defaults to {}.
            exist_ok (bool, optional): if `True` - ignore index exist check error. Defaults to ``False``.
        """
        # additional arguments
        # kwargs = {}
        body = {"settings": {}}
        if len(index_fields) > 0:
            body["mappings"] = {"properties": index_fields}
        if analysis != {}:
            body["settings"].update({"analysis": analysis})
        if settings != {}:
            body["settings"].update(settings)

        dynamic_templates = [
            {
                "search_as_you_type_mappings": {
                    "match_mapping_type": "string",
                    "match": "*_sayt",
                    "mapping": {"type": "search_as_you_type"},
                }
            },
            {
                "usd_properties": {
                    "match": "usd_properties",
                    "mapping": {"type": "nested"},
                }
            },
            {
                "usd_properties_sayt": {
                    "path_match": "usd_properties.*_sayt",
                    "match_mapping_type": "string",
                    "mapping": {"type": "search_as_you_type"},
                }
            },
            {
                "usd_properties_keyword": {
                    "path_match": "usd_properties.*",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"},
                }
            },
            {
                "usd_properties_numeric": {
                    "path_match": "usd_properties.value_numeric",
                    "match_mapping_type": "double",
                    "mapping": {"type": "double"},
                }
            },
            {
                "usd_dimensions": {
                    "match": "usd_dimensions",
                    "mapping": {"type": "object"},
                }
            },
            {
                "usd_dimensions_float": {
                    "path_match": "usd_dimensions.*",
                    "match_mapping_type": "double",
                    "mapping": {"type": "float"},
                }
            },
            {
                "usd_dimensions_string": {
                    "path_match": "usd_dimensions.*",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}": {
                    "match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}",
                    "mapping": {"type": "nested"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}_text_subfields": {
                    "path_match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}.*name",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}_text_subfields": {
                    "path_match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}.*_text",
                    "match_mapping_type": "string",
                    "mapping": {"type": "text"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}_bool_subfields": {
                    "path_match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}.*_bool",
                    "match_mapping_type": "boolean",
                    "mapping": {"type": "boolean"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}_sayt_subfields": {
                    "path_match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}.*_sayt",
                    "match_mapping_type": "string",
                    "mapping": {"type": "search_as_you_type"},
                }
            },
            {
                f"plugin_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}_keyword_subfields": {
                    "path_match": f"plugin_*_metadata_{self._index_settings.vision_generated_dynamic_templates_suffix}.*_keyword",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"},
                }
            },
        ]

        body["mappings"]["dynamic_templates"] = dynamic_templates

        kwargs = {}
        if exist_ok:
            kwargs["ignore"] = 400

        # create index
        logger.debug("Creating index: %s\n%s", index_name, body)
        r = self.es.indices.create(index=index_name, body=body, **kwargs)
        if r.get("status") == 400:
            # update indec mappings
            logger.debug("Updating index mappings: %s\n%s", index_name, body["mappings"])
            response = self.es.indices.put_mapping(index=index_name, body=body["mappings"], ignore=[400])
            if response.get("error") is not None:
                logger.error("Error updating index mappings: %s", response.get("error"))

    def _get_knn_query_exact(self, field_name: str, query_embed: np.ndarray) -> dict:
        return {
            "must": [
                {
                    "script_score": {
                        "query": {"match_all": {}},
                        "script": {
                            "source": "knn_score",
                            "lang": "knn",
                            "params": {
                                "field": field_name,
                                "query_value": query_embed,
                                "space_type": "cosinesimil",
                            },
                        },
                    }
                }
            ]
        }

    def _get_knn_query_approximate(self, field_name: str, query_embed: np.ndarray, candidates: int) -> dict:
        return {"must": [{"knn": {field_name: {"vector": query_embed, "k": candidates}}}]}

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
        query_body = {"bool": {"must": []}}
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
            query["nested"]["query"]["bool"] = (
                self._get_knn_query_exact(field_name, query_embed)
                if search_method == "exact"
                else self._get_knn_query_approximate(field_name, query_embed, candidates)
            )
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

        query_body = {"body": {"query": query_body}}

        # add size constraint
        if size is not None:
            if size > max_size:
                logger.warning(f"Requested: {size} items from index, which is higher than: {max_size}")
                query_body["size"] = int(max_size)
            else:
                query_body["size"] = int(size)

        query_body.update(query_params)
        if source_filter is not None:
            query_body["_source_includes"] = source_filter

        logger.debug(query_body)

        return query_body

    async def get_all_keys_iter_async(self, index_name: str, max_requests: int = 5000, context=None) -> list:
        """Get all keys from elastic search index

        Args:
            index_name (str): name of the index

        Returns:
            list: list of keys that are stored in it
        """
        # get total number of items
        async with self.async_context(context=context) as es:
            async for h in helpers.async_scan(
                es,
                query={"_source": False, "query": {"match_all": {}}},
                scroll="10m",
                size=int(max_requests),
                index=index_name,
            ):
                yield h["_id"]

    def add_item(self, index_name: str, key, content: dict):
        """Add item to index.

        Args:
            index_name (str): name of the index to which item should be added
            key: item key
            content (dict): item content
        """
        self.es.index(index=index_name, id=key, body=content)
