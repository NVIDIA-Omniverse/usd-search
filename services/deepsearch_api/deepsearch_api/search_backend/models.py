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

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from deepsearch_api.routers_v2.models import (
    DeepSearchSearchRequest,
    QueryRelevanceValidationResult,
)
from deepsearch_api.search_backend.models_extra import AGSAssetData
from pydantic import BaseModel, Field, PrivateAttr, confloat
from pydantic.config import ConfigDict
from pydantic_settings import BaseSettings
from pydantic_settings.main import SettingsConfigDict


class VectorQueryScoreType(str, Enum):
    """Method used to compute vector similarity scores.

    - SCRIPT_SCORE: Exact brute-force cosine similarity. More accurate but slower on large indexes.
    - KNN: Approximate nearest-neighbor search using HNSW. Faster but may miss some results.
    """

    SCRIPT_SCORE = "script_score"
    KNN = "knn"


class TextMatchType(str, Enum):
    """How text queries are matched against field values.

    - EXACT: Case-sensitive exact token match. Use for IDs or known values.
    - FUZZY: Tolerates typos and minor spelling variations. Recommended default for natural language queries.
    - PHRASE: Matches the exact word sequence. Use when word order matters (e.g., "red sports car").
    - PREFIX: Matches tokens starting with the query prefix. Use for autocomplete/typeahead.
    """

    EXACT = "exact"
    FUZZY = "fuzzy"
    PHRASE = "phrase"
    PREFIX = "prefix"


class SearchType(str, Enum):
    """Identifies which search strategy produced a score explanation.

    - TEXT: Keyword/full-text search leg.
    - HYBRID: Combined text + vector search with RRF fusion (the recommended default).
    - FILTER_ONLY: No text/vector query — results are purely from filters.
    - TEXT_TO_VECTOR: Text query converted to embedding for vector search.
    - IMAGE_SIMILARITY: Image-based vector search using visual embeddings.
    - VECTOR: Direct vector search with a pre-computed embedding array.
    """

    TEXT = "text"
    HYBRID = "hybrid"
    FILTER_ONLY = "filter_only"
    TEXT_TO_VECTOR = "text_to_vector"
    IMAGE_SIMILARITY = "image_similarity"
    VECTOR = "vector"


class VectorScore(BaseModel):
    """Detail of a single vector similarity match within an explanation."""

    offset: int = Field(description="Index offset of the matched embedding in the stored array")
    score: float = Field(
        description="Cosine similarity score between query and matched embedding (0-1, higher is more similar)"
    )
    field: str = Field(description="Vector field name that produced this match")
    image: Optional[str] = Field(
        default=None,
        description="Image key/ID associated with this embedding, if the embedding was generated from an image",
    )
    keyword: Optional[List[str]] = Field(default=None, description="Keywords/labels associated with this embedding")
    label: Optional[str] = Field(
        default=None,
        description="Human-readable label for this embedding (e.g., model name or view angle)",
    )


class ScoreExplanation(BaseModel):
    """Explains one scoring component: which search leg matched, on which field, with what score.

    Each search result may have multiple explanations (one per search leg that matched),
    which are then combined via Reciprocal Rank Fusion into the final rrf_score.
    """

    search_type: SearchType = Field(description="Which search strategy produced this score")
    score: float = Field(description="Raw score from this search leg")
    field: str = Field(description="Index field that was matched (e.g., 'name', 'siglip2-embedding.embedding')")
    details: Dict[str, Any] | None = Field(
        default=None, description="Additional scoring details from the search engine"
    )
    rrf_score: float | None = Field(default=None, description="This leg's contribution to the final RRF score")
    rrf_rank_constant: int | None = Field(default=None, description="RRF rank constant (k) used for this leg")
    matched_terms: Optional[List[str]] = Field(default=None, description="Text terms that matched in this field")
    vector_similarity: Optional[float] = Field(
        default=None,
        description="Overall vector cosine similarity for vector search legs",
    )
    matched_vectors: Optional[List[VectorScore]] = Field(
        default=None, description="Individual vector matches with per-embedding scores"
    )


