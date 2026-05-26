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
import json
import logging
import re
import shlex
import time
from copy import deepcopy
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

import numpy as np
from deepsearch_api.search_backend.embeddings import (
    BaseEmbeddingInterface,
    EmbeddingType,
)
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    FieldConfig,
    FieldScoreConfig,
    ScoreExplanation,
    ScoringConfig,
    SearchResponse,
    SearchResult,
    SearchResultMetadata,
    SearchType,
    TextMatchType,
    VectorFieldConfig,
    VectorScore,
)
from deepsearch_api.search_backend.response_models import (
    KeyValuePair,
    StatsResponse,
    UniqueKey,
    UniqueValue,
)
from deepsearch_api.search_backend.utils import (
    extract_embeddings_from_hit,
    parse_arg_input_and_or,
)
from fastapi import HTTPException
from opensearchpy import AsyncOpenSearch
from opentelemetry import trace
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import OPENSEARCH_MAX_RESULT_WINDOW
from .exceptions import ImageProcessingError, ScoringConfigQueryMismatchError
from .models import VectorQueryScoreType
from .utils import OrjsonSerializer

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Constant for vision metadata fields expansion in hybrid search
VISION_METADATA_FIELDS_PLACEHOLDER = "__VISION_METADATA_FIELDS__"


class SearchBackendMappingCache:
    """Cache for search backend mapping."""

    def __init__(self):
        self.search_index_mapping_cache: Dict[str, Dict[str, Any]] = {}

    def get_search_index_mapping(self, index_name: str) -> Optional[Dict[str, Any]]:
        """Get search index mapping from cache or fetch from backend."""
        return self.search_index_mapping_cache[index_name]

    def set_search_index_mapping(self, index_name: str, mapping: Dict[str, Any]):
        self.search_index_mapping_cache[index_name] = mapping

    def has_usd_properties_field(self, index_name: str) -> bool:
        """Check if the index has the usd_properties field."""
        return self.search_index_mapping_cache[index_name]["mappings"]["properties"].get("usd_properties") is not None


search_index_mapping_cache = SearchBackendMappingCache()


class SearchSettings(BaseSettings):
    vector_query_score_type: VectorQueryScoreType = Field(
        default=VectorQueryScoreType.SCRIPT_SCORE,
        description="Type of score to use for vector queries",
    )
    opensearch_host: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    opensearch_index_name: str = "my-usdsearch-instance-index-ver5.0"
    opensearch_image_cache_index_name: str = "my-usdsearch-instance-index-ver4.0-image-cache"
    opensearch_use_ssl: bool = False
    opensearch_verify_certs: bool = True
    opensearch_timeout: int = 60  # seconds

    enable_aggregations: bool = True


class SearchFilterConfig(BaseSettings):
    fields_config: Dict[str, FieldConfig] = Field(default_factory=dict)

    model_config = SettingsConfigDict(env_prefix="search_filter_config_")


