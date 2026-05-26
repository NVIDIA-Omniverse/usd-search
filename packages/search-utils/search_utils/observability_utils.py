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

import abc
import enum
import logging
from typing import List

import prometheus_client
from elasticsearch import AsyncElasticsearch, Elasticsearch
from opensearchpy import AsyncOpenSearch
from opensearchpy.client import OpenSearch

from search_utils import log_utils as lu

logger = logging.getLogger(__name__)


class QueryType(enum.Enum):
    elastiknn_exact = "elastiknn_exact"
    elastiknn_lsh = "elastiknn_lsh"
    opensearch_approximate_knn = "opensearch_approximate_knn"
    opensearch_exact_knn = "opensearch_exact_knn"
    unknown = "unknown"


def get_query_type(search_method: str, es_client) -> QueryType:
    """
    Determine query type to be reported in metrics based
    """
    if search_method == "exact":
        if isinstance(es_client, OpenSearch) or isinstance(es_client, AsyncOpenSearch):
            return QueryType.opensearch_exact_knn
        elif isinstance(es_client, Elasticsearch) or isinstance(es_client, AsyncElasticsearch):
            return QueryType.elastiknn_exact
    elif search_method == "lsh" or search_method == "approximate":
        if isinstance(es_client, OpenSearch) or isinstance(es_client, AsyncOpenSearch):
            return QueryType.opensearch_approximate_knn
        elif isinstance(es_client, Elasticsearch) or isinstance(es_client, AsyncElasticsearch):
            return QueryType.elastiknn_lsh
    return QueryType.unknown


class SearchObservabilityHandlerBase(abc.ABC):
    @abc.abstractmethod
    def observe_query(
        self,
        query_type: QueryType,
        query_size: int,
        result_size: int,
        backend_duration_seconds: float,
        total_duration_seconds: float,
        scroll: bool,
    ):
        pass


class PrometheusSearchObservabilityHandler(SearchObservabilityHandlerBase):
    def __init__(self, common_labels: dict = None):
        self.common_labels = {} if common_labels is None else common_labels
        common_labels_keys = list(self.common_labels.keys())
        size_buckets = (
            1.0,
            2.0,
            4.0,
            8.0,
            16.0,
            32.0,
            64.0,
            128.0,
            256.0,
            512.0,
            1024.0,
            2048.0,
            4096.0,
            8192.0,
            float("inf"),
        )
        label_keys = ["query_type"]
        namespace = "omningsearch"
        self.backend_query_duration = prometheus_client.Histogram(
            "backend_query_duration_seconds",
            "Query duration (backend side)",
            common_labels_keys + label_keys,
            namespace=namespace,
        )
        self.total_query_duration = prometheus_client.Histogram(
            "total_query_duration_seconds",
            "Total query duration as seen from the ngsearch service",
            common_labels_keys + label_keys,
            namespace=namespace,
        )
        self.query_size = prometheus_client.Histogram(
            "query_size",
            "Requested query size",
            common_labels_keys + label_keys,
            namespace=namespace,
            buckets=size_buckets,
        )
        self.result_size = prometheus_client.Histogram(
            "result_size",
            "Size of the returned results set",
            common_labels_keys + label_keys,
            namespace=namespace,
            buckets=size_buckets,
        )

    def observe_query(
        self,
        query_type: QueryType,
        query_size: int,
        result_size: int,
        backend_duration_seconds: float,
        total_duration_seconds: float,
        scroll: bool,
    ) -> None:
        self.backend_query_duration.labels(**self.common_labels, query_type=query_type.value).observe(
            backend_duration_seconds
        )
        self.total_query_duration.labels(**self.common_labels, query_type=query_type.value).observe(
            total_duration_seconds
        )
        self.query_size.labels(**self.common_labels, query_type=query_type.value).observe(query_size)
        self.result_size.labels(**self.common_labels, query_type=query_type.value).observe(result_size)


class LoggingSearchObservabilityHandler(SearchObservabilityHandlerBase):
    def __init__(self):
        pass

    def observe_query(
        self,
        query_type: QueryType,
        query_size: int,
        result_size: int,
        backend_duration_seconds: float,
        total_duration_seconds: float,
        scroll: bool = False,
    ) -> None:
        logger.info(
            f"Search query (type: {query_type.value}, scroll: {scroll}, size: {query_size}, result_size: {result_size}) took: {backend_duration_seconds * 1000:.1f}ms (backend), {total_duration_seconds * 1000:.1f}ms (total)"
        )


class SearchBackendObservability:
    def __init__(self, handlers: List[SearchObservabilityHandlerBase] = None):
        if not handlers:
            handlers = []
        self.handlers = handlers

    def observe_query(
        self,
        query_type: QueryType,
        query_size: int,
        result_size: int,
        backend_duration_seconds: float,
        total_duration_seconds: float,
        scroll: bool = False,
    ) -> None:
        for handler in self.handlers:
            handler.observe_query(
                query_type,
                int(query_size),
                int(result_size),
                backend_duration_seconds,
                total_duration_seconds,
                scroll,
            )