class SearchResultMetadata(BaseModel):
    """Per-result scoring transparency showing how the final rank was computed.

    Contains the full list of score explanations from each search leg, the final
    RRF rank, and the original rank in each individual result set before fusion.
    """

    explanations: List[ScoreExplanation] = Field(
        description="Score breakdowns from each search leg that matched this result"
    )
    rrf_rank: Optional[int] = Field(
        default=None,
        description="Final position in the RRF-ranked result list (1-based)",
    )
    original_ranks: Dict[str, int] = Field(
        default_factory=dict,
        description="Position in each individual search leg's result list before RRF fusion (keyed by search type)",
    )


class SearchResultSource(BaseModel):
    """Indexed document fields for a search result.

    Contains the asset's storage metadata, optional thumbnail image, USD properties,
    and AI-generated metadata depending on which return_* flags were set in the request.
    Extra fields from the search index that are not explicitly modeled are preserved.
    """

    model_config = ConfigDict(extra="allow")

    url: Optional[str] = Field(
        default=None,
        description="Full asset URL on the storage backend (e.g., omniverse://server/path/asset.usd or s3://bucket/key)",
    )
    name: Optional[str] = Field(default=None, description="Asset file name (e.g., 'red_car.usd')")
    path: Optional[str] = Field(default=None, description="Directory path of the asset on the storage backend")
    base_key: Optional[str] = Field(
        default=None,
        description="Canonical storage key used internally for deduplication and image retrieval",
    )
    hash_value: Optional[str] = Field(default=None, description="Content hash for change detection and deduplication")
    created: Optional[str] = Field(default=None, description="Asset creation timestamp from the storage backend")
    modified: Optional[str] = Field(
        default=None,
        description="Asset last-modified timestamp from the storage backend",
    )
    created_by: Optional[str] = Field(
        default=None,
        description="User who created the asset (email or ID depending on backend)",
    )
    modified_by: Optional[str] = Field(default=None, description="User who last modified the asset")
    size: Optional[float] = Field(default=None, description="File size in bytes")
    etag: Optional[str] = Field(default=None, description="Storage backend ETag for cache validation")
    image: Optional[str] = Field(
        default=None,
        description="Base64-encoded thumbnail image. In V2 responses, embedded directly. In V3/hybrid responses, use the separate GET /images?asset_url=<url> endpoint to fetch thumbnails for each result.",
    )
    usd_properties: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="USD attribute key-value pairs from root prims (only populated when return_usd_properties=true)",
    )
    usd_dimensions: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Bounding box dimensions: bbox_dimension_x/y/z in scene units (only populated when return_usd_dimensions=true)",
    )
    tags: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Asset tags as key-value pairs (only populated when return_tags=true)",
    )
    vision_generated_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="AI-generated descriptions and labels from Vision Language Models (e.g., object_type, materials, colors)",
    )

    def get(self, key: str, default=None):
        """Dict-style access for backward compatibility with code that treated source as a dict."""
        return getattr(self, key, default)

    def __getitem__(self, key: str):
        """Dict-style subscript access for backward compatibility."""
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)


class SearchResult(BaseModel):
    """A single search hit from the USD Search index.

    Results are ranked by rrf_score (Reciprocal Rank Fusion) which combines
    text search, vector similarity, and other scoring legs into a single ranking.
    The source field contains the actual asset data; metadata contains scoring transparency.
    """

    id: str = Field(description="Unique document ID in the search index")
    score: float = Field(description="Raw relevance score from the primary search leg")
    rrf_score: float = Field(
        description="Final Reciprocal Rank Fusion score combining all search legs. Higher is better. Range typically 0.0-1.0."
    )
    metadata: SearchResultMetadata = Field(
        description="Scoring transparency: individual search leg scores, RRF rank, and original positions"
    )
    source: SearchResultSource = Field(
        description="Indexed asset data including URL, metadata, thumbnail, USD properties, and AI-generated labels"
    )
    inner_hits: Dict[str, Any] = Field(
        default_factory=dict,
        description="Nested query matches showing which specific sub-document (e.g., USD property or embedding) matched",
    )
    ags_data: AGSAssetData = Field(
        default_factory=AGSAssetData,
        description="Asset Graph Service data: instance prims, root prims, and default prims if the scene has been graph-indexed",
    )
    thumbnail_exists: Optional[bool] = Field(
        default=None,
        description="Whether a pre-rendered thumbnail exists for this asset in the image store",
    )
    query_relevance: Optional[QueryRelevanceValidationResult] = Field(
        default=None,
        description="VLM validation result: match confidence and reasoning (only present when validate_results=true)",
    )