class SearchBackendClientV2:

    # Core document identity and display fields — always fetched.
    # base_key is the only field read by internal code;
    _BASE_SOURCE_FIELDS: List[str] = ["base_key", "path", "name", "ext"]

    # Fields only needed when return_metadata=True.
    # In compat.py these are read exclusively to build the Metadata object,
    # which is then gated by `if search_request.return_metadata`.
    _METADATA_SOURCE_FIELDS: List[str] = [
        "created_timestamp",
        "created_by",
        "modified_timestamp",
        "modified_by",
        "size",
        "etag",
        "ext",
        "pathType",
        "empty",
        "path",
        "name",
        "on_mount",
        "hash_value",
        "hash_type",
    ]

    def __init__(
        self,
        settings: SearchSettings,
        embedding_clients: Dict[EmbeddingType, BaseEmbeddingInterface],
        search_filter_config: Optional[SearchFilterConfig] = None,
    ):
        logger.info(
            "Initializing SearchBackendClientV2 with settings:\n %s",
            json.dumps(settings.model_dump(exclude={"opensearch_password"}), indent=2),
        )
        with tracer.start_as_current_span("search_backend.create_opensearch_client"):
            self.client = AsyncOpenSearch(
                hosts=[settings.opensearch_host],
                http_auth=(
                    (settings.opensearch_username, settings.opensearch_password)
                    if settings.opensearch_username and settings.opensearch_password
                    else None
                ),
                timeout=settings.opensearch_timeout,
                use_ssl=settings.opensearch_use_ssl,
                verify_certs=settings.opensearch_verify_certs,
                serializer=OrjsonSerializer(),
            )
        self._vector_query_score_type = settings.vector_query_score_type
        self.index_name = settings.opensearch_index_name
        self.text_to_vector_model = None  # Initialize text-to-vector model when needed
        self.explain = False
        self.embedding_clients: dict[EmbeddingType, BaseEmbeddingInterface] = embedding_clients
        if EmbeddingType.SIGLIP2_EMBEDDING not in embedding_clients:
            raise ValueError("Siglip2 embedding client is required for SearchBackendClientV2")

        # Vision metadata configuration
        self.vision_generated_dynamic_templates_suffix = "vlm_generated"

        # Cache for vision metadata fields with TTL
        self._vision_metadata_fields_cache = None
        self._vision_metadata_fields_cache_timestamp = 0
        self._vision_metadata_fields_cache_ttl = 300  # 5 minutes TTL

        if search_filter_config is None:
            self.search_filter_config = SearchFilterConfig()
        else:
            self.search_filter_config = search_filter_config

    async def __aenter__(self):
        with tracer.start_as_current_span("search_backend.verify_search_index_mappings"):
            await self.verify_search_index_mappings()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self.client.close()

    async def verify_search_index_mappings(self):
        try:
            has_usd_properties_field = search_index_mapping_cache.has_usd_properties_field(self.index_name)
        except KeyError:
            mapping = await self.client.indices.get_mapping(index=self.index_name)
            search_index_mapping_cache.set_search_index_mapping(self.index_name, mapping[self.index_name])
            has_usd_properties_field = search_index_mapping_cache.has_usd_properties_field(self.index_name)

        if not has_usd_properties_field:
            # Add usd_properties field to the mapping
            await self.client.indices.put_mapping(
                index=self.index_name,
                body={
                    "properties": {
                        "usd_properties": {
                            "type": "nested",
                        }
                    }
                },
            )
            mapping = await self.client.indices.get_mapping(index=self.index_name)
            search_index_mapping_cache.set_search_index_mapping(self.index_name, mapping[self.index_name])
            logger.info(f"usd_properties field added to the mapping for index {self.index_name}")
        else:
            logger.info(f"usd_properties field already exists in the mapping for index {self.index_name}")

    async def _get_text_embeddings(self, text: str, field_config: VectorFieldConfig | None = None) -> List[float]:
        """Get vector embeddings for text input."""
        with tracer.start_as_current_span("search_backend.text_embeddings") as span:
            span.set_attribute("embedding.text", text[:256])
            span.set_attribute("embedding.type", "text")
            return await self.embedding_clients[EmbeddingType.SIGLIP2_EMBEDDING].get_text_embeddings(text, field_config)

    async def _get_image_embeddings(
        self, images: List[str], field_config: VectorFieldConfig | None = None
    ) -> List[List[float]]:
        """Get vector embeddings for images. Returns one embedding per image."""
        with tracer.start_as_current_span("search_backend.image_embeddings") as span:
            span.set_attribute("embedding.image_count", len(images))
            span.set_attribute("embedding.type", "image")
            try:
                return await self.embedding_clients[EmbeddingType.SIGLIP2_EMBEDDING].get_image_embeddings(
                    images, field_config
                )
            except OSError as e:
                logger.error(f"Failed to get image embeddings: {e}")
                raise ImageProcessingError(f"Failed to get image embeddings: {e}") from e

    async def _build_hybrid_text_query(self, query: str, config: ScoringConfig) -> Dict[str, Any]:
        """Build a query that searches across multiple fields with separate match queries."""

        # Expand vision metadata fields if placeholder is found
        expanded_fields = []
        for field_config in config.hybrid_text.fields:
            if field_config.field == VISION_METADATA_FIELDS_PLACEHOLDER:
                # Get discovered vision metadata fields and expand them
                vision_fields = await self._get_vision_metadata_fields()
                if not vision_fields:
                    logging.warning(
                        "Vision metadata fields placeholder used but no vision metadata fields found in the index. Skipping vision metadata fields."
                    )
                    continue
                for vision_field in vision_fields:
                    # Add nested queries for vision metadata fields
                    for subfield in ["name", "name_sayt", "value_text", "value_sayt"]:
                        expanded_field_config = FieldScoreConfig(
                            field=f"{vision_field}.{subfield}",
                            enabled=field_config.enabled,
                            weight=field_config.weight,
                            match_type=field_config.match_type,
                            fuzzy_max_expansions=field_config.fuzzy_max_expansions,
                            nested=True,  # Vision metadata fields are nested
                            wildcard=field_config.wildcard,
                            match=field_config.match,
                        )
                        expanded_fields.append(expanded_field_config)
            else:
                expanded_fields.append(field_config)

        # Separate nested and non-nested fields
        nested_fields = {}
        regular_fields = []

        for field_config in expanded_fields:
            if not field_config.enabled:
                continue

            field = field_config.field
            # if "." in field:
            if field_config.nested:  # We configure it explicitly to support multi-fields such as path.tree
                # Extract the path (everything before the last dot)
                path = ".".join(field.split(".")[:-1])
                if path not in nested_fields:
                    nested_fields[path] = []
                nested_fields[path].append(field_config)
            else:
                regular_fields.append(field_config)

        queries = []

        # Add individual match queries for regular fields
        field_config: FieldScoreConfig
        for field_config in regular_fields:
            if field_config.match:
                match_query = {
                    "match": {
                        field_config.field: {
                            "query": query,
                            "_name": f"{field_config.field}_field",
                            "operator": config.hybrid_text.cross_field_operator,
                            "boost": field_config.weight,
                        }
                    }
                }
                if field_config.analyzer:
                    match_query["match"][field_config.field]["analyzer"] = field_config.analyzer

                # Add fuzzy matching parameters if configured
                if field_config.match_type == TextMatchType.FUZZY:
                    match_query["match"][field_config.field]["fuzziness"] = "AUTO"
                    if field_config.fuzzy_max_expansions:
                        match_query["match"][field_config.field]["max_expansions"] = field_config.fuzzy_max_expansions

                queries.append(match_query)

            if field_config.wildcard:
                wildcard_query = {
                    "wildcard": {
                        field_config.field: {
                            "value": f"*{query}*",
                            "_name": f"{field_config.field}_field",
                            "boost": field_config.weight,
                            "case_insensitive": field_config.case_insensitive,
                        }
                    }
                }
                queries.append(wildcard_query)

        # Add match queries for nested fields at root level
        for path, field_configs in nested_fields.items():
            for field_config in field_configs:
                match_query = {
                    "match": {
                        field_config.field: {
                            "query": query,
                            "_name": f"{field_config.field}_field",
                            "operator": config.hybrid_text.cross_field_operator,
                            "boost": field_config.weight,
                        }
                    }
                }

                if field_config.analyzer:
                    match_query["match"][field_config.field]["analyzer"] = field_config.analyzer

                # Add fuzzy matching parameters if configured
                if field_config.match_type == TextMatchType.FUZZY:
                    match_query["match"][field_config.field]["fuzziness"] = "AUTO"
                    if field_config.fuzzy_max_expansions:
                        match_query["match"][field_config.field]["max_expansions"] = field_config.fuzzy_max_expansions

                # Wrap the match query in a nested query
                nested_query = {
                    "nested": {
                        "path": path,
                        "query": match_query,
                        "_name": f"{field_config.field}_field",  # Move _name to root level
                    }
                }
                queries.append(nested_query)
                # TODO: Add wildcard support for nested fields

        # If there's only one query, return it directly
        if len(queries) == 1:
            return queries[0]

        # If there are multiple queries, combine them with a bool should
        return {"bool": {"should": queries}}

    def _create_score_explanation(
        self,
        hit: dict,
        search_type: SearchType,
        field: str,
        scoring_config: ScoringConfig,
        rrf_score: float,
        rrf_rank_constant: int,
    ) -> ScoreExplanation:
        """Create a detailed score explanation for a search result."""
        explanation = ScoreExplanation(
            search_type=search_type,
            score=hit["_score"],
            field=field,
            details=hit.get("_explanation", None),
            rrf_score=rrf_score,
            rrf_rank_constant=rrf_rank_constant,
        )

        if search_type in [SearchType.TEXT, SearchType.HYBRID]:
            explanation.matched_terms = hit.get("matched_queries", None)

        if search_type in [SearchType.TEXT_TO_VECTOR, SearchType.IMAGE_SIMILARITY]:
            explanation.vector_similarity = hit.get("inner_hits").get("siglip2-embedding").get("hits").get("max_score")

            for vector_hit in hit.get("inner_hits").get("siglip2-embedding").get("hits").get("hits"):
                if explanation.matched_vectors is None:
                    explanation.matched_vectors = []

                # Extract additional fields from the vector hit source
                vector_source = vector_hit.get("_source", {})
                image = vector_source.get("image")
                keyword = vector_source.get("keyword")
                label = vector_source.get("label")

                explanation.matched_vectors.append(
                    VectorScore(
                        offset=vector_hit["_nested"]["offset"],
                        score=vector_hit["_score"],
                        field=vector_hit["_nested"]["field"],
                        image=image,
                        keyword=keyword,
                        label=label,
                    )
                )

        if search_type in [SearchType.VECTOR]:
            for inner_hit in hit.get("inner_hits").values():
                explanation.vector_similarity = inner_hit.get("hits").get("max_score")
                for hit in inner_hit.values():

                    for vector_hit in hit.get("hits"):
                        if explanation.matched_vectors is None:
                            explanation.matched_vectors = []

                        # Extract additional fields from the vector hit source
                        vector_source = vector_hit.get("_source", {})
                        image = vector_source.get("image")
                        keyword = vector_source.get("keyword")
                        label = vector_source.get("label")

                        explanation.matched_vectors.append(
                            VectorScore(
                                offset=vector_hit["_nested"]["offset"],
                                score=vector_hit["_score"],
                                field=vector_hit["_nested"]["field"],
                                image=image,
                                keyword=keyword,
                                label=label,
                            )
                        )

        return explanation

    def _apply_similarity_threshold_filtering(
        self, sorted_docs: List[tuple], search_request: DeepSearchSearchRequestV2
    ) -> List[tuple]:
        """Apply similarity threshold filtering to remove duplicate assets based on embedding similarity."""
        if search_request.similarity_threshold is None or not (
            search_request.description or search_request.image_similarity_search or search_request.vector_queries
        ):
            return sorted_docs

        threshold = search_request.similarity_threshold
        filtered_docs = []

        for doc_id, doc_info in sorted_docs:
            is_duplicate = False
            current_embeddings = extract_embeddings_from_hit(doc_info["hit"])

            if current_embeddings is None:
                # If we can't extract embeddings, include the document
                filtered_docs.append((doc_id, doc_info))
                continue

            # Check against all previously accepted documents
            for existing_doc_id, existing_doc_info in filtered_docs:
                existing_embeddings = extract_embeddings_from_hit(existing_doc_info["hit"])

                if existing_embeddings is None:
                    continue

                # Calculate cosine distance between embeddings
                cosine_distance = self._calculate_cosine_distance(current_embeddings, existing_embeddings)

                if cosine_distance < threshold:
                    is_duplicate = True
                    logger.debug(f"Filtering duplicate asset {doc_id} (distance: {cosine_distance:.4f} < {threshold})")
                    break

            if not is_duplicate:
                filtered_docs.append((doc_id, doc_info))

        logger.debug(f"Similarity threshold filtering: {len(sorted_docs)} -> {len(filtered_docs)} documents")
        return filtered_docs

    def _calculate_cosine_distance(self, embedding1: List[float], embedding2: List[float]) -> float:
        """Calculate cosine distance between two embeddings."""
        try:
            # Convert to numpy arrays for efficient computation
            vec1 = np.array(embedding1, dtype=np.float32)
            vec2 = np.array(embedding2, dtype=np.float32)

            # Calculate cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 2.0  # Maximum distance for zero vectors

            cosine_similarity = dot_product / (norm1 * norm2)
            # Cosine distance = 1 - cosine_similarity
            # But since cosine similarity can be in [-1, 1], distance is in [0, 2]
            cosine_distance = 1.0 - cosine_similarity

            return float(cosine_distance)
        except Exception as e:
            logger.warning(f"Failed to calculate cosine distance: {e}")
            return 2.0  # Return maximum distance on error

    def _get_explanations(
        self,
        hit: Any,
        search_type: SearchType,
        scoring_config: ScoringConfig,
        rrf_score: float,
        rank_constant: int,
        query_name: str,
    ) -> list[ScoreExplanation]:
        """Process and format search results with detailed scoring explanations."""
        explanations = []

        # Create score explanations for each active search type
        if search_type == SearchType.TEXT:
            explanations.append(
                self._create_score_explanation(
                    hit,
                    SearchType.TEXT,
                    query_name,
                    scoring_config,
                    rrf_score,
                    rank_constant,
                )
            )

        if search_type == SearchType.HYBRID:
            explanations.append(
                self._create_score_explanation(
                    hit,
                    SearchType.HYBRID,
                    query_name,
                    scoring_config,
                    rrf_score,
                    rank_constant,
                )
            )

        if search_type in [SearchType.IMAGE_SIMILARITY, SearchType.TEXT_TO_VECTOR]:
            explanations.append(
                self._create_score_explanation(
                    hit,
                    search_type,
                    query_name,
                    scoring_config,
                    rrf_score,
                    rank_constant,
                )
            )

        if search_type == SearchType.VECTOR:
            explanations.append(
                self._create_score_explanation(
                    hit,
                    SearchType.VECTOR,
                    query_name,
                    scoring_config,
                    rrf_score,
                    rank_constant,
                )
            )

        return explanations

    async def _filter_source(self, source: Dict[str, Any], search_request: DeepSearchSearchRequestV2) -> Dict[str, Any]:
        """Filter source fields based on search request parameters."""
        filtered = source.copy()

        if not (search_request.return_images or search_request.return_predictions):
            filtered.pop("siglip2-embedding", None)
        if not search_request.return_metadata:
            filtered.pop("metadata", None)
        if not search_request.return_predictions:
            filtered.pop("predictions", None)
        if not search_request.return_vision_generated_metadata:
            # TODO: Migrate vision_generated metadata to nested fields
            for vision_key in [key for key in source.keys() if key.startswith("vision_generated_")]:
                filtered.pop(vision_key)
            for plugin_key in await self._get_vision_metadata_fields():
                filtered.pop(plugin_key, None)
        if not search_request.return_tags:
            filtered.pop("tags", None)
        if not search_request.return_usd_properties:
            filtered.pop("usd_properties", None)
        if not search_request.return_usd_dimensions:
            filtered.pop("usd_dimensions", None)
        if not search_request.return_inner_hits:
            filtered.pop("inner_hits", None)

        return filtered

    def _is_vector_search(self, query_name: str) -> bool:
        """Check if a query is vector-based (embedding/similarity search)."""
        vector_search_types = [
            SearchType.TEXT_TO_VECTOR,
            SearchType.IMAGE_SIMILARITY,
            SearchType.VECTOR,
        ]

        # Check for exact matches with SearchType enum values
        if query_name in vector_search_types:
            return True

        # Check for vector query names that start with "vector_"
        if isinstance(query_name, str) and query_name.startswith("vector"):
            return True

        return False

    def _add_collapse_for_deduplication(
        self, query_body: Dict[str, Any], search_request: DeepSearchSearchRequestV2
    ) -> Dict[str, Any]:
        """Add OpenSearch collapse functionality to deduplicate by hash_value."""
        if search_request.deduplicate_by_hash:
            query_body["collapse"] = {"field": "hash_value"}
        return query_body

    async def search(
        self,
        search_request: DeepSearchSearchRequestV2,
        from_: int = 0,
        url_whitelist: Optional[List[str]] = None,
    ) -> SearchResponse:
        logger.debug(
            "Performing search with request:\n%s",
            search_request.model_dump_json(indent=2),
        )

        size = search_request.limit

        scoring_config = search_request.scoring_config
        rrf_config = scoring_config.rrf_config
        # cap the window size to 10000 to avoid OpenSearch max_result_window limit
        window_size = min(rrf_config.window_size or (from_ + size) * 2, OPENSEARCH_MAX_RESULT_WINDOW)

        # Store individual search results
        all_results = []
        bool_filters = await self._create_bool_filters(search_request)
        source_includes = self._build_source_includes(search_request)

        # Add URL whitelist filter if provided
        if url_whitelist:
            url_filter = {"terms": {"base_key": url_whitelist}}
            if bool_filters:
                bool_filters.append(url_filter)
            else:
                bool_filters = [url_filter]

        # If we only have filters, execute a match_all query with filters
        if not any(
            [
                search_request.description,
                search_request.hybrid_text_query,
                search_request.image_similarity_search,
                search_request.vector_queries,
            ]
        ):
            query = {
                "_source": source_includes,
                "query": {
                    "bool": (
                        {"must": [{"match_all": {}}], "filter": bool_filters}
                        if bool_filters
                        else {"must": {"match_all": {}}}
                    )
                },
            }

            # Add collapse for deduplication if requested
            query = self._add_collapse_for_deduplication(query, search_request)

            logger.debug(
                "Executing filter-only search with query:\n%s",
                json.dumps(query, indent=2),
            )
            with tracer.start_as_current_span("search_backend.opensearch_query") as span:
                span.set_attribute("query.type", "filter_only")
                span.set_attribute("query.window_size", window_size)
                response = await self.client.search(
                    index=self.index_name,
                    body=query,
                    size=window_size,
                    explain=self.explain,
                    track_total_hits=True,
                )
                span.set_attribute("query.took_ms", response.get("took", 0))
                span.set_attribute(
                    "query.total_hits",
                    response.get("hits", {}).get("total", {}).get("value", 0),
                )
            all_results.append((SearchType.FILTER_ONLY, response))

        else:
            # Parallelize all search queries
            search_tasks = []

            # Prepare hybrid text search if enabled
            if search_request.hybrid_text_query and scoring_config.hybrid_text.enabled:
                with tracer.start_as_current_span("search_backend.build_hybrid_text_query") as span:
                    hybrid_query = {
                        "query": await self._build_hybrid_text_query(search_request.hybrid_text_query, scoring_config)
                    }

                if bool_filters:
                    hybrid_query["query"] = {
                        "bool": {
                            "must": [hybrid_query["query"]],
                            "filter": bool_filters,
                        }
                    }

                # Add collapse for deduplication if requested
                hybrid_query = self._add_collapse_for_deduplication(hybrid_query, search_request)
                hybrid_query["_source"] = source_includes

                logger.debug(
                    "Preparing hybrid text search with query:\n%s",
                    json.dumps(hybrid_query, indent=2),
                )

                async def execute_hybrid_search():
                    with tracer.start_as_current_span("search_backend.opensearch_query") as span:
                        span.set_attribute("query.type", "hybrid_text")
                        span.set_attribute("query.window_size", window_size)
                        response = await self.client.search(
                            index=self.index_name,
                            body=hybrid_query,
                            size=window_size,
                            explain=self.explain,
                            track_total_hits=True,
                        )
                        span.set_attribute("query.took_ms", response.get("took", 0))
                        span.set_attribute(
                            "query.total_hits",
                            response.get("hits", {}).get("total", {}).get("value", 0),
                        )
                    return (SearchType.HYBRID, response)

                search_tasks.append(asyncio.create_task(execute_hybrid_search()))

            # Prepare all vector searches
            with tracer.start_as_current_span("search_backend.build_vector_queries") as span:
                vector_queries = await self._build_vector_queries(search_request, window_size)
            for idx, vector_query in enumerate(vector_queries):
                query = {"query": vector_query}

                if bool_filters:
                    query["query"] = {"bool": {"must": [query["query"]], "filter": bool_filters}}

                # Add collapse for deduplication if requested
                query = self._add_collapse_for_deduplication(query, search_request)
                query["_source"] = source_includes

                logger.debug(
                    "Preparing vector search %d with query:\n%s",
                    idx,
                    json.dumps(query, indent=2),
                )

                query_name = f"vector_{idx}"
                if "description" in vector_query.get("nested", {}).get("_name", ""):
                    query_name = SearchType.TEXT_TO_VECTOR
                elif "image" in vector_query.get("nested", {}).get("_name", ""):
                    query_name = SearchType.IMAGE_SIMILARITY

                async def execute_vector_search(query_body=query, vector_idx=idx, search_name=query_name):
                    with tracer.start_as_current_span("search_backend.opensearch_query") as span:
                        span.set_attribute("query.type", "vector")
                        span.set_attribute("query.vector_index", vector_idx)
                        span.set_attribute("query.window_size", window_size)
                        response = await self.client.search(
                            index=self.index_name,
                            body=query_body,
                            size=window_size,
                            explain=self.explain,
                        )
                        span.set_attribute("query.took_ms", response.get("took", 0))
                        span.set_attribute(
                            "query.total_hits",
                            response.get("hits", {}).get("total", {}).get("value", 0),
                        )
                    return (search_name, response)

                search_tasks.append(asyncio.create_task(execute_vector_search()))

            # Execute all search tasks in parallel
            if search_tasks:
                logger.debug("Executing %d search queries in parallel", len(search_tasks))
                search_results = await asyncio.gather(*search_tasks)
                all_results.extend(search_results)

        # Process results and implement client-side RRF
        document_scores = {}

        # Calculate RRF scores for each document
        with tracer.start_as_current_span("search_backend.calculate_rrf_scores") as span:
            for query_name, response in all_results:
                rank_constant = rrf_config.query_rank_constants.get(query_name, rrf_config.rank_constant)

                # Get the weight for this query type
                query_weight = 1.0  # default weight
                if query_name == SearchType.HYBRID:
                    query_weight = scoring_config.hybrid_text.weight
                elif query_name == SearchType.VECTOR or (
                    isinstance(query_name, str) and query_name.startswith("vector")
                ):
                    # For vector queries, get the weight from the specific vector field config
                    if isinstance(query_name, str) and query_name.startswith("vector_"):
                        field_name = query_name.replace("vector_", "")
                        vector_config = scoring_config.vector_fields.get(field_name)
                        if vector_config:
                            query_weight = vector_config.weight
                    else:
                        # Use default vector weight from first configured vector field if available
                        if scoring_config.vector_fields:
                            first_vector_config = next(iter(scoring_config.vector_fields.values()))
                            query_weight = first_vector_config.weight

                for rank, hit in enumerate(response["hits"]["hits"], 1):
                    doc_id = hit["_id"]
                    hit_score = hit["_score"]

                    # Apply cutoff threshold for vector-based searches
                    if search_request.cutoff_threshold is not None and self._is_vector_search(query_name):
                        if hit_score < search_request.cutoff_threshold:
                            continue  # Skip this result as it doesn't meet the minimum similarity threshold

                    rrf_score = 1 / (rank + rank_constant)
                    weighted_rrf_score = rrf_score * query_weight

                    if doc_id not in document_scores:
                        document_scores[doc_id] = {
                            "hit": hit,
                            "rrf_score": 0,
                            "original_ranks": {},
                        }

                    document_scores[doc_id]["rrf_score"] += weighted_rrf_score
                    document_scores[doc_id]["original_ranks"][query_name] = rank
                    if "original_scores" not in document_scores[doc_id]:
                        document_scores[doc_id]["original_scores"] = []
                    if "explanations" not in document_scores[doc_id]:
                        document_scores[doc_id]["explanations"] = []
                    query_type = SearchType.VECTOR if query_name.startswith("vector") else query_name
                    document_scores[doc_id]["explanations"].extend(
                        self._get_explanations(
                            hit,
                            query_type,
                            scoring_config,
                            weighted_rrf_score,
                            rank_constant,
                            query_name,
                        )
                    )
                    document_scores[doc_id]["original_scores"].append(hit_score)

        # Sort documents by RRF score
        sorted_docs = sorted(document_scores.items(), key=lambda x: x[1]["rrf_score"], reverse=True)

        # Apply similarity threshold filtering for embedding-based searches
        filtered_docs = self._apply_similarity_threshold_filtering(sorted_docs, search_request)

        # Apply pagination and prepare final results
        total_hits = len(filtered_docs)
        # Lower-bound estimate of corpus matches: max of per-leg OpenSearch total_hits.
        # Each leg applies the same bool_filters, so max(legs) <= true union <= sum(legs).
        # Note: OpenSearch defaults to track_total_hits=10000, so this saturates at 10000
        # for large corpora unless track_total_hits is overridden upstream.
        corpus_total = max(
            (r.get("hits", {}).get("total", {}).get("value", 0) for _, r in all_results),
            default=0,
        )
        paginated_docs = filtered_docs[from_ : from_ + size]
        final_hits = []

        for doc_id, doc_info in paginated_docs:
            hit = doc_info["hit"]
            # Filter source fields according to user preferences
            filtered_source = await self._filter_source(hit["_source"], search_request)

            if search_request.return_images:
                thumbnail_exists = (
                    True
                    if "siglip2-embedding" in filtered_source and len(filtered_source["siglip2-embedding"]) > 0
                    else False
                )
            else:
                thumbnail_exists = None

            # Remove siglip2-embedding if not requested by user (but was kept for similarity filtering)
            if not search_request.return_predictions and "siglip2-embedding" in filtered_source:
                filtered_source.pop("siglip2-embedding", None)

            result = SearchResult.model_construct(
                id=hit["_id"],
                score=(
                    sum(doc_info["original_scores"]) if len(doc_info["original_scores"]) else 0
                ),  # TODO: TBD what to return in such case
                rrf_score=doc_info["rrf_score"],
                metadata=SearchResultMetadata.model_construct(
                    explanations=doc_info["explanations"],
                    rrf_rank=len(final_hits) + 1,
                    original_ranks=doc_info["original_ranks"],
                ),
                source=filtered_source,
                inner_hits=(hit.get("inner_hits", {}) if search_request.return_inner_hits else {}),
                thumbnail_exists=thumbnail_exists,
            )
            final_hits.append(result)

        search_response = SearchResponse.model_construct(
            total=total_hits,
            corpus_total=corpus_total,
            hits=final_hits,
            search_metadata={
                "took": sum(r["took"] for _, r in all_results),
                "max_score": max((h.score for h in final_hits), default=0),
            },
        )
        logger.debug(
            "SearchBackendClientV2 response:\n%s",
            search_response.model_dump_json(indent=2),
        )
        return search_response

    async def _build_vector_queries(
        self, search_request: DeepSearchSearchRequestV2, window_size: int
    ) -> List[Dict[str, Any]]:
        """Build vector similarity queries for all requested vector fields."""
        vector_queries = []

        # Prepare image list upfront so we can run text + image embeddings concurrently
        processed_images = []
        if search_request.image_similarity_search:
            for img in search_request.image_similarity_search:
                if isinstance(img, str) and img.startswith(("s3://", "omniverse://")):
                    downloaded_img = search_request.get_downloaded_image(img)
                    if downloaded_img is not None:
                        processed_images.append(downloaded_img)
                    else:
                        logger.warning(f"No downloaded image data found for {img}, skipping")
                else:
                    processed_images.append(img)

        # Run text and image embedding requests concurrently
        text_embeddings_coro = (
            self._get_text_embeddings(search_request.description) if search_request.description else None
        )
        image_embeddings_coro = self._get_image_embeddings(processed_images) if processed_images else None

        if text_embeddings_coro and image_embeddings_coro:
            text_embeddings, all_image_embeddings = await asyncio.gather(text_embeddings_coro, image_embeddings_coro)
        elif text_embeddings_coro:
            text_embeddings = await text_embeddings_coro
            all_image_embeddings = None
        elif image_embeddings_coro:
            all_image_embeddings = await image_embeddings_coro
            text_embeddings = None
        else:
            text_embeddings = None
            all_image_embeddings = None

        if text_embeddings is not None:
            vector_queries.append(
                {
                    "nested": {
                        "path": "siglip2-embedding",
                        "score_mode": "max",
                        "inner_hits": {"_source": self.should_fetch_vector_inner_hits(search_request)},
                        "_name": "embedding_description",
                        "query": {
                            **self._build_knn_query(
                                vector_query_type=self._vector_query_score_type,
                                query_vector=text_embeddings,
                                embedding_field="siglip2-embedding.embedding",
                                space_type="innerproduct",
                                k=window_size,
                            )
                        },
                    }
                }
            )

        if all_image_embeddings is not None:
            for i, image_embedding in enumerate(all_image_embeddings):
                vector_queries.append(
                    {
                        "nested": {
                            "path": "siglip2-embedding",
                            "score_mode": "max",
                            "inner_hits": {"_source": self.should_fetch_vector_inner_hits(search_request)},
                            "_name": f"embedding_image_similarity_search_{i}",
                            "query": {
                                **self._build_knn_query(
                                    vector_query_type=self._vector_query_score_type,
                                    query_vector=image_embedding,
                                    embedding_field="siglip2-embedding.embedding",
                                    space_type="innerproduct",
                                    k=window_size,
                                )
                            },
                        }
                    }
                )

        # Process explicit vector queries
        for vector_query in search_request.vector_queries:
            field_config = search_request.scoring_config.vector_fields.get(vector_query.field_name)
            if not field_config:
                raise ScoringConfigQueryMismatchError(f"Field {vector_query.field_name} not found in scoring config")
            if not field_config.enabled:
                continue

            # Extract the base field name and the nested path
            field_parts = vector_query.field_name.split(".")
            nested_path = ".".join(field_parts[:-1]) if len(field_parts) > 1 else field_parts[0]
            embedding_field = f"{vector_query.field_name}"

            # Handle image queries with downloaded data
            if (
                vector_query.query_type == "image"
                and isinstance(vector_query.query, str)
                and vector_query.query.startswith(("s3://", "omniverse://"))
            ):
                downloaded_img = search_request.get_downloaded_image(vector_query.query)
                if downloaded_img is None:
                    logger.warning(f"No downloaded image data found for {vector_query.query}, skipping vector query")
                    continue
                query_vector = (await self._get_image_embeddings([downloaded_img], field_config))[0]
            else:
                query_vector = (
                    await self._get_text_embeddings(vector_query.query, field_config)
                    if vector_query.query_type == "text"
                    else (
                        (await self._get_image_embeddings([vector_query.query], field_config))[0]
                        if vector_query.query_type == "image"
                        else vector_query.query
                    )
                )

            vector_queries.append(
                {
                    "nested": {
                        "path": nested_path,
                        "score_mode": "max",
                        "inner_hits": {"_source": self.should_fetch_vector_inner_hits(search_request)},
                        "_name": f"embedding_{nested_path}",
                        "query": {
                            **self._build_knn_query(
                                vector_query_type=self._vector_query_score_type,
                                query_vector=query_vector,
                                embedding_field=embedding_field,
                                space_type="innerproduct",
                                k=window_size,
                            )
                        },
                    }
                }
            )

        return vector_queries

    def _build_knn_query(
        self,
        vector_query_type: VectorQueryScoreType,
        query_vector: List[float],
        embedding_field: str,
        space_type: str = "innerproduct",
        k: int = 10,
    ) -> Dict[str, Any]:
        """Build a KNN query for a field."""
        if vector_query_type == VectorQueryScoreType.SCRIPT_SCORE:
            return {
                "script_score": {
                    "query": {"match_all": {}},
                    "script": {
                        "source": "knn_score",
                        "lang": "knn",
                        "params": {
                            "field": embedding_field,
                            "query_value": query_vector,
                            "space_type": space_type,
                        },
                    },
                }
            }
        elif vector_query_type == VectorQueryScoreType.KNN:
            return {"knn": {embedding_field: {"vector": query_vector, "k": k}}}
        else:
            raise ValueError(f"Invalid vector query type: {vector_query_type}")

    def _build_source_includes(self, search_request: DeepSearchSearchRequestV2) -> Dict[str, Any]:
        """Build the OpenSearch _source inclusion filter for the main document.

        Only requests the fields that will actually be used, avoiding the transfer of
        heavy optional fields (embeddings, nested arrays) when they are not needed.
        """
        includes = list(self._BASE_SOURCE_FIELDS)

        # siglip2-embedding is needed for similarity deduplication, thumbnail existence
        # check, or when the caller wants predictions/images returned.
        if search_request.similarity_threshold or search_request.return_images or search_request.return_predictions:
            includes.append("siglip2-embedding")

        if search_request.return_predictions:
            includes.append("predictions")

        if search_request.return_metadata:
            includes.append("metadata")
            includes.extend(self._METADATA_SOURCE_FIELDS)

        if search_request.return_tags:
            includes.append("tags")

        # Wildcard patterns cover all dynamically-named vision/plugin fields.
        if search_request.return_vision_generated_metadata:
            includes.extend(["vision_generated_*", "plugin_*"])

        if (
            search_request.return_usd_properties
            or search_request.return_root_prims
            or search_request.return_default_prims
        ):
            includes.append("usd_properties")

        if (
            search_request.return_usd_dimensions
            or search_request.return_root_prims
            or search_request.return_default_prims
        ):
            includes.append("usd_dimensions")

        return {"includes": includes}

    def should_fetch_vector_inner_hits(self, search_request: DeepSearchSearchRequestV2) -> bool:
        """
        Determine if vector inner_hits should be FETCHED from OpenSearch.

        This is different from returning inner_hits in the API response.
        Inner hits must be fetched internally for:
        1. Image loading (to extract image IDs from siglip2-embedding results)
        2. Score explanations for vector searches
        3. Similarity threshold filtering (to extract embeddings)
        4. User explicitly requested them

        Note: Inner hits are only included in API response if user sets return_inner_hits=True
        """
        reasons = []

        # User explicitly requested inner_hits
        if search_request.return_inner_hits:
            reasons.append("user requested return_inner_hits=True")

        # Image loading requires inner_hits to extract image IDs
        if search_request.return_images:
            reasons.append("image loading requires inner_hits for image ID extraction")

        # Vector searches with score explanations need inner_hits
        has_vector_search = (
            search_request.description or search_request.image_similarity_search or search_request.vector_queries
        )
        if has_vector_search:
            reasons.append("vector searches need inner_hits for score explanations")

        # Similarity threshold filtering may benefit from inner_hits
        if search_request.similarity_threshold is not None:
            reasons.append("similarity threshold filtering may use inner_hits")

        should_return = len(reasons) > 0

        if should_return:
            logger.debug(f"Fetching inner_hits=True because: {', '.join(reasons)}")
        else:
            logger.debug("No inner_hits needed for fetching, returning False")

        return should_return

    async def _get_vision_metadata_fields(self) -> List[str]:
        """
        Discover and cache vision metadata fields from the index mapping.
        Returns list of field names matching plugin_*_metadata_{suffix} pattern.
        """
        current_time = time.time()

        # Check if cache is still valid
        if (
            self._vision_metadata_fields_cache is not None
            and current_time - self._vision_metadata_fields_cache_timestamp < self._vision_metadata_fields_cache_ttl
        ):
            return self._vision_metadata_fields_cache

        try:
            # Get the index mapping
            mapping_response = await self.client.indices.get_mapping(index=self.index_name)
            mapping = mapping_response[self.index_name]["mappings"]

            # Find all fields matching the pattern
            pattern_prefix = "plugin_"
            pattern_suffix = f"_metadata_{self.vision_generated_dynamic_templates_suffix}"

            vision_fields = [
                k
                for k in mapping.get("properties", {}).keys()
                if k.startswith(pattern_prefix) and k.endswith(pattern_suffix)
            ]

            # Update cache
            self._vision_metadata_fields_cache = vision_fields
            self._vision_metadata_fields_cache_timestamp = current_time

            logger.debug(f"Discovered {len(vision_fields)} vision metadata fields: {vision_fields}")
            return vision_fields

        except Exception as e:
            logger.error(f"Error discovering vision metadata fields: {e}")
            # Return empty list on error, don't cache
            return []

    def _create_bool_wildcard_filters_from_or_groups(
        self,
        or_groups: List[List[str]],
        field_name: str,
        **extra_wildcard_kwargs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Create boolean filters from OR groups of search request parameters."""
        filters = []
        for or_group in or_groups:
            or_filters = []
            for value in or_group:
                or_filters.append({"wildcard": {field_name: {"value": value, **extra_wildcard_kwargs}}})
            filters.append({"bool": {"should": or_filters, "minimum_should_match": 1}})
        return filters

    def _create_negative_bool_wildcard_filters_from_or_groups(
        self,
        or_groups: List[List[str]],
        field_name: str,
        **extra_wildcard_kwargs: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Create boolean filters from OR groups of search request parameters."""
        filters = []
        for or_group in or_groups:
            for value in or_group:
                filters.append(
                    {
                        "bool": {
                            "must_not": {
                                "wildcard": {
                                    field_name: {
                                        "value": value,
                                        **extra_wildcard_kwargs,
                                    }
                                }
                            }
                        }
                    }
                )
        return filters

    @staticmethod
    def _parse_usd_property_filters(properties_str: str) -> List[Dict[str, Any]]:
        """Parse a comma-separated USD properties string into nested OpenSearch filter clauses.

        Supports exact match (=) and wildcard match (=~) operators:
          k=v   exact key + exact value
          k=    key-only (exact)
          =v    value-only (exact)
          k=~v  wildcard key + wildcard value (case-insensitive)
          k=~   wildcard key-only (case-insensitive)
          =~v   wildcard value-only (case-insensitive)

        Values may be quoted to include literal commas, e.g. key="(v1,v2,v3)".
        """
        lexer = shlex.shlex(properties_str, posix=True)
        lexer.whitespace = ","
        lexer.whitespace_split = True
        parsed: List[Dict[str, Any]] = []
        for prop in lexer:
            if "=~" in prop:
                name, value = prop.split("=~", 1)
                use_wildcard = True
            elif "=" in prop:
                name, value = prop.split("=", 1)
                use_wildcard = False
            else:
                continue

            query_conditions: List[Dict[str, Any]] = []

            def _field_clause(field: str, val: str) -> Dict[str, Any]:
                if use_wildcard:
                    return {"wildcard": {field: {"value": val, "case_insensitive": True}}}
                return {"term": {field: val}}

            if name and not value:
                query_conditions.append(_field_clause("usd_properties.name", name))
            elif not name and value:
                query_conditions.append(_field_clause("usd_properties.value", value))
            elif name and value:
                query_conditions.append(_field_clause("usd_properties.name", name))
                query_conditions.append(_field_clause("usd_properties.value", value))

            if query_conditions:
                parsed.append(
                    {
                        "nested": {
                            "path": "usd_properties",
                            "query": {"bool": {"must": query_conditions}},
                        }
                    }
                )
        return parsed

    async def _create_bool_filters(self, search_request: DeepSearchSearchRequestV2) -> List[Dict[str, Any]]:
        """Generate boolean filters based on search request parameters."""
        filters = []

        # File name filters
        if search_request.file_name:
            filters.extend(
                self._create_bool_wildcard_filters_from_or_groups(
                    or_groups=parse_arg_input_and_or(search_request.file_name),
                    field_name="name",
                    case_insensitive=self.search_filter_config.fields_config.get(
                        "name", FieldConfig()
                    ).case_insensitive,
                )
            )
        if search_request.exclude_file_name:
            filters.extend(
                self._create_negative_bool_wildcard_filters_from_or_groups(
                    or_groups=parse_arg_input_and_or(search_request.exclude_file_name),
                    field_name="name",
                    case_insensitive=self.search_filter_config.fields_config.get(
                        "name", FieldConfig()
                    ).case_insensitive,
                )
            )

        # Extension filters
        if search_request.file_extension_include:
            filters.extend(
                self._create_bool_wildcard_filters_from_or_groups(
                    or_groups=parse_arg_input_and_or(search_request.file_extension_include),
                    field_name="ext",
                    case_insensitive=self.search_filter_config.fields_config.get("ext", FieldConfig()).case_insensitive,
                )
            )
        if search_request.file_extension_exclude:
            filters.extend(
                self._create_negative_bool_wildcard_filters_from_or_groups(
                    or_groups=parse_arg_input_and_or(search_request.file_extension_exclude),
                    field_name="ext",
                    case_insensitive=self.search_filter_config.fields_config.get("ext", FieldConfig()).case_insensitive,
                )
            )

        # Vision metadata filter
        if search_request.vision_metadata:
            vision_metadata_fields = await self._get_vision_metadata_fields()
            if not vision_metadata_fields:
                raise ValueError(
                    "Vision metadata queries are not supported: no vision metadata fields found in the index"
                )
            if vision_metadata_fields:
                vision_filters = []
                for prop in search_request.vision_metadata.split(","):
                    if "=" in prop:
                        name, value = prop.split("=", 1)
                    else:
                        name, value = None, prop

                    # Create queries for all discovered vision metadata fields
                    field_queries = []
                    for field_path in vision_metadata_fields:
                        query_conditions = []

                        # Key-only pattern: k=
                        if name and not value:
                            query_conditions.append({"match": {f"{field_path}.name": name}})
                        # Value-only pattern: =v
                        elif not name and value:
                            query_conditions.append(
                                {"match": {f"{field_path}.value_text": value}},
                            )
                        # Key-value pattern: k=v
                        elif name and value:
                            query_conditions.extend(
                                [
                                    {
                                        "bool": {
                                            "must": [
                                                {"match": {f"{field_path}.name": name}},
                                                {"match": {f"{field_path}.value_text": value}},
                                            ]
                                        }
                                    }
                                ]
                            )

                        if query_conditions:
                            field_queries.append(
                                {
                                    "nested": {
                                        "path": field_path,
                                        "query": {"bool": {"must": query_conditions}},
                                    }
                                }
                            )

                    if field_queries:
                        vision_filters.append({"bool": {"should": field_queries}})

                if vision_filters:
                    filters.append({"bool": {"must": vision_filters}})

        # Date filters
        date_filters = {
            "created_timestamp": {
                "gte": search_request.created_after,
                "lte": search_request.created_before,
            },
            "modified_timestamp": {
                "gte": search_request.modified_after,
                "lte": search_request.modified_before,
            },
        }

        for field, conditions in date_filters.items():
            if any(conditions.values()):
                range_filter = {field: {k: v for k, v in conditions.items() if v is not None}}
                filters.append({"range": range_filter})

        # Size filters
        if search_request.file_size_greater_than or search_request.file_size_less_than:
            size_filter = {"size": {}}
            if search_request.file_size_greater_than:
                size_filter["size"]["gte"] = self._convert_size_to_bytes(search_request.file_size_greater_than)
            if search_request.file_size_less_than:
                size_filter["size"]["lte"] = self._convert_size_to_bytes(search_request.file_size_less_than)
            filters.append({"range": size_filter})

        # Path filters
        if search_request.search_path:
            filters.append(
                {
                    "wildcard": {
                        "base_key": {
                            "value": f"*{search_request.search_path}*",
                            "case_insensitive": True,
                        }
                    }
                }
            )
        if search_request.exclude_search_path:
            filters.append(
                {
                    "bool": {
                        "must_not": {
                            "wildcard": {
                                "base_key": {
                                    "value": f"*{search_request.exclude_search_path}*",
                                    "case_insensitive": True,
                                }
                            }
                        }
                    }
                }
            )

        # User filters
        for field, value, exclude_value in [
            (
                "created_by",
                search_request.created_by,
                search_request.exclude_created_by,
            ),
            (
                "modified_by",
                search_request.modified_by,
                search_request.exclude_modified_by,
            ),
        ]:
            if value:
                filters.append({"term": {field: value}})
            if exclude_value:
                filters.append({"bool": {"must_not": {"term": {field: exclude_value}}}})

        # URL regexp filter — flags: ALL enables intersection (&) and other Lucene operators.
        # OpenSearch 3.x (Lucene 10) silently broke the ~ complement operator in regexp queries
        # (returns 0 hits instead of the complement set). Rewrite top-level ~(inner) as
        # bool.must_not + regexp(inner), which produces correct results on both 2.x and 3.x.
        if search_request.filter_url_regexp:
            complement_match = re.fullmatch(r"~\((.+)\)", search_request.filter_url_regexp)
            if complement_match:
                filters.append(
                    {
                        "bool": {
                            "must_not": {
                                "regexp": {
                                    "base_key": {
                                        "value": complement_match.group(1),
                                        "flags": "ALL",
                                    }
                                }
                            }
                        }
                    }
                )
            else:
                filters.append(
                    {
                        "regexp": {
                            "base_key": {
                                "value": search_request.filter_url_regexp,
                                "flags": "ALL",
                            }
                        }
                    }
                )

        # USD properties filter (AND — all conditions must match)
        if search_request.filter_by_properties:
            filters.extend(self._parse_usd_property_filters(search_request.filter_by_properties))

        # USD properties OR filter — at least one condition must match
        if search_request.filter_by_properties_include_any:
            any_filters = self._parse_usd_property_filters(search_request.filter_by_properties_include_any)
            if any_filters:
                filters.append({"bool": {"should": any_filters, "minimum_should_match": 1}})

        # USD properties exclusion filter
        if search_request.exclude_filter_by_properties:
            exclude_filters = self._parse_usd_property_filters(search_request.exclude_filter_by_properties)
            if exclude_filters:
                filters.append({"bool": {"must_not": exclude_filters}})

        # USD numeric properties filter
        if search_request.filter_by_properties_numeric:
            numeric_filters = self._parse_numeric_property_filters(search_request.filter_by_properties_numeric)
            if numeric_filters:
                filters.extend(numeric_filters)

        # USD properties filter
        if search_request.filter_by_tags:
            tags_filters = []
            for prop in search_request.filter_by_tags.split(","):
                if "=" in prop:
                    name, value = prop.split("=", 1)
                    query_conditions = []

                    # Key-only pattern: k=
                    if name and not value:
                        query_conditions.append(
                            {
                                "wildcard": {
                                    "tags.tag": {
                                        "value": name,
                                        "case_insensitive": True,
                                    }
                                }
                            }
                        )
                    # Value-only pattern: =v
                    elif not name and value:
                        query_conditions.append(
                            {
                                "wildcard": {
                                    "tags.value": {
                                        "value": value,
                                        "case_insensitive": True,
                                    }
                                }
                            }
                        )
                    # Key-value pattern: k=v
                    elif name and value:
                        query_conditions.extend(
                            [
                                {
                                    "wildcard": {
                                        "tags.tag": {
                                            "value": name,
                                            "case_insensitive": True,
                                        }
                                    }
                                },
                                {
                                    "wildcard": {
                                        "tags.value": {
                                            "value": value,
                                            "case_insensitive": True,
                                        }
                                    }
                                },
                            ]
                        )

                    if query_conditions:
                        tags_filters.append(
                            {
                                "nested": {
                                    "path": "tags",
                                    "query": {"bool": {"must": query_conditions}},
                                }
                            }
                        )
            if tags_filters:
                filters.append({"bool": {"must": tags_filters}})

        # Bounding box filters using usd_dimensions
        for axis in ["x", "y", "z"]:
            min_val = getattr(search_request, f"min_bbox_{axis}", None)
            max_val = getattr(search_request, f"max_bbox_{axis}", None)
            if min_val is not None or max_val is not None:
                bbox_range = {}
                if min_val is not None:
                    bbox_range["gte"] = min_val
                if max_val is not None:
                    bbox_range["lte"] = max_val
                if search_request.bbox_use_scaled_dimensions:
                    filters.append({"range": {f"usd_dimensions.scaled_bbox_dimension_{axis}": bbox_range}})
                else:
                    filters.append({"range": {f"usd_dimensions.bbox_dimension_{axis}": bbox_range}})

        return filters

    def _convert_size_to_bytes(self, size_str: str) -> int:
        """Convert size string (e.g., '1KB', '2MB') to bytes."""
        units = {"KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4}
        number = float(size_str[:-2])
        unit = size_str[-2:]
        return int(number * units[unit])

    def _parse_numeric_property_filters(self, filter_str: str) -> List[Dict[str, Any]]:
        """
        Parse numeric property filter string and build Elasticsearch nested range queries.

        Args:
            filter_str: Filter string in format "property>value,property<=value"
                       Supported operators: >, >=, <, <=, =

        Returns:
            List of Elasticsearch filter clauses

        Raises:
            HTTPException: 422 if filter string is invalid
        """
        import re

        if not filter_str or not filter_str.strip():
            raise HTTPException(
                status_code=422,
                detail="filter_by_properties_numeric cannot be empty",
            )

        filters = []
        # Pattern matches: property_name<operator>value
        # Operators (in order of specificity): >=, <=, >, <, =
        pattern = r"([^><=,]+)(>=|<=|>|<|=)([^,]+)"

        matches = list(re.finditer(pattern, filter_str))
        if not matches:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid filter_by_properties_numeric format: '{filter_str}'. "
                f"Expected format: 'property>value' or 'property>=value,property2<value'. "
                f"Supported operators: >, >=, <, <=, =",
            )

        for match in matches:
            prop_name = match.group(1).strip()
            operator = match.group(2)
            value_str = match.group(3).strip()

            if not prop_name:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid filter_by_properties_numeric: property name cannot be empty in '{match.group(0)}'",
                )

            if not value_str:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid filter_by_properties_numeric: value cannot be empty for property '{prop_name}'",
                )

            # Parse the numeric value
            try:
                numeric_value = float(value_str)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid filter_by_properties_numeric: '{value_str}' is not a valid numeric value for property '{prop_name}'",
                )

            # Map operator to Elasticsearch range query operator
            if operator == "=":
                # Exact numeric match using term query on value_numeric
                query = {
                    "nested": {
                        "path": "usd_properties",
                        "query": {
                            "bool": {
                                "must": [
                                    {"term": {"usd_properties.name": prop_name}},
                                    {"term": {"usd_properties.value_numeric": numeric_value}},
                                ]
                            }
                        },
                    }
                }
            else:
                # Range query
                range_op_map = {
                    ">": "gt",
                    ">=": "gte",
                    "<": "lt",
                    "<=": "lte",
                }
                es_operator = range_op_map[operator]

                query = {
                    "nested": {
                        "path": "usd_properties",
                        "query": {
                            "bool": {
                                "must": [
                                    {"term": {"usd_properties.name": prop_name}},
                                    {"range": {"usd_properties.value_numeric": {es_operator: numeric_value}}},
                                ]
                            }
                        },
                    }
                }

            filters.append(query)

        return filters

    def _build_text_query(self, field: str, value: str, config: FieldScoreConfig) -> Dict[str, Any]:
        """Build text query for a field based on its configuration."""
        # TODO: Use instead of wildcard queries for text fields
        # Requires reindexing with a new mapping
        if not config.enabled:
            return None

        if config.match_type == TextMatchType.EXACT:
            return {"match": {field: {"query": value, "boost": config.weight}}}
        elif config.match_type == TextMatchType.FUZZY:
            return {
                "fuzzy": {
                    field: {
                        "value": value,
                        "boost": config.weight,
                        "max_expansions": config.fuzzy_max_expansions,
                    }
                }
            }
        elif config.match_type == TextMatchType.PHRASE:
            return {"match_phrase": {field: {"query": value, "boost": config.weight}}}
        elif config.match_type == TextMatchType.PREFIX:
            return {"prefix": {field: {"value": value, "boost": config.weight}}}

    async def _run_composite_agg(self, base_agg: dict, agg_name: str) -> AsyncGenerator[dict, None]:
        """
        Helper method to run a composite aggregation and yield all buckets.
        """
        after_key = None

        while True:
            # Build the request body from scratch for each page
            body = deepcopy(base_agg)
            if after_key:
                body["aggs"]["usd_properties_agg"]["aggs"][agg_name]["composite"]["after"] = after_key

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Running composite aggregation with body:\n%s",
                    json.dumps(body, indent=2),
                )
            response = await self.client.search(index=self.index_name, body=body)
            result = response["aggregations"]["usd_properties_agg"][agg_name]
            buckets = result["buckets"]

            for b in buckets:
                yield b

            if "after_key" in result:
                after_key = result["after_key"]
            else:
                break

    async def get_usd_properties_stats(self, page_size=10000) -> StatsResponse:
        # Aggregation bodies:
        keys_agg = {
            "size": 0,
            "aggs": {
                "usd_properties_agg": {
                    "nested": {"path": "usd_properties"},
                    "aggs": {
                        "all_keys": {
                            "composite": {
                                "size": page_size,
                                "sources": [{"usd_key": {"terms": {"field": "usd_properties.name"}}}],
                            }
                        }
                    },
                }
            },
        }

        values_agg = {
            "size": 0,
            "aggs": {
                "usd_properties_agg": {
                    "nested": {"path": "usd_properties"},
                    "aggs": {
                        "all_values": {
                            "composite": {
                                "size": page_size,
                                "sources": [{"usd_value": {"terms": {"field": "usd_properties.value"}}}],
                            }
                        }
                    },
                }
            },
        }

        kv_agg = {
            "size": 0,
            "aggs": {
                "usd_properties_agg": {
                    "nested": {"path": "usd_properties"},
                    "aggs": {
                        "kv_pairs": {
                            "composite": {
                                "size": page_size,
                                "sources": [
                                    {"usd_key": {"terms": {"field": "usd_properties.name"}}},
                                    {"usd_value": {"terms": {"field": "usd_properties.value"}}},
                                ],
                            }
                        }
                    },
                }
            },
        }

        async def collect_agg_results(agg_body: dict, agg_name: str, mapper: Callable[[dict], Any]):
            results = []
            async for b in self._run_composite_agg(agg_body, agg_name):
                results.append(mapper(b))
            return results

        # Run all three aggregations in parallel
        keys_task = asyncio.create_task(
            collect_agg_results(
                keys_agg,
                "all_keys",
                lambda b: UniqueKey(key=b["key"]["usd_key"], asset_count=b["doc_count"]),
            )
        )
        values_task = asyncio.create_task(
            collect_agg_results(
                values_agg,
                "all_values",
                lambda b: UniqueValue(value=b["key"]["usd_value"], asset_count=b["doc_count"]),
            )
        )
        kv_task = asyncio.create_task(
            collect_agg_results(
                kv_agg,
                "kv_pairs",
                lambda b: KeyValuePair(
                    key=b["key"]["usd_key"],
                    value=b["key"]["usd_value"],
                    asset_count=b["doc_count"],
                ),
            )
        )

        unique_keys, unique_values, kv_pairs = await asyncio.gather(keys_task, values_task, kv_task)

        return StatsResponse(
            unique_keys=sorted(unique_keys, key=lambda x: x.asset_count, reverse=True),
            unique_values=sorted(unique_values, key=lambda x: x.asset_count, reverse=True),
            kv_pairs=sorted(kv_pairs, key=lambda x: x.asset_count, reverse=True),
        )
