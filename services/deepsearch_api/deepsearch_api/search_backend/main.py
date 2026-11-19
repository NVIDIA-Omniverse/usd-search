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
import uuid
from copy import deepcopy
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

import numpy as np
from deepsearch_api.routers_v2.models import SearchFilterFields
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
from .pagination import (
    DepthLimitReason,
    PageInfo,
    PageSpec,
    PaginationMode,
    build_cursor,
    fingerprint_request,
)
from .property_versions import (
    PropertyValues,
    PropertyValuesCache,
    matching_values,
    parse_version_filters,
)
from .utils import OrjsonSerializer

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Constant for vision metadata fields expansion in hybrid search
VISION_METADATA_FIELDS_PLACEHOLDER = "__VISION_METADATA_FIELDS__"

# The name vote (ScoringConfig.name_match): hits whose name or path holds every query word, as whole words.
NAME_VOTE_STOPWORDS = frozenset(
    {"a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "is", "of", "on", "or", "the", "to", "with"}
)
NAME_VOTE_MAX_WORDS = 8
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")
_WORD_PIECES = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")


def name_vote_words(query: str) -> List[str]:
    """The query's words for the name vote: split at anything not a letter or digit, lowercased, each once,
    stopwords and one-character words left out, at most NAME_VOTE_MAX_WORDS."""
    words: List[str] = []
    for word in _NON_ALNUM.split((query or "").lower()):
        if len(word) < 2 or word in NAME_VOTE_STOPWORDS or word in words:
            continue
        words.append(word)
        if len(words) == NAME_VOTE_MAX_WORDS:
            break
    return words


def _name_parts(text: str) -> Tuple[set, set]:
    """(parts, words) of a name or path, lowercased: parts are split at anything not a letter or digit; words add
    each part's camelCase and letter/digit pieces ("AllegroHand" -> allegrohand, allegro, hand)."""
    parts, words = set(), set()
    for part in _NON_ALNUM.split(text or ""):
        if not part:
            continue
        parts.add(part.lower())
        words.update(piece.lower() for piece in _WORD_PIECES.findall(part))
    return parts, words | parts


def _holds_word(word: str, parts: set, words: set) -> bool:
    if any(c.isdigit() for c in word):  # a model code: the start of a part (m900 ~ m900ib280, ur10 ~ ur10e)
        return any(part.startswith(word) for part in parts)
    return word in words or word + "s" in words or word + "es" in words or (word.endswith("s") and word[:-1] in words)


def holds_query_words(source: Dict[str, Any], words: List[str]) -> bool:
    """Whether a hit's name or path holds every word (name_vote_words) as a whole word."""
    parts, all_words = _name_parts(f"{source.get('name') or ''} {source.get('path') or ''}")
    return all(_holds_word(w, parts, all_words) for w in words)


def _top_matched_view(explanations: Optional[List[ScoreExplanation]]) -> Optional[Dict[str, Any]]:
    """A ranked hit's top matched view, as stored with it in the ranking cache, or None.

    The first matched vector with an image across the hit's explanations: the view a client shows and judges
    (``matched_vectors[0].image``). Short keys, since it is stored once per ranked hit.
    """
    for explanation in explanations or []:
        for vector in explanation.matched_vectors or []:
            if vector.image:
                return {
                    "t": getattr(explanation.search_type, "value", explanation.search_type),
                    "f": explanation.field,
                    "s": explanation.score,
                    "o": vector.offset,
                    "vs": vector.score,
                    "vf": vector.field,
                    "i": vector.image,
                }
    return None


def _explanations_from_cached_view(view: Any) -> List[ScoreExplanation]:
    """The explanation a page served from the ranking cache carries: the one naming the hit's top matched view.

    Explanations are built from per-leg hit payloads, which are not cached; without this, hits past the first page
    had no matched view, and a client validating them fell back to the asset's URL. [] for an entry cached without
    a view (a text-only hit, or a ranking cached before this) or one that does not parse.
    """
    if not isinstance(view, dict) or not view.get("i"):
        return []
    try:
        return [
            ScoreExplanation(
                search_type=view["t"],
                score=view["s"],
                field=view["f"],
                matched_vectors=[VectorScore(offset=view["o"], score=view["vs"], field=view["vf"], image=view["i"])],
            )
        ]
    except (KeyError, TypeError, ValueError):  # pydantic's ValidationError is a ValueError
        return []


def _normalize_extension_groups(or_groups: List[List[str]]) -> List[List[str]]:
    """Strip a single leading dot from extension tokens (".png" -> "png").

    The indexed ``ext`` field stores extensions without a leading dot, so a
    user-supplied ".png" would otherwise be a wildcard that matches nothing and
    silently returns no results. A real wildcard like "*.png" starts with "*",
    not ".", so it is left untouched.
    """
    return [[tok[1:] if tok.startswith(".") else tok for tok in group] for group in or_groups]


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

    # Floor for the auto-computed RRF fusion window used when a request omits
    # scoring_config.rrf_config.window_size, so small limits still give each leg
    # a meaningful fusion pool. Capped by OPENSEARCH_MAX_RESULT_WINDOW.
    # Env var: RRF_MIN_WINDOW_SIZE (no env_prefix on SearchSettings).
    rrf_min_window_size: int = 100

    # --- Pagination (docs/plans/search-pagination.md §4.6) ---------------------
    # None of these are mandatory: cursors are unsigned and self-describing, so
    # pagination adds no deployment config that has to be kept in sync between
    # replicas. Env vars are the bare upper-cased names (no env_prefix here).
    #
    # Depth cap for text-query and multi-leg searches. NOT applied to filter-only
    # queries, which page to arbitrary depth over a unique keyword sort.
    pagination_max_offset: int = 10000
    # Fusion window pinned for a multi-leg query that does not set
    # scoring_config.rrf_config.window_size. The window IS the reachable result
    # set when paging — a client can never see past it — so it has to exceed the
    # old floor of 100, which capped a hybrid query at ~3 pages.
    #
    # It is not free: every leg fetches `window` documents per request, so this
    # multiplies per-leg fetch and deserialization volume directly, and the
    # similarity sweep (when similarity_threshold is set) is O(window^2) in
    # Python. 200 keeps that within ~2x of the pre-pagination cost while giving
    # 10 pages at the Explorer's default limit of 20. Raise it per request via
    # scoring_config.rrf_config.window_size when a specific caller needs depth.
    #
    # MIRRORED IN THE UI: services/explorer/src/utils/pagination.js (DEFAULT_WINDOW)
    # hardcodes this to label its window-size presets and to explain the limit when
    # paging stops. Nothing fails if the two diverge — the Explorer just labels the
    # wrong number as the default — so changing this value needs a UI check too.
    pagination_default_window: int = 200
    # Access filtering runs after the page is cut, so pages have to be topped
    # back up (FilteredSearchClient._search_filling_page). Over-fetching this
    # much per attempt fills a page in one round trip for any caller who can see
    # at least 1/factor of the corpus...
    access_filter_overfetch_factor: int = 3
    # ...and this bounds what the rest cost: 4 attempts at 3x reach ~12
    # page-widths of candidates, past which the caller gets a short page plus
    # has_more=true rather than a request that walks the index looking for
    # something visible.
    access_filter_max_fetches: int = 4
    # Cursor lifetime. Bounded so a cursor cannot long outlive the index state it
    # describes; clamped down to the ranking cache's TTL when that cache is on, so
    # a cursor never outlives the ranking it points at. 0 disables expiry.
    pagination_cursor_ttl_seconds: int = 900

    # --- filter_by_properties_version (see property_versions.py) --------------
    # How long a property's distinct values are cached per process; also how long
    # a newly indexed version can take to start matching. 0 disables the cache.
    property_values_cache_ttl_seconds: int = 60
    # Properties with more distinct values than this are rejected with a 422
    # rather than compared against a partial list.
    property_values_max_count: int = 1000
    # Each distinct property in one request costs its own aggregation on a cache
    # miss, so requests naming more properties than this are rejected with a 422.
    version_filter_max_properties: int = 10
    # Longest filter_by_properties_version string accepted; longer is rejected with
    # a 422 before it is parsed. Read by the request model's validator.
    version_filter_max_length: int = 4096


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
        self._rrf_min_window_size = settings.rrf_min_window_size
        self.pagination_max_offset = settings.pagination_max_offset
        self._pagination_default_window = settings.pagination_default_window
        self._pagination_cursor_ttl_seconds = settings.pagination_cursor_ttl_seconds
        # Read by FilteredSearchClient, which owns the post-filter page refill.
        self.access_filter_overfetch_factor = settings.access_filter_overfetch_factor
        self.access_filter_max_fetches = settings.access_filter_max_fetches
        # Optional RRF ranking cache (Redis), attached at startup. Purely a
        # latency optimisation for pages 2..N of a multi-leg query — when absent
        # or unreachable, every page recomputes the fused ranking, which is
        # correct, just slower.
        self.ranking_cache: Optional[Any] = None
        self.text_to_vector_model = None  # Initialize text-to-vector model when needed
        # One-time index-mapping check guard (see ensure_mappings_verified). This
        # client is shared process-wide, so mappings are verified once, not per request.
        self._mappings_verified = False
        self.embedding_clients: dict[EmbeddingType, BaseEmbeddingInterface] = embedding_clients
        if EmbeddingType.SIGLIP2_EMBEDDING not in embedding_clients:
            raise ValueError("Siglip2 embedding client is required for SearchBackendClientV2")

        # Vision metadata configuration
        self.vision_generated_dynamic_templates_suffix = "vlm_generated"

        # Cache for vision metadata fields with TTL
        self._vision_metadata_fields_cache = None
        self._vision_metadata_fields_cache_timestamp = 0
        self._vision_metadata_fields_cache_ttl = 300  # 5 minutes TTL

        self._property_values_cache = PropertyValuesCache(ttl_seconds=settings.property_values_cache_ttl_seconds)
        self._property_values_max_count = settings.property_values_max_count
        self._version_filter_max_properties = settings.version_filter_max_properties

        if search_filter_config is None:
            self.search_filter_config = SearchFilterConfig()
        else:
            self.search_filter_config = search_filter_config

    async def __aenter__(self):
        await self.ensure_mappings_verified()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def close(self):
        await self.client.close()

    async def ensure_mappings_verified(self) -> None:
        """Verify the index mappings exactly once for this (shared) client.

        Idempotent and cheap after the first success (a bool check). Safe to call
        on the hot path: the underlying check is module-cached and the mapping
        write is idempotent, so a concurrent double-run before the flag is set is
        harmless. Left un-set if verification fails (e.g. OpenSearch briefly down
        at startup) so the next caller retries.
        """
        if self._mappings_verified:
            return
        with tracer.start_as_current_span("search_backend.verify_search_index_mappings"):
            await self.verify_search_index_mappings()
        self._mappings_verified = True

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

    async def _build_hybrid_text_query(self, query: str, config: ScoringConfig) -> Optional[Dict[str, Any]]:
        """Build a query that searches across multiple fields with separate match queries.

        Returns None when no enabled field produces a clause — an empty bool/should
        would be a match-all query and inject arbitrary documents as a full-strength
        RRF leg.
        """

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
                    # Score free text against metadata VALUES only. The `name`/`name_sayt`
                    # subfields hold schema labels ("colors", "materials", ...) that would
                    # match query words like "color" on every VLM-tagged asset, and
                    # `value_sayt` duplicates `value_text` content — both inflate the
                    # text leg with noise. The sayt/name subfields remain available to
                    # the explicit `vision_metadata` k=v filter.
                    for subfield in ["value_text"]:
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

                # Wrap the match query in a nested query. score_mode=sum so an asset
                # matching several nested docs (e.g. colors=red AND materials=plastic)
                # accumulates score instead of averaging down to a single-term match.
                nested_query = {
                    "nested": {
                        "path": path,
                        "query": match_query,
                        "score_mode": "sum",
                        "_name": f"{field_config.field}_field",  # Move _name to root level
                    }
                }
                queries.append(nested_query)
                # TODO: Add wildcard support for nested fields

        # No enabled fields produced clauses — signal the caller to skip the text leg
        if not queries:
            return None

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
                    search_type,
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

    @staticmethod
    def _deterministic_leg_sort() -> List[Dict[str, Any]]:
        """Sort spec giving every leg a total, reproducible order.

        OpenSearch does not order equal-scoring documents stably across requests
        (different shard copies, different segment layouts), and RRF scores a
        document by its *rank* within a leg — so tied documents swapping
        positions 5 and 6 swaps their fused scores too. The order has to be
        pinned at the leg; a Python-side tiebreak is too late. Ties are the norm,
        not the exception: a filter-only ``match_all`` leg scores everything 1.0.

        ``base_key`` is a unique indexed keyword, always fetched; sorting on
        ``_id`` would need fielddata. ``_score`` first keeps relevance order and
        keeps scores computed. The per-hit ``sort`` values this emits are what
        ``search_after`` consumes.
        """
        return [{"_score": "desc"}, {"base_key": "asc"}]

    async def _page_from_cached_ranking(
        self,
        search_request: DeepSearchSearchRequestV2,
        page: PageSpec,
        query_fingerprint: str,
        size: int,
    ) -> Optional[Tuple[List[Tuple[str, Dict[str, Any]]], int]]:
        """Serve an RRF page from a previously materialised fused order.

        Returns ``(paginated_docs, ranking_length)``, or None to fall back to
        recomputing — on a cache miss, an expiry, a fingerprint mismatch, or any
        Redis error. Falling back is always correct, just slower: the cursor
        carries everything needed to rebuild the ranking.

        Only the *order* is cached, so document bodies are re-fetched by id here.
        That keeps the cache small and means it can never serve a stale
        ``_source``.
        """
        if not (self.ranking_cache and page.ranking_id):
            return None

        order = await self.ranking_cache.get(page.ranking_id, query_fingerprint)
        if not order:
            return None

        # raw_offset: the cached order is the pre-access-filter one, so it is
        # indexed by the raw position (identical to `offset` unless access
        # filtering has dropped hits earlier in the walk).
        window = order[page.raw_offset : page.raw_offset + size]
        if not window:
            return [], len(order)

        hits_by_id = await self._fetch_hits_by_ids([entry["id"] for entry in window], search_request)

        paginated_docs: List[Tuple[str, Dict[str, Any]]] = []
        for entry in window:
            hit = hits_by_id.get(entry["id"])
            if hit is None:
                # Deleted between the ranking being built and this page being
                # requested. Skip it rather than fabricate a hit; the page comes
                # back one short, which is the same shape access filtering
                # produces and which has_more already accounts for.
                continue
            paginated_docs.append(
                (
                    entry["id"],
                    {
                        "hit": hit,
                        "rrf_score": entry.get("s", 0.0),
                        "original_ranks": entry.get("r", {}),
                        "original_scores": entry.get("os", []),
                        # Score explanations are derived from per-leg hit payloads,
                        # which are deliberately not cached (they would dwarf the
                        # order itself). Pages served from cache carry
                        # rrf_score/rrf_rank/original_ranks and one explanation:
                        # the hit's top matched view, stored with the order.
                        "explanations": _explanations_from_cached_view(entry.get("mv")),
                    },
                )
            )
        return paginated_docs, len(order)

    async def _fetch_hits_by_ids(
        self, doc_ids: List[str], search_request: DeepSearchSearchRequestV2
    ) -> Dict[str, Dict[str, Any]]:
        """Fetch raw hits for an explicit id list, keyed by id.

        Used by the cached-ranking path: the fused order is known, only the
        bodies are missing.
        """
        if not doc_ids:
            return {}
        body = {
            "query": {"ids": {"values": doc_ids}},
            "_source": self._build_source_includes(search_request),
        }
        with tracer.start_as_current_span("search_backend.fetch_by_ids") as span:
            span.set_attribute("query.type", "ids")
            span.set_attribute("query.id_count", len(doc_ids))
            response = await self.client.search(index=self.index_name, body=body, size=len(doc_ids))
        return {hit["_id"]: hit for hit in response.get("hits", {}).get("hits", [])}

    def cursor_ttl(self) -> Optional[int]:
        """Cursor lifetime.

        ``pagination_cursor_ttl_seconds`` bounds how long a cursor may describe an
        index that has moved on underneath it; 0 disables expiry. When the ranking
        cache is on the two are kept in step (the smaller wins) so a cursor never
        outlives the ranking it points at by much — an expired cursor is a clean
        400, whereas a stale ranking id would silently recompute.
        """
        ttl = self._pagination_cursor_ttl_seconds or None
        if self.ranking_cache:
            ttl = min(ttl, self.ranking_cache.ttl_seconds) if ttl else self.ranking_cache.ttl_seconds
        return ttl

    def default_window_size(self, search_request: DeepSearchSearchRequestV2, retrieval_depth: int) -> int:
        """Fusion window for a query no cursor has pinned one for."""
        return search_request.scoring_config.rrf_config.window_size or max(
            self._rrf_min_window_size, self._pagination_default_window, retrieval_depth * 2
        )

    def _select_pagination_mode(
        self,
        search_request: DeepSearchSearchRequestV2,
        leg_count: int,
        requested: Optional[PaginationMode] = None,
    ) -> PaginationMode:
        """Pick the retrieval strategy. Never caller-controlled — it flips with
        the leg count, which is an implementation detail.

        LEG mode pages natively in OpenSearch and needs a single leg, where RRF
        order is that leg's own order: an optimisation plus extra depth, not a
        ranking change. ``similarity_threshold`` disqualifies it, since that
        sweep is prefix-dependent (offset 5000 cannot be judged without having
        materialised 0..4999) — but only when the sweep actually runs, so a
        filter-only request carrying an inert threshold keeps LEG mode.

        ``requested`` is a cursor's pinned mode; honouring it keeps a walk in one
        mode, and can only narrow LEG to RRF, never the reverse.
        """
        similarity_sweep_runs = search_request.similarity_threshold is not None and bool(
            search_request.description or search_request.image_similarity_search or search_request.vector_queries
        )
        eligible = leg_count <= 1 and not similarity_sweep_runs
        if not eligible:
            return PaginationMode.RRF
        if requested == PaginationMode.RRF:
            return PaginationMode.RRF
        return PaginationMode.LEG

    def _leg_retrieval_params(
        self,
        mode: PaginationMode,
        page: PageSpec,
        limit: int,
        window_size: int,
    ) -> Tuple[int, Optional[int], Optional[List[Any]]]:
        """Per-leg ``size`` / ``from`` / ``search_after`` for the chosen mode.

        RRF mode fetches the full fusion window on every leg and slices in Python
        afterwards — the fused order does not exist until the legs are merged, so
        OpenSearch cannot do the paging.

        LEG mode pushes the paging down to OpenSearch: ``from``/``size`` while
        ``from + size`` fits inside ``index.max_result_window``, then
        ``search_after`` beyond it. ``search_after`` has no depth limit; ``from``
        is rejected by the server once ``from + size`` exceeds the window, and
        batching does not help because the check is per request.
        """
        if mode == PaginationMode.RRF:
            return window_size, None, None

        if page.search_after:
            # Deep page: resume from the previous page's last sort values. `from`
            # must not be combined with search_after.
            return limit, None, page.search_after

        # raw_offset, not offset: `from` indexes the pre-access-filter ordering.
        return limit, page.raw_offset, None

    async def _execute_leg(
        self,
        leg: Dict[str, Any],
        size: int,
        from_: Optional[int] = None,
        search_after: Optional[List[Any]] = None,
        preference: Optional[str] = None,
    ) -> Tuple[Any, float, Dict[str, Any]]:
        """Run one leg and return ``(name, weight, response)``.

        ``preference`` pins the shard copies the leg runs on. A primary and its
        replicas score the same document differently (each holds its own deleted
        docs until a merge, which shifts BM25 statistics, and builds its own kNN
        graphs), so without it consecutive pages of one walk can land on
        different copies: a ``search_after`` score taken from one copy then skips
        or repeats documents on another, and a replayed cursor returns a different
        page. Passing the query fingerprint keeps every page and replay of a walk
        on the same copies. It is a routing hint, never a constraint: if a pinned
        copy goes away OpenSearch falls back to another one. The value must not
        start with ``_``, which OpenSearch reserves for its special preferences.
        """
        body = leg["body"]
        if search_after:
            body = {**body, "search_after": search_after}

        kwargs: Dict[str, Any] = {}
        if from_:
            kwargs["from_"] = from_
        if preference:
            kwargs["preference"] = preference

        with tracer.start_as_current_span("search_backend.opensearch_query") as span:
            span.set_attribute("query.type", leg["type_attr"])
            span.set_attribute("query.size", size)
            if "index" in leg:
                span.set_attribute("query.vector_index", leg["index"])
            if from_:
                span.set_attribute("query.from", from_)
            if search_after:
                span.set_attribute("query.search_after", True)
            response = await self.client.search(
                index=self.index_name,
                body=body,
                size=size,
                explain=False,  # OpenSearch _explain output is not exposed by the API
                # Every leg counts exactly. Without this OpenSearch stops counting
                # at 10000, so corpus_total (a max() across legs) silently
                # saturated whenever a vector leg won.
                track_total_hits=True,
                **kwargs,
            )
            span.set_attribute("query.took_ms", response.get("took", 0))
            span.set_attribute(
                "query.total_hits",
                response.get("hits", {}).get("total", {}).get("value", 0),
            )
        return (leg["name"], leg["weight"], response)

    async def search(
        self,
        search_request: DeepSearchSearchRequestV2,
        from_: int = 0,
        url_whitelist: Optional[List[str]] = None,
        window_size: Optional[int] = None,
        page: Optional[PageSpec] = None,
    ) -> SearchResponse:
        """Run the multi-leg search and fuse the legs with client-side RRF.

        Args:
            window_size: Pin the RRF fusion window explicitly. Pagination MUST pass
                this (carried in the cursor), because the auto-computed default
                below grows with ``from_`` — page 1 would fuse a pool of 100 and
                page 10 a pool of 640, so a given offset would not denote a stable
                document across pages. When ``None`` the legacy auto-computation is
                kept so existing non-paginating callers are unaffected.
        """
        logger.debug(
            "Performing search with request:\n%s",
            search_request.model_dump_json(indent=2),
        )

        size = search_request.limit

        # `from_` is the legacy positional offset; `page` is the richer form used
        # by pagination. Reconcile them so both entry points work.
        if page is None:
            page = PageSpec(offset=from_, raw_offset=from_)
        # Retrieval happens in the RAW (pre-access-filter) space: `raw_offset` is
        # the position in the ordering OpenSearch and the fusion step produce,
        # whereas `offset` counts only the hits a caller actually received. The two
        # coincide unless the access-filtering layer has dropped hits (see
        # FilteredSearchClient), so this is a no-op for every other caller.
        from_ = page.raw_offset

        # How deep this request needs to reach: the page start plus the page itself.
        retrieval_depth = from_ + size

        scoring_config = search_request.scoring_config
        rrf_config = scoring_config.rrf_config
        # cap the window size to OPENSEARCH_MAX_RESULT_WINDOW; floor at
        # pagination_default_window (the window IS the reachable set in RRF mode,
        # so a small pool would cap a hybrid query at a couple of pages), and grow
        # with the requested depth for callers asking for a big single page.
        window_size = min(
            page.window or window_size or self.default_window_size(search_request, retrieval_depth),
            OPENSEARCH_MAX_RESULT_WINDOW,
        )

        query_fingerprint = fingerprint_request(search_request)

        # Fast path: a later page of a multi-leg query whose fused order was
        # already materialised. Skips every leg (including the kNN ones) and the
        # O(n^2) similarity sweep, fetching only this page's documents by id.
        # A miss falls through and recomputes — see cache/ranking_cache.py.
        cached = await self._page_from_cached_ranking(search_request, page, query_fingerprint, size)
        if cached is not None:
            paginated_docs, ranking_length = cached
            return await self._assemble_response(
                search_request=search_request,
                page=page,
                mode=PaginationMode.RRF,
                paginated_docs=paginated_docs,
                size=size,
                window_size=window_size,
                total_hits=ranking_length,
                corpus_total=ranking_length,
                took=0,
                query_fingerprint=query_fingerprint,
                ranking_id=page.ranking_id,
            )

        # Store individual search results
        all_results = []
        # Set by whichever branch runs; the filter-only branch is single-leg by
        # definition so it settles the mode up front.
        mode = PaginationMode.RRF
        bool_filters = await self.create_bool_filters(search_request)
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
            # match_all scores every document 1.0, so the whole result set is one
            # tie — without an explicit sort the order is whatever the shards
            # happen to return.
            query["sort"] = self._deterministic_leg_sort()

            logger.debug(
                "Executing filter-only search with query:\n%s",
                json.dumps(query, indent=2),
            )
            # One leg by construction, so LEG mode always applies (there is no
            # similarity_threshold to disqualify it — that filter is inert without
            # a vector query). This is the shape that pages to arbitrary depth.
            mode = self._select_pagination_mode(search_request, leg_count=1, requested=page.mode)
            leg_size, leg_from, leg_search_after = self._leg_retrieval_params(
                mode=mode, page=page, limit=size, window_size=window_size
            )
            all_results.append(
                await self._execute_leg(
                    leg={
                        "name": SearchType.FILTER_ONLY,
                        "weight": 1.0,
                        "body": query,
                        "type_attr": "filter_only",
                    },
                    size=leg_size,
                    from_=leg_from,
                    search_after=leg_search_after,
                    preference=query_fingerprint,
                )
            )

        else:

            def _prepare_leg_query(inner_query: Dict[str, Any]) -> Dict[str, Any]:
                leg_query = {"query": inner_query}
                if bool_filters:
                    leg_query["query"] = {
                        "bool": {
                            "must": [leg_query["query"]],
                            "filter": bool_filters,
                        }
                    }
                # Add collapse for deduplication if requested
                leg_query = self._add_collapse_for_deduplication(leg_query, search_request)
                leg_query["_source"] = source_includes
                # Pin tie order so per-leg ranks (and therefore RRF scores) are
                # reproducible across requests.
                leg_query["sort"] = self._deterministic_leg_sort()
                return leg_query

            # Build every leg BEFORE executing any of them: the pagination mode is
            # decided by how many legs a query actually produces, and that is not
            # known from the request alone (a text query whose fields are all
            # disabled contributes no leg, and vector legs fan out per query/image).
            legs: List[Dict[str, Any]] = []

            # Prepare hybrid text search if enabled
            if search_request.hybrid_text_query and scoring_config.hybrid_text.enabled:
                with tracer.start_as_current_span("search_backend.build_hybrid_text_query"):
                    hybrid_text_inner = await self._build_hybrid_text_query(
                        search_request.hybrid_text_query, scoring_config
                    )

                if hybrid_text_inner is None:
                    logger.warning(
                        "Hybrid text query given but no enabled fields produced clauses; skipping the text leg"
                    )
                else:
                    hybrid_query = _prepare_leg_query(hybrid_text_inner)
                    logger.debug(
                        "Preparing hybrid text search with query:\n%s",
                        json.dumps(hybrid_query, indent=2),
                    )
                    legs.append(
                        {
                            "name": SearchType.HYBRID,
                            "weight": scoring_config.hybrid_text.weight,
                            "body": hybrid_query,
                            "type_attr": "hybrid_text",
                            "is_vector": False,
                        }
                    )

            # Prepare all vector searches.
            #
            # k is how many candidates an approximate-kNN leg retrieves per shard.
            # It must cover BOTH uses, because the mode is not settled yet — it
            # depends on the leg count, which is only known once these are built:
            #   - RRF mode fuses the whole window, so k >= window_size
            #   - LEG mode pages to offset + limit, and an approximate leg has
            #     nothing to page into past k (it never retrieved those
            #     candidates), so k >= retrieval_depth
            knn_k = min(max(window_size, retrieval_depth), OPENSEARCH_MAX_RESULT_WINDOW)
            with tracer.start_as_current_span("search_backend.build_vector_queries"):
                vector_queries = await self._build_vector_queries(search_request, knn_k)
            for idx, (vector_query, vector_field_name) in enumerate(vector_queries):
                query = _prepare_leg_query(vector_query)

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

                # Resolve this leg's RRF weight from the embedding field it searches.
                # Resolution happens here, at leg-construction time, because the leg
                # name alone ("vector_0", "text_to_vector", ...) does not identify
                # the configured vector field.
                vector_field_config = scoring_config.vector_fields.get(vector_field_name)
                leg_weight = vector_field_config.weight if vector_field_config else 1.0

                legs.append(
                    {
                        "name": query_name,
                        "weight": leg_weight,
                        "body": query,
                        "type_attr": "vector",
                        "is_vector": True,
                        "index": idx,
                    }
                )

            # Now that the leg count is known, settle the mode and re-derive the
            # per-leg retrieval depth from it.
            mode = self._select_pagination_mode(search_request, leg_count=len(legs), requested=page.mode)
            leg_size, leg_from, leg_search_after = self._leg_retrieval_params(
                mode=mode, page=page, limit=size, window_size=window_size
            )

            search_tasks = [
                asyncio.create_task(
                    self._execute_leg(
                        leg=leg,
                        size=leg_size,
                        from_=leg_from,
                        search_after=leg_search_after,
                        preference=query_fingerprint,
                    )
                )
                for leg in legs
            ]

            # Execute all search tasks in parallel
            if search_tasks:
                logger.debug("Executing %d search queries in parallel", len(search_tasks))
                search_results = await asyncio.gather(*search_tasks)
                all_results.extend(search_results)

        # Process results and implement client-side RRF
        document_scores = {}

        # Calculate RRF scores for each document
        with tracer.start_as_current_span("search_backend.calculate_rrf_scores"):
            # Each leg carries its own weight, resolved at leg-construction time
            # (hybrid_text.weight or the matching vector_fields[...].weight).
            # Weights MUST NOT be re-derived from leg names here: names like
            # "vector_0" or "text_to_vector" do not map back to a vector_fields
            # key, which previously caused all configured vector weights to be
            # silently ignored.
            # In LEG mode OpenSearch already returned only the requested page, so
            # the first hit is at absolute position `offset`, not 1. Ranks must be
            # absolute or a doc's rrf_score would change purely with which page it
            # was fetched on.
            rank_offset = page.raw_offset if mode == PaginationMode.LEG else 0

            for query_name, query_weight, response in all_results:
                rank_constant = rrf_config.query_rank_constants.get(query_name, rrf_config.rank_constant)
                # Leg names arrive as either a plain str (vector legs: "vector_0")
                # or a SearchType member (text, filter-only). They end up as dict
                # keys in `original_ranks`, which is declared Dict[str, int] and is
                # serialized by orjson when the fused order is cached — and orjson
                # rejects a dict key that is not exactly str, enum-of-str or not.
                # Normalise once, here, rather than at each use.
                rank_key = query_name.value if isinstance(query_name, SearchType) else query_name

                for rank, hit in enumerate(response["hits"]["hits"], rank_offset + 1):
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
                    document_scores[doc_id]["original_ranks"][rank_key] = rank
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

        # The name vote (ScoringConfig.name_match): the hits whose name or path holds every query word, as whole
        # words, get one more vote, ranked in the order fused so far. Read from the hits the legs returned, so no
        # extra query runs; fused requests only (a single leg is paged by OpenSearch, where a vote moves nothing).
        # A query shorter than min_words votes only when its word is rare among those hits (rare_word_hits).
        name_match = scoring_config.name_match
        vote_query = search_request.hybrid_text_query or search_request.description
        if mode == PaginationMode.RRF and name_match.enabled and name_match.weight > 0 and vote_query:
            words = name_vote_words(vote_query)
            if words:
                fused = sorted(
                    document_scores.items(),
                    key=lambda x: (-x[1]["rrf_score"], x[1]["hit"].get("_source", {}).get("base_key", ""), x[0]),
                )
                voted = [doc for _, doc in fused if holds_query_words(doc["hit"].get("_source", {}), words)]
                if len(words) < name_match.min_words and len(voted) > name_match.rare_word_hits:
                    voted = []
                rank_constant = rrf_config.query_rank_constants.get(SearchType.NAME, rrf_config.rank_constant)
                for rank, doc in enumerate(voted, 1):
                    vote = name_match.weight / (rank + rank_constant)
                    doc["rrf_score"] += vote
                    doc["original_ranks"][SearchType.NAME.value] = rank
                    doc.setdefault("explanations", []).append(
                        ScoreExplanation(
                            search_type=SearchType.NAME,
                            score=1.0,
                            field="name",
                            rrf_score=vote,
                            rrf_rank_constant=rank_constant,
                            matched_terms=words,
                        )
                    )

        # Sort documents by RRF score, with a deterministic tiebreak.
        #
        # Exact rrf_score ties happen whenever two documents occupy the same rank
        # in different legs (e.g. doc A is #3 in the text leg, doc B is #3 in the
        # vector leg, and neither appears in the other). Sorting on rrf_score alone
        # left those to `document_scores` insertion order. That is reproducible
        # within one process, but it is derived from per-leg hit order, which is
        # NOT stable across requests — see _deterministic_leg_sort() for why.
        #
        # base_key is the per-document unique key (hash_value repeats across
        # base_keys, which is why deduplicate_by_hash collapses on it) and is always
        # fetched via _BASE_SOURCE_FIELDS. doc_id is a belt-and-braces final key: it
        # is the dict key here, so it is unique even if _source were ever filtered
        # down past base_key.
        sorted_docs = sorted(
            document_scores.items(),
            key=lambda x: (
                -x[1]["rrf_score"],
                x[1]["hit"].get("_source", {}).get("base_key", ""),
                x[0],
            ),
        )

        # Apply similarity threshold filtering for embedding-based searches
        filtered_docs = self._apply_similarity_threshold_filtering(sorted_docs, search_request)

        # Lower-bound estimate of corpus matches: max of per-leg OpenSearch total_hits.
        # Each leg applies the same bool_filters, so max(legs) <= true union <= sum(legs).
        # Every leg now runs with track_total_hits=True, so each leg's own count is
        # exact; this is a lower bound only because legs may disagree on membership.
        corpus_total = max(
            (r.get("hits", {}).get("total", {}).get("value", 0) for _, _, r in all_results),
            default=0,
        )

        ranking_id = None
        if mode == PaginationMode.LEG:
            # OpenSearch already applied from/size (or search_after), so these ARE
            # the page. Slicing again would drop everything past the first page.
            paginated_docs = filtered_docs
            # There is no fusion window here — the whole result set is reachable,
            # so the candidate pool is the corpus match count.
            total_hits = corpus_total
        else:
            total_hits = len(filtered_docs)
            paginated_docs = filtered_docs[from_ : from_ + size]
            # Materialise the fused order so later pages can skip the legs
            # entirely. Best-effort: a failed write only costs the next page a
            # recompute. Reuse the incoming ranking id when resuming after a
            # cache miss, so a walk keeps one id rather than orphaning entries.
            #
            # Detached (set_soon, not await set): this response does not read what
            # it writes, so waiting on Redis here only adds a round trip — a
            # cross-node one in most deployments — to every first page.
            if self.ranking_cache and total_hits > size:
                ranking_id = page.ranking_id or uuid.uuid4().hex
                order = []
                for doc_id, info in filtered_docs:
                    entry = {
                        "id": doc_id,
                        "s": info["rrf_score"],
                        "r": info["original_ranks"],
                        "os": info.get("original_scores", []),
                    }
                    # The hit's top matched view, so later pages name it too (see _explanations_from_cached_view).
                    view = _top_matched_view(info.get("explanations"))
                    if view:
                        entry["mv"] = view
                    order.append(entry)
                self.ranking_cache.set_soon(ranking_id, query_fingerprint, order)

        return await self._assemble_response(
            search_request=search_request,
            page=page,
            mode=mode,
            paginated_docs=paginated_docs,
            size=size,
            window_size=window_size,
            total_hits=total_hits,
            corpus_total=corpus_total,
            took=sum(r["took"] for _, _, r in all_results),
            query_fingerprint=query_fingerprint,
            ranking_id=ranking_id,
        )

    async def _assemble_response(
        self,
        search_request: DeepSearchSearchRequestV2,
        page: PageSpec,
        mode: PaginationMode,
        paginated_docs: List[Tuple[str, Dict[str, Any]]],
        size: int,
        window_size: int,
        total_hits: int,
        corpus_total: int,
        took: int,
        query_fingerprint: str,
        ranking_id: Optional[str] = None,
    ) -> SearchResponse:
        """Turn a page of fused documents into the API response.

        Shared by the normal path and the cached-ranking fast path so both emit
        identical shapes.
        """
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
                    # Absolute position in the ranked list, not position within
                    # this page — otherwise every page would restart at 1.
                    rrf_rank=page.offset + len(final_hits) + 1,
                    original_ranks=doc_info["original_ranks"],
                ),
                source=filtered_source,
                inner_hits=(hit.get("inner_hits", {}) if search_request.return_inner_hits else {}),
                thumbnail_exists=thumbnail_exists,
                # Only LEG mode paginates through OpenSearch, so only there do the
                # per-hit sort values mean anything; the cached-ranking path has no
                # hits to take them from. Never serialized (excluded on the field).
                sort_values=hit.get("sort"),
            )
            final_hits.append(result)

        page_info, paginable_total, has_more, next_cursor = self._build_pagination_state(
            search_request=search_request,
            page=page,
            mode=mode,
            page_hits=paginated_docs,
            page_size=size,
            window_size=window_size,
            candidate_total=total_hits,
            query_fingerprint=query_fingerprint,
            ranking_id=ranking_id,
        )

        search_response = SearchResponse.model_construct(
            total=total_hits,
            corpus_total=corpus_total,
            paginable_total=paginable_total,
            next_cursor=next_cursor,
            has_more=has_more,
            pagination=page_info.model_dump(mode="json"),
            hits=final_hits,
            search_metadata={
                "took": took,
                "max_score": max((h.score for h in final_hits), default=0),
            },
        )
        logger.debug(
            "SearchBackendClientV2 response:\n%s",
            search_response.model_dump_json(indent=2),
        )
        return search_response

    def _build_pagination_state(
        self,
        search_request: DeepSearchSearchRequestV2,
        page: PageSpec,
        mode: PaginationMode,
        page_hits: List[Tuple[str, Dict[str, Any]]],
        page_size: int,
        window_size: int,
        candidate_total: int,
        query_fingerprint: Optional[str] = None,
        ranking_id: Optional[str] = None,
    ) -> Tuple[PageInfo, int, bool, Optional[str]]:
        """Work out how deep this query can go, and mint the next cursor.

        Returns ``(page_info, paginable_total, has_more, next_cursor)``.

        ``paginable_total`` — NOT ``corpus_total`` — is what a paginator should
        render: in RRF mode only the fusion window is reachable, so showing a
        1.2M corpus count over a 1000-document pool would be wrong.
        """
        consumed = len(page_hits)

        if search_request.validate_results:
            # Single-page by contract (see the plan, §9.5): VLM validation drops
            # non-matching hits after the page is cut and never backfills. Minting
            # a cursor here would hand the caller a token the server then refuses,
            # so say up front that this is the only page.
            return (
                PageInfo(
                    mode=mode,
                    offset=page.offset,
                    page_size=consumed,
                    depth_limit=consumed,
                    depth_limit_reason=DepthLimitReason.VALIDATION,
                ),
                consumed,
                False,
                None,
            )

        if mode == PaginationMode.RRF:
            # Fusion happens client-side over a bounded window, so the window IS
            # the reachable set.
            depth_limit = min(window_size, page.max_offset)
            reason = DepthLimitReason.RRF_WINDOW
        elif search_request.deduplicate_by_hash:
            # collapse + search_after is rejected by the server unless the collapse
            # field IS the sort field ("collapse field and sort field must be the
            # same...", verified on OpenSearch 3.6.0 — plan 7.1b). Satisfying that
            # would mean sorting on hash_value and losing relevance order, so
            # deduplicated queries stay on from/size and inherit its hard cap.
            depth_limit = min(OPENSEARCH_MAX_RESULT_WINDOW, page.max_offset)
            reason = DepthLimitReason.COLLAPSE
        else:
            depth_limit = page.max_offset
            reason = DepthLimitReason.MAX_OFFSET

        paginable_total = min(candidate_total, depth_limit)
        # Depth is measured in the raw (pre-access-filter) space, which is what
        # every limit here is expressed in; `offset` only counts hits the caller
        # actually received, and diverges once access filtering drops some.
        next_raw = page.raw_offset + consumed
        next_offset = page.offset + consumed
        has_more = consumed > 0 and next_raw < paginable_total

        next_cursor = None
        # Set when paging stops because the retrieval mechanism ran out, not
        # because the results did. Keeps the EXHAUSTED override below from
        # relabelling a hard stop as "no more results" — the whole point of
        # depth_limit_reason is that a client can tell those two apart.
        stopped_by_depth = False
        if has_more:
            search_after = None
            if mode == PaginationMode.LEG and not search_request.deduplicate_by_hash:
                # Beyond index.max_result_window `from` is rejected outright, so a
                # deep walk has to hand the next page its resume position. The sort
                # values come free from _deterministic_leg_sort().
                last_hit = page_hits[-1][1]["hit"]
                search_after = last_hit.get("sort")

            if next_raw + page_size > OPENSEARCH_MAX_RESULT_WINDOW and search_after is None:
                # Cannot go deeper: `from` is capped and we have no resume values.
                has_more = False
                stopped_by_depth = True
                reason = DepthLimitReason.RESULT_WINDOW
                paginable_total = min(paginable_total, OPENSEARCH_MAX_RESULT_WINDOW)
            else:
                next_cursor = build_cursor(
                    mode=mode,
                    query_fingerprint=query_fingerprint or fingerprint_request(search_request),
                    offset=next_offset,
                    raw_offset=next_raw,
                    window=window_size if mode == PaginationMode.RRF else None,
                    search_after=search_after,
                    # Lets the next page reuse the materialised fused order. Absent
                    # (or stale) just means that page recomputes.
                    ranking_id=ranking_id,
                    ttl_seconds=self.cursor_ttl(),
                )

        if not has_more and not stopped_by_depth and next_raw >= paginable_total:
            reason = DepthLimitReason.EXHAUSTED

        return (
            PageInfo(
                mode=mode,
                offset=page.offset,
                page_size=consumed,
                depth_limit=depth_limit,
                depth_limit_reason=reason,
                window=window_size if mode == PaginationMode.RRF else None,
            ),
            paginable_total,
            has_more,
            next_cursor,
        )

    async def _build_vector_queries(
        self, search_request: DeepSearchSearchRequestV2, window_size: int
    ) -> List[Tuple[Dict[str, Any], str]]:
        """Build vector similarity queries for all requested vector fields.

        Returns (query, embedding_field_name) pairs; the field name identifies the
        VectorFieldConfig whose weight applies to the leg in RRF fusion.
        """
        vector_queries: List[Tuple[Dict[str, Any], str]] = []
        default_embedding_field = "siglip2-embedding.embedding"

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
                (
                    {
                        "nested": {
                            "path": "siglip2-embedding",
                            "score_mode": "max",
                            "inner_hits": {"_source": self._vector_inner_hits_source(search_request)},
                            "_name": "embedding_description",
                            "query": {
                                **self._build_knn_query(
                                    vector_query_type=self._vector_query_score_type,
                                    query_vector=text_embeddings,
                                    embedding_field=default_embedding_field,
                                    space_type="innerproduct",
                                    k=window_size,
                                )
                            },
                        }
                    },
                    default_embedding_field,
                )
            )

        if all_image_embeddings is not None:
            for i, image_embedding in enumerate(all_image_embeddings):
                vector_queries.append(
                    (
                        {
                            "nested": {
                                "path": "siglip2-embedding",
                                "score_mode": "max",
                                "inner_hits": {"_source": self._vector_inner_hits_source(search_request)},
                                "_name": f"embedding_image_similarity_search_{i}",
                                "query": {
                                    **self._build_knn_query(
                                        vector_query_type=self._vector_query_score_type,
                                        query_vector=image_embedding,
                                        embedding_field=default_embedding_field,
                                        space_type="innerproduct",
                                        k=window_size,
                                    )
                                },
                            }
                        },
                        default_embedding_field,
                    )
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
                (
                    {
                        "nested": {
                            "path": nested_path,
                            "score_mode": "max",
                            "inner_hits": {"_source": self._vector_inner_hits_source(search_request)},
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
                    },
                    vector_query.field_name,
                )
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

        # The siglip2-embedding nested field holds the heavy embedding vector plus a
        # lightweight image hash, one entry per thumbnail. Pull only the sub-field each
        # caller needs: the embedding (heavy) for similarity dedup / predictions, and the
        # small image hash for return_images. The embedding vector is also kept out of the
        # vector-leg inner_hits unless explicitly requested (see _vector_inner_hits_source).
        if (
            search_request.similarity_threshold is not None and search_request.similarity_threshold != 0
        ) or search_request.return_predictions:
            includes.append("siglip2-embedding.embedding")
        if search_request.return_images:
            includes.append("siglip2-embedding.image")

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

    def _vector_inner_hits_source(self, search_request: DeepSearchSearchRequestV2) -> Any:
        """The `_source` spec for vector-leg inner_hits.

        Returns False when inner_hits aren't needed at all. Otherwise returns only the
        lightweight fields used for image-hash extraction and score explanations,
        deliberately OMITTING the heavy 1536-d embedding vector — unless the caller
        asked for it via return_embeddings, which is the only consumer of the vector
        from inner_hits. (Similarity-threshold dedup and predictions read the embedding
        from the top-level _source, not inner_hits.) Without this, return_images alone
        forces inner_hits to be returned with the full nested _source, leaking every
        matched view's embedding into the response.

        NOTE: for nested inner_hits OpenSearch resolves _source include paths relative
        to the ROOT document, so the fields MUST be fully-qualified
        ("siglip2-embedding.image", not bare "image") — bare names match nothing and
        the inner _source comes back empty, breaking image-hash extraction.
        """
        if not self.should_fetch_vector_inner_hits(search_request):
            return False
        if search_request.return_embeddings:
            return True
        return [
            "siglip2-embedding.image",
            "siglip2-embedding.keyword",
            "siglip2-embedding.label",
        ]

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
        for prop in (term.strip() for term in lexer):
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

    async def create_bool_filters(self, search_request: SearchFilterFields) -> List[Dict[str, Any]]:
        """Generate boolean filters based on search request parameters.

        Shared by two callers, which is why it takes the narrower
        ``SearchFilterFields`` rather than a full search request: the search path
        drops the result into ``bool.filter``, and the USD-property statistics
        path uses the same clauses to scope its aggregations. Anything added here
        therefore lands on both — see ``SearchFilterFields``.
        """
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
                    or_groups=_normalize_extension_groups(
                        parse_arg_input_and_or(search_request.file_extension_include)
                    ),
                    field_name="ext",
                    case_insensitive=self.search_filter_config.fields_config.get("ext", FieldConfig()).case_insensitive,
                )
            )
        if search_request.file_extension_exclude:
            filters.extend(
                self._create_negative_bool_wildcard_filters_from_or_groups(
                    or_groups=_normalize_extension_groups(
                        parse_arg_input_and_or(search_request.file_extension_exclude)
                    ),
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

        # USD version-range filter, resolved to the matching stored values
        if search_request.filter_by_properties_version:
            filters.extend(await self._version_property_filters(search_request.filter_by_properties_version))

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

    async def _version_property_filters(self, filter_str: str) -> List[Dict[str, Any]]:
        """Resolve version conditions to exact-value filters over each property's stored values."""
        by_property = parse_version_filters(filter_str)
        if len(by_property) > self._version_filter_max_properties:
            raise HTTPException(
                status_code=422,
                detail=f"filter_by_properties_version: {len(by_property)} properties named, at most "
                f"{self._version_filter_max_properties} are allowed per request",
            )
        lookups = await asyncio.gather(
            *(
                self._property_values_cache.get(name, lambda name=name: self._fetch_property_values(name))
                for name in by_property
            )
        )
        filters: List[Dict[str, Any]] = []
        for (name, conditions), stored in zip(by_property.items(), lookups):
            if stored.truncated:
                raise HTTPException(
                    status_code=422,
                    detail=f"filter_by_properties_version: property '{name}' has more than "
                    f"{self._property_values_max_count} distinct values, too many to compare as versions",
                )
            matched = matching_values(stored.values, conditions)
            if not matched:
                # No stored version is in range: the filter must select nothing, not be dropped.
                filters.append({"match_none": {}})
                continue
            filters.append(
                {
                    "nested": {
                        "path": "usd_properties",
                        "query": {
                            "bool": {
                                "must": [
                                    {"term": {"usd_properties.name": name}},
                                    {"terms": {"usd_properties.value": matched}},
                                ]
                            }
                        },
                    }
                }
            )
        return filters

    async def _fetch_property_values(self, name: str) -> PropertyValues:
        """Distinct stored values of one USD property across the whole index (one terms aggregation)."""
        name_clause = {"term": {"usd_properties.name": name}}
        limit = self._property_values_max_count
        body = {
            "size": 0,
            "track_total_hits": False,
            "query": {"nested": {"path": "usd_properties", "query": name_clause}},
            "aggs": {
                "props": {
                    "nested": {"path": "usd_properties"},
                    "aggs": {
                        "named": {
                            "filter": name_clause,
                            "aggs": {
                                "values": {
                                    # One extra bucket tells "exactly at the limit" from "over it".
                                    # "map" groups only the filtered entries instead of loading
                                    # global ordinals for every value of the field.
                                    "terms": {
                                        "field": "usd_properties.value",
                                        "size": limit + 1,
                                        "execution_hint": "map",
                                    }
                                }
                            },
                        }
                    },
                }
            },
        }
        with tracer.start_as_current_span("search_backend.fetch_property_values"):
            response = await self.client.search(index=self.index_name, body=body)
        buckets = response["aggregations"]["props"]["named"]["values"]["buckets"]
        values = tuple(bucket["key"] for bucket in buckets)
        return PropertyValues(values=values[:limit], truncated=len(values) > limit)

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

    async def get_usd_properties_stats(
        self,
        bool_filters: Optional[List[Dict[str, Any]]] = None,
        page_size=10000,
    ) -> StatsResponse:
        """Inventory the USD properties carried by the indexed corpus.

        Args:
            bool_filters: clauses from ``create_bool_filters``, restricting the
                aggregation to the assets they match. An aggregation runs over
                everything the query matched — not over a page of hits — so the
                counts stay exact for whatever subset is selected. ``None`` (the
                default) aggregates over the whole index, which is the original
                behaviour: no ``query`` key is emitted at all.

                Note the scope is the *asset*, not the property: filtering on
                ``class=vehicle`` returns every property those assets carry, not
                just the matching one. That is what makes this usable for
                drill-down.
        """
        # A doc-level filter, so it applies to the parent assets; the nested
        # aggregation below then walks all of their usd_properties.
        query = {"bool": {"filter": bool_filters}} if bool_filters else None

        def _agg_body(agg_name: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
            body = {
                "size": 0,
                "aggs": {
                    "usd_properties_agg": {
                        "nested": {"path": "usd_properties"},
                        "aggs": {
                            agg_name: {
                                "composite": {
                                    "size": page_size,
                                    "sources": sources,
                                }
                            }
                        },
                    }
                },
            }
            if query is not None:
                body["query"] = query
            return body

        # Aggregation bodies:
        keys_agg = _agg_body("all_keys", [{"usd_key": {"terms": {"field": "usd_properties.name"}}}])

        values_agg = _agg_body("all_values", [{"usd_value": {"terms": {"field": "usd_properties.value"}}}])

        kv_agg = _agg_body(
            "kv_pairs",
            [
                {"usd_key": {"terms": {"field": "usd_properties.name"}}},
                {"usd_value": {"terms": {"field": "usd_properties.value"}}},
            ],
        )

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