class SearchResponse(BaseModel):
    """Top-level response from the hybrid search endpoint.

    Contains the total number of matching documents, the ranked list of hits
    (limited by the request's limit parameter), and search execution metadata.
    """

    total: int = Field(
        description=(
            "Size of the RRF fusion candidate pool — i.e. the number of distinct documents that survived "
            "client-side reciprocal-rank fusion across all query legs after similarity-threshold filtering. "
            "Bounded by scoring_config.rrf_config.window_size (default 2 * (from + limit), capped at "
            "OpenSearch's index.max_result_window of 10000). This is NOT the corpus match count — see "
            "corpus_total for that."
        )
    )
    corpus_total: Optional[int] = Field(
        default=None,
        description=(
            "Lower-bound estimate of the number of documents in the index matching the query and filters, "
            "computed as max(per-leg OpenSearch total_hits) across all executed legs. Equal to the true "
            "corpus match count for filter-only and single-leg queries; for multi-leg hybrid queries it "
            "underestimates the union when legs disagree (true union is in [max(legs), sum(legs)]). "
            "kNN/vector legs are bounded by window_size and contribute a floor only. May be absent for "
            "back-compat with older clients."
        ),
    )
    hits: List[SearchResult] = Field(
        description="Ranked search results ordered by rrf_score descending, limited by the request's limit parameter"
    )
    search_metadata: Dict[str, Any] = Field(
        description="Search execution metadata including query timing and search method used"
    )


class FieldConfig(BaseModel):
    """Configuration for field-level query behavior."""

    case_insensitive: bool = Field(
        default=True,
        description="Whether wildcard queries on this field ignore case. Recommended: true for asset search.",
    )

    model_config = SettingsConfigDict(env_prefix="field_config_")


class FieldScoreConfig(BaseModel):
    """Configuration for scoring a single text field in hybrid search.

    Controls how text queries match against a specific field and how much weight
    that field contributes to the overall text search score.
    """

    field: str | None = Field(
        default=None,
        description="Field name to search in. Use '__VISION_METADATA_FIELDS__' as a special placeholder for all AI-generated metadata fields (object type, materials, colors, etc.).",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this field participates in text search scoring",
    )
    weight: confloat(ge=0, le=100) = Field(
        default=1.0,
        description="Relative importance of this field (1.0 = normal, 2.0 = double weight). Higher weight means matches in this field rank higher.",
    )
    match_type: TextMatchType = Field(
        default=TextMatchType.FUZZY,
        description="Text matching strategy. FUZZY is recommended for natural language queries as it tolerates typos.",
    )
    analyzer: Optional[str] = Field(
        default=None,
        description="Custom OpenSearch analyzer name. Leave None for default analyzer.",
    )
    fuzzy_max_expansions: Optional[int] = Field(
        default=50,
        description="Maximum number of fuzzy term expansions. Lower values are faster but less tolerant of typos.",
    )
    nested: bool = Field(
        default=False,
        description="Whether this field is nested (e.g., usd_properties.key, usd_properties.value, tags.tag, tags.value)",
    )
    wildcard: bool = Field(
        default=True,
        description="Whether to also run a wildcard query on this field for partial matching",
    )
    match: bool = Field(default=True, description="Whether to run a standard match query on this field")
    case_insensitive: bool = Field(default=True, description="Whether wildcard queries ignore case")


class RRFConfig(BaseModel):
    """Reciprocal Rank Fusion configuration for combining multiple search result lists.

    RRF combines results from text search, vector search, and other legs into a single
    ranked list. The formula for each document is: sum(1 / (k + rank_in_list)) across all lists.
    A higher rank_constant gives more influence to lower-ranked documents.
    """

    rank_constant: int = Field(
        default=60,
        ge=1,
        description="RRF constant factor (k). Determines how much influence lower-ranked documents in individual result sets have on the final ranking. Higher values (e.g., 60) produce smoother fusion; lower values (e.g., 1-10) heavily favor top-ranked results. Recommended: 60 for balanced hybrid search.",
    )
    window_size: Optional[int] = Field(
        default=None,
        ge=1,
        description="Number of top-k documents to consider from each search leg before fusion. None means use all results.",
    )
    query_rank_constants: dict[SearchType | str, int] = Field(
        default_factory=dict,
        description='Override rank_constant for specific search types (e.g., {"text": 30, "vector": 90}). Allows fine-tuning the relative influence of each search leg.',
    )


class HybridTextConfig(BaseSettings):
    """Configuration for the text search leg of hybrid search.

    Controls which fields are searched, how they're weighted, and how matches
    are combined across fields. The text leg runs in parallel with vector search,
    and results are merged via RRF.

    Recommended fields for USD asset search: name, name.simple, name.standard,
    path, usd_properties.value, usd_properties.key, __VISION_METADATA_FIELDS__.
    """

    enabled: bool = Field(
        default=True,
        description="Whether text search is active. Set to false to rely on vector search only.",
    )
    weight: confloat(ge=0, le=100) = Field(
        default=1.0,
        description="Boost factor for text search relative to other legs. Values >1.0 (e.g., 1.2) prioritize text keyword matches over vector similarity. Recommended: 1.0-1.5.",
    )
    fields: List[FieldScoreConfig] = Field(
        default_factory=list,
        description="List of fields to search with individual weights. If empty, server defaults are used. Include '__VISION_METADATA_FIELDS__' for AI-generated descriptions.",
    )
    cross_field_operator: str = Field(
        default="or",
        description="How to combine matches across fields: 'or' (any field matches) or 'and' (all fields must match). Recommended: 'or' for discovery, 'and' for precision.",
    )

    model_config = SettingsConfigDict(env_prefix="hybrid_search_hybrid_text_config_")


class VectorFieldConfig(BaseSettings):
    """Configuration for a single vector search field.

    Currently the only supported vector field is 'siglip2-embedding.embedding'
    (SigLIP2 vision-language embeddings, 1536 dimensions). This enables semantic
    similarity search where query text is encoded into the same embedding space
    as the indexed asset thumbnails.
    """

    enabled: bool = Field(
        default=False,
        description="Whether vector search is active for this field. Set to true to enable semantic similarity.",
    )
    weight: confloat(ge=0, le=100) = Field(
        default=1.0,
        description="Relative weight of this vector field's scores in RRF fusion. Higher values prioritize visual similarity.",
    )
    field_name: str = Field(
        description="Name of the vector field in the search index. Use 'siglip2-embedding.embedding' for SigLIP2 visual embeddings."
    )
    dimension: int = Field(
        description="Dimensionality of the embedding vectors. Must match the index configuration. SigLIP2 uses 1536 dimensions."
    )
    model_name: Optional[str] = Field(
        default=None,
        description="Embedding model identifier used for encoding queries. Leave None to use the server's default encoder.",
    )

    model_config = SettingsConfigDict(env_prefix="hybrid_search_vector_field_config_")


class ScoringConfig(BaseSettings):
    """Controls how text, vector, and hybrid search results are combined via Reciprocal Rank Fusion.

    For most use cases, the defaults work well. Customize when you need to:
    - Boost text keyword matching over visual similarity (increase hybrid_text.weight)
    - Prioritize vector similarity over text (increase vector_fields weight)
    - Enable/disable specific search legs

    Typical configuration for agentic search:
    - rrf_config: rank_constant=60 (default)
    - hybrid_text: enabled=true, weight=1.2, fields=[name(2), name.simple(2), path(1), __VISION_METADATA_FIELDS__(1)]
    - vector_fields: {"siglip2-embedding.embedding": {enabled: true, weight: 1, dimension: 1536}}
    """

    # RRF configuration
    rrf_config: RRFConfig = Field(
        default_factory=RRFConfig,
        description="Reciprocal Rank Fusion parameters for merging results from multiple search legs",
    )

    hybrid_text: HybridTextConfig = Field(
        default_factory=HybridTextConfig,
        description="Text search leg configuration: fields, weights, and matching strategy",
    )

    vector_fields: Dict[str, VectorFieldConfig] = Field(
        default_factory=dict,
        description="Vector search fields configuration. Key is the field name (e.g., 'siglip2-embedding.embedding'), value is the field config with dimension and weight.",
    )

    model_config = SettingsConfigDict(env_prefix="hybrid_search_scoring_config_", extra="allow")


class VectorQueryType(str, Enum):
    """Type of input provided for vector similarity search.

    - TEXT: Natural language text that will be encoded into an embedding by the server (most common).
    - IMAGE: Base64-encoded image or image URL that will be encoded into a visual embedding.
    - VECTOR: Pre-computed embedding as a list of floats (for advanced use when you have your own encoder).
    """

    TEXT = "text"
    IMAGE = "image"
    VECTOR = "vector"


class VectorQuery(BaseModel):
    """A single vector similarity search query.

    Vector queries find assets whose embeddings are close to the query embedding
    in the shared vision-language embedding space. Use query_type='text' for natural
    language descriptions (most common) or 'image' for visual similarity search.
    """

    field_name: str = Field(
        description="Vector field to search in. Use 'siglip2-embedding.embedding' for SigLIP2 visual-language embeddings (1536 dimensions)."
    )
    query_type: VectorQueryType = Field(
        description="Type of query input: 'text' (natural language, converted to embedding), 'image' (base64/URL, converted to visual embedding), or 'vector' (raw float array)."
    )
    query: Union[str, List[float]] = Field(
        description="The query content: a text string (for type 'text'), a base64 image or URL (for type 'image'), or a list of floats (for type 'vector'). For text queries, use SHORT descriptive phrases (2-5 words) for best results with CLIP/SigLIP2 embeddings."
    )


class DeepSearchSearchRequestV2(DeepSearchSearchRequest):
    """Extended search request with hybrid text+vector search and advanced scoring configuration.

    This is the request body for POST /search_hybrid (recommended) and POST /v3/deepsearch/search.
    It extends the base search request with scoring configuration, vector queries, and additional
    response control flags.

    Typical usage for an AI agent:
    1. Set hybrid_text_query to a short descriptive phrase (2-5 words, e.g., "red sports car")
    2. Set vector_queries with the same text using field 'siglip2-embedding.embedding', query_type='text'
    3. Set file_extension_include="usd*" to filter to USD assets only
    4. Set return_images=true for visual inspection and return_metadata=true for file info
    5. Set limit=20-50 for initial exploration, increase if needed
    6. Leave scoring_config as default unless you need to tune ranking behavior
    """

    scoring_config: Optional[ScoringConfig] = Field(
        default_factory=ScoringConfig,
        description="Advanced scoring configuration controlling how text, vector, and filter results are combined via RRF. Leave as default for standard behavior, or customize field weights and RRF parameters for fine-tuned ranking.",
    )
    hybrid_text_query: Optional[str] = Field(
        default=None,
        description="Natural language search query for text-based search across multiple configurable fields (name, path, properties, AI-generated metadata). Use SHORT descriptive phrases (2-5 words) for best results. Combine with vector_queries using the same text for optimal hybrid search.",
    )
    vector_queries: List[VectorQuery] = Field(
        default_factory=list,
        description="Vector similarity queries for semantic search. Typically used with same text as hybrid_text_query for hybrid search: [{field_name: 'siglip2-embedding.embedding', query_type: 'text', query: '<same query>'}]. Multiple queries search different vector fields in parallel.",
    )
    return_embeddings: bool = Field(
        default=False,
        description="Return raw embedding vectors for search results. Useful for client-side similarity computations or caching.",
    )
    return_tags: bool = Field(
        default=False,
        description="Return asset tags (key-value pairs) in the source data for each result",
    )
    return_usd_properties: bool = Field(
        default=False,
        description="Return USD attributes (semantic labels, physics properties, etc.) from root prims for each result",
    )
    return_usd_dimensions: bool = Field(
        default=False,
        description="Return bounding box dimensions (bbox_dimension_x/y/z) for each result. Useful for size-based filtering or layout planning.",
    )
    return_inner_hits: bool = Field(
        default=False,
        description="Return detailed inner hits showing which nested documents matched (e.g., specific embedding offsets or USD property values)",
    )
    deduplicate_by_hash: bool = Field(
        default=False,
        description="Collapse results with identical content hashes, returning only the highest-scoring version. Useful when the same asset exists at multiple paths.",
    )

    class Config:
        json_schema_extra = {
            "examples": [
                {
                    "title": "Minimal hybrid search (recommended starting point)",
                    "hybrid_text_query": "red car vehicle",
                    "vector_queries": [
                        {
                            "field_name": "siglip2-embedding.embedding",
                            "query_type": "text",
                            "query": "red car vehicle",
                        },
                    ],
                    "file_extension_include": "usd*",
                    "return_images": True,
                    "return_metadata": True,
                    "limit": 20,
                },
                {
                    "title": "Image similarity search (find visually similar assets)",
                    "image_similarity_search": [
                        "data:image/jpeg;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC"
                    ],
                    "return_metadata": True,
                    "return_images": True,
                    "deduplicate_by_hash": True,
                    "limit": 20,
                },
                {
                    "title": "Size-constrained search (find objects within specific dimensions)",
                    "hybrid_text_query": "wooden table",
                    "vector_queries": [
                        {
                            "field_name": "siglip2-embedding.embedding",
                            "query_type": "text",
                            "query": "wooden table",
                        },
                    ],
                    "file_extension_include": "usd*",
                    "min_bbox_x": 0.5,
                    "max_bbox_x": 2.0,
                    "min_bbox_y": 0.3,
                    "max_bbox_y": 1.2,
                    "return_usd_dimensions": True,
                    "return_usd_properties": True,
                    "return_images": True,
                    "limit": 30,
                },
                {
                    "title": "Property-filtered search (semantic labels + text)",
                    "hybrid_text_query": "vehicle",
                    "vector_queries": [
                        {
                            "field_name": "siglip2-embedding.embedding",
                            "query_type": "text",
                            "query": "vehicle",
                        },
                    ],
                    "filter_by_properties": "class=vehicle",
                    "file_extension_include": "usd*",
                    "return_usd_properties": True,
                    "return_images": True,
                    "return_metadata": True,
                    "limit": 30,
                },
                {
                    "title": "Advanced hybrid search with custom scoring configuration",
                    "hybrid_text_query": "modern office furniture",
                    "vector_queries": [
                        {
                            "field_name": "siglip2-embedding.embedding",
                            "query_type": "text",
                            "query": "modern office furniture",
                        },
                    ],
                    "file_extension_include": "usd*",
                    "created_after": "2023-01-01",
                    "return_usd_dimensions": True,
                    "return_usd_properties": True,
                    "return_metadata": True,
                    "deduplicate_by_hash": True,
                    "limit": 50,
                    "scoring_config": {
                        "rrf_config": {"rank_constant": 60},
                        "hybrid_text": {
                            "enabled": True,
                            "weight": 1.2,
                            "fields": [
                                {
                                    "field": "name",
                                    "weight": 2,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "name.simple",
                                    "weight": 2,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "name.standard",
                                    "weight": 2,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "usd_properties.value",
                                    "nested": True,
                                    "weight": 1,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "usd_properties.key",
                                    "nested": True,
                                    "weight": 1,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "path",
                                    "weight": 1,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                                {
                                    "field": "__VISION_METADATA_FIELDS__",
                                    "weight": 1,
                                    "match_type": "fuzzy",
                                    "wildcard": True,
                                },
                            ],
                            "cross_field_operator": "or",
                        },
                        "vector_fields": {
                            "siglip2-embedding.embedding": {
                                "enabled": True,
                                "weight": 1,
                                "field_name": "siglip2-embedding.embedding",
                                "dimension": 1536,
                            }
                        },
                    },
                },
            ]
        }

    # Private field to store downloaded images, won't be included in schema or serialization
    _downloaded_images: Dict[str, bytes] = PrivateAttr(default_factory=dict)

    def set_downloaded_image(self, url: str, image_data: bytes):
        """Store downloaded image data for a given URL."""
        self._downloaded_images[url] = image_data

    def get_downloaded_image(self, url: str) -> Optional[bytes]:
        """Get downloaded image data for a given URL."""
        return self._downloaded_images.get(url)
