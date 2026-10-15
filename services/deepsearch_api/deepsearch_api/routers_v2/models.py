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

import base64
import re
from datetime import datetime
from enum import Enum
from typing import Annotated, Any, List, Optional

from deepsearch_api._constants import IMAGE_MAGIC_TO_MIME
from deepsearch_api.models import Prediction, Prim
from llm_client.validation.validation_fields import (
    ASSET_FACT_NAMES,
    SIMILARITY_SCORE_DESCRIPTION,
)
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    validator,
)

# Request fields naming an asset carry these annotations, which normalize the URL
# to the deployment's internal form during request parsing — so a caller may use
# either the public or the internal spelling, and everything downstream (OpenSearch
# terms, AGS lookups, ACL checks, cache keys) only ever sees the internal one. All
# no-ops unless URL mapping is configured; see ``search_utils.url_mapping`` and
# ``docs/configuration-map.md``. Re-exported here because the v3 routers
# import them from this module alongside the request models they annotate.
from search_utils.url_mapping import (  # noqa: F401
    AssetUrl,
    AssetUrlList,
    AssetUrlOrImage,
    LuceneUrlRegexp,
    get_url_mapper,
)


def _validate_base64_image_str(img: str) -> None:
    """Validate a single base64-encoded image (data URL or bare base64).

    Raises ``ValueError`` for malformed base64 or bytes that don't carry a
    known image magic number (JPEG/PNG/GIF). Callers that accept
    ``omniverse://`` / ``s3://`` reference passthrough must screen those out
    before calling this — it treats every input as an inline image payload.
    """
    if img.startswith("data:image/"):
        # Extract the base64 part from the data URL.
        match = re.match(r"^data:image/[a-zA-Z]+;base64,(.+)$", img)
        if not match:
            raise ValueError("Invalid data URL format for image")
        base64_str = match.group(1)
    else:
        base64_str = img

    try:
        decoded = base64.b64decode(base64_str)
    except base64.binascii.Error:
        raise ValueError("Invalid base64 encoding")

    # Reject bytes that don't start with a known image magic number.
    if not any(decoded.startswith(magic) for magic in IMAGE_MAGIC_TO_MIME.keys()):
        raise ValueError("Invalid image format. Must be JPEG, PNG, or GIF")


class SearchMethod(str, Enum):
    EXACT = "exact"
    APPROXIMATE = "approximate"


class Metadata(BaseModel):
    created: Optional[str]
    created_by: Optional[str]
    modified: Optional[str]
    modified_by: Optional[str]
    size: Optional[float]
    etag: Optional[str]


class SearchFilterFields(BaseModel):
    """The set-selecting parameters shared by search and USD-property statistics.

    Every field here narrows *which assets* a request is about; nothing here
    ranks results or shapes the response. That split is load-bearing, because it
    lets one definition drive two different things: the ``bool.filter`` clauses
    of a search query, and the document set that
    ``GET /search/stats/usd_properties`` aggregates over. Both go through
    ``SearchBackendClientV2._create_bool_filters``, which accepts any model
    carrying these fields.

    So: a field added here becomes a statistics filter automatically. Ranking-only
    parameters (text/vector queries, thresholds) and response-only parameters
    (``return_*``, ``limit``) belong on the request models that inherit from this
    one — putting them here would silently widen the statistics surface.

    ``examples`` are values only. The stats endpoint binds this model as query
    parameters, and FastAPI does not emit the named ``summary``/``value``
    ``parameter.examples`` form for model-bound query params — only schema-level
    examples survive. ``GET /search`` declares its own richer ``openapi_examples``
    inline; the two are independent.

    Parameter groups:
    - File filters: file_name, file_extension_include/exclude, search_path, file_size_*
    - Date filters: created_after/before, modified_after/before (ISO format: YYYY-MM-DD)
    - User filters: created_by, modified_by (+ exclude_* counterparts)
    - USD filters: filter_by_properties, filter_by_properties_numeric, min/max_bbox_*, filter_by_tags
    - Scene scope: search_in_scene (resolved to an asset list via the Asset Graph Service)
    """

    file_name: Optional[str] = Field(
        default=None,
        description="Filter results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
        examples=["robot.usd", "*scene*"],
    )
    exclude_file_name: Optional[str] = Field(
        default=None,
        description="Exclude results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
        examples=["draft*", "*temp*"],
    )
    file_extension_include: Optional[str] = Field(
        default=None,
        description="Filter results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
        examples=["usd", "usd*", "jpg,png,gif"],
    )
    file_extension_exclude: Optional[str] = Field(
        default=None,
        description="Exclude results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
        examples=["jpg", "jpg,png,gif", "mdl"],
    )
    created_after: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created after a specified date",
        examples=["2023-01-01", "2023-06-01"],
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    created_before: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created before a specified date",
        examples=["2023-01-01", "2023-06-01"],
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    modified_after: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified after a specified date",
        examples=["2023-02-01", "2023-07-01"],
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    modified_before: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified before a specified date",
        examples=["2023-02-01", "2023-07-01"],
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    file_size_greater_than: Optional[str] = Field(
        default=None,
        description="Filter results to only include files larger than a specific size",
        pattern=r"^\d+[KMGT]B$",
        examples=["1KB", "10MB"],
    )
    file_size_less_than: Optional[str] = Field(
        default=None,
        description="Filter results to only include files smaller than a specific size",
        pattern=r"^\d+[KMGT]B$",
        examples=["100MB", "1GB"],
    )
    created_by: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created by a specific user. In case AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
        examples=["ov_user"],
    )
    exclude_created_by: Optional[str] = Field(
        default=None,
        description="Exclude assets created by a specific user from the results",
        examples=["ov_user"],
    )
    modified_by: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified by a specific user. In the case, when AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
        examples=["ov_user"],
    )
    exclude_modified_by: Optional[str] = Field(
        default=None,
        description="Exclude assets modified by a specific user from the results",
        examples=["ov_user"],
    )
    search_path: Optional[str] = Field(
        default=None,
        description=(
            "Limit search to assets within this directory path on the storage backend. Do NOT include the "
            "storage backend URL prefix (e.g., use '/Projects/Vehicles/' not "
            "'omniverse://server/Projects/Vehicles/'). Supports wildcards: `*` for any characters, `?` for "
            "single character. Note: the path is always interpreted against the asset's internal storage "
            "URL. If this deployment publishes rewritten (e.g. `https://`) asset URLs, a path segment that "
            "only exists in the rewritten form will not match."
        ),
        examples=["/Projects/Vehicles/", "/Samples/*"],
    )
    exclude_search_path: Optional[str] = Field(
        default=None,
        description="Exclude assets within this directory path. Same format as search_path — do NOT include the storage backend URL prefix. Supports wildcards: `*` for any characters, `?` for single character.",
        examples=["/Projects/Archive/", "*/tmp/*"],
    )
    filter_url_regexp: Optional[LuceneUrlRegexp] = Field(
        default=None,
        description=(
            "Specify an asset URL filter in the "
            "[Lucene Regexp format](https://www.elastic.co/guide/en/elasticsearch/reference/5.6/"
            "query-dsl-regexp-query.html#regexp-syntax). The pattern is matched against the asset's "
            "**internal** storage URL. If this deployment publishes rewritten asset URLs (e.g. `https://` "
            "instead of `s3://`), a pattern that *begins with a literal* rewritten prefix is translated for "
            "you — including inside a whole-pattern exclusion, `~(<prefix>temp/.*)`. A pattern that "
            "expresses that prefix as a pattern rather than a literal is not, and will match nothing. When "
            "in doubt, write the pattern without a scheme/host prefix (e.g. `.*[/]Vehicles[/].*`), which "
            "works either way."
        ),
        examples=[".*[/]Vehicles[/].*", "~(.*[/]temp[/].*)"],
    )
    search_in_scene: Optional[AssetUrl] = Field(
        default=None,
        description="Conduct the search within a specific scene. Provide the full URL for the asset including the storage backend URL prefix.",
        examples=["s3://bucket-name/Project/scene.usd"],
    )
    filter_by_properties: Optional[str] = Field(
        default=None,
        description="Filter assets by USD attributes where at least one root prim matches ALL listed conditions (AND logic). Format: `key=value` pairs comma-separated. Use `=~` prefix on value for wildcard matching. Examples: `class=vehicle` (exact), `class=~*vehicle*` (wildcard), `class=vehicle,material=metal` (both must match). Only a subset of indexed attributes is searchable.",
        examples=["class=vehicle", "class=~*vehicle*", "class=vehicle,material=metal"],
    )
    filter_by_properties_include_any: Optional[str] = Field(
        default=None,
        description="Filter assets by USD attributes using OR logic — an asset matches if ANY of the listed property conditions match. Same format as filter_by_properties: `key=value` for exact, `key=~*pattern*` for wildcard. Example: `class=car,class=truck` matches assets with either class.",
        examples=["class=car,class=truck"],
    )
    exclude_filter_by_properties: Optional[str] = Field(
        default=None,
        description="Exclude assets by USD attributes where at least one root prim matches (note: only supported for a subset of attributes indexed). Format: `attribute1=abc,attribute2=456` for exact matches or `*attribute1*=~*abc*,*attribute2*=~*456*` for wildcard matches",
        examples=["class=vehicle", "class=~*draft*"],
    )
    filter_by_properties_numeric: Optional[str] = Field(
        default=None,
        description="Filter assets by numeric USD attributes with comparison operators. Format: `property>value,property<=value`. Supported operators: `>`, `>=`, `<`, `<=`, `=`. Example: `physics:mass>1.0,physics:density<=500`",
        examples=["physics:mass>1.0", "physics:mass>1.0,physics:density<=500"],
    )
    filter_by_tags: Optional[str] = Field(
        default=None,
        description="Filter assets by tags. Format: `tag1=,=value2,tag3=value3`",
        examples=["reviewed=", "=production", "status=approved"],
    )
    min_bbox_x: Optional[float] = Field(
        default=None,
        description="Filter by minimum X axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
        examples=[1.0],
    )
    min_bbox_y: Optional[float] = Field(
        default=None,
        description="Filter by minimum Y axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
        examples=[1.0],
    )
    min_bbox_z: Optional[float] = Field(
        default=None,
        description="Filter by minimum Z axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
        examples=[1.0],
    )
    max_bbox_x: Optional[float] = Field(
        default=None,
        description="Filter by maximum X axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
        examples=[100.0],
    )
    max_bbox_y: Optional[float] = Field(
        default=None,
        description="Filter by maximum Y axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
        examples=[100.0],
    )
    max_bbox_z: Optional[float] = Field(
        default=None,
        description="Filter by maximum Z axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
        examples=[100.0],
    )
    bbox_use_scaled_dimensions: bool = Field(
        default=True, description="Use scaled dimensions for bounding box filtering"
    )
    vision_metadata: Optional[str] = Field(
        default=None,
        description="Uses a keyword match query on metadata fields that were generated using Vision Language Models. Format: `attribute1=abc,attribute2=456`",
        examples=["material=metal", "color=red,style=modern"],
    )

    @field_validator("created_before", "created_after", "modified_before", "modified_after")
    @classmethod
    def validate_date_format(cls, v):
        if v is not None:
            v_str = str(v)
            try:
                # Try ISO format first (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
                datetime.fromisoformat(v_str)
            except ValueError:
                # Try YYYYMMDD format
                if len(v_str) == 8 and v_str.isdigit():
                    try:
                        datetime.strptime(v_str, "%Y%m%d")
                    except ValueError:
                        raise ValueError("Invalid date format. Expected ISO format (YYYY-MM-DD) or YYYYMMDD")
                else:
                    raise ValueError("Invalid date format. Expected ISO format (YYYY-MM-DD) or YYYYMMDD")
        return v

    @validator(
        "min_bbox_x",
        "min_bbox_y",
        "min_bbox_z",
        "max_bbox_x",
        "max_bbox_y",
        "max_bbox_z",
        pre=True,
    )
    @classmethod
    def must_not_be_boolean(cls, v: Optional[float]) -> Optional[float]:
        if isinstance(v, bool):
            raise ValueError("Boolean received for a float value")
        return v


class UsdPropertyStatsFilters(SearchFilterFields):
    """Optional filters narrowing ``GET /search/stats/usd_properties``.

    Bound as query parameters, so a caller who passes none gets the whole-corpus
    inventory exactly as before. ``extra="forbid"`` is deliberate: the statistics
    are computed by an OpenSearch aggregation over the *matched set*, which has
    no notion of ranking, so a search-only parameter (``description``,
    ``vector_queries``, ``limit``, …) cannot be honoured here. Rejecting it with
    a 422 is far kinder than silently returning corpus-wide numbers the caller
    would read as filtered — and it catches typos in filter names too.
    """

    model_config = ConfigDict(extra="forbid")


class DeepSearchSearchRequest(SearchFilterFields):
    """Base search request for the USD Search API.

    Supports text-based AI search, image similarity search, and extensive filtering by
    file metadata, dates, USD properties, dimensions, and tags. For best results, use via
    DeepSearchSearchRequestV2 with the POST /search_hybrid endpoint, combining
    hybrid_text_query + vector_queries for semantic + keyword matching.

    The filters themselves live on ``SearchFilterFields``, which this shares with
    the USD-property statistics endpoint.

    Key parameter groups:
    - Text/Semantic search: description (legacy) OR hybrid_text_query + vector_queries (preferred, on V2 request)
    - Image search: image_similarity_search (base64, data URL, or asset URL)
    - File filters: file_name, file_extension_include/exclude, search_path, file_size_*
    - Date filters: created_after/before, modified_after/before (ISO format: YYYY-MM-DD)
    - USD filters: filter_by_properties, filter_by_properties_numeric, min/max_bbox_*, filter_by_tags
    - Response control: return_images, return_metadata, return_root_prims, return_predictions, limit
    """

    description: Optional[str] = Field(
        default=None,
        description="Legacy text search query using AI-powered semantic matching. For new integrations, prefer hybrid_text_query on DeepSearchSearchRequestV2 (POST /search_hybrid) which combines text+vector search for better results.",
    )
    image_similarity_search: Optional[AssetUrlOrImage] = Field(
        default=None,
        description="Find visually similar assets by providing reference images. Accepts base64-encoded images (JPEG/PNG/GIF), data URLs (data:image/jpeg;base64,...), or asset URLs (omniverse:// or s3://). Up to 10 images. Can be combined with text search for multimodal queries.",
        max_length=10,
    )
    similarity_threshold: Optional[float] = Field(
        default=None,
        description="Deduplication threshold using embedding cosine distance. Assets with cosine distance below this value are considered duplicates — only the highest-scoring one is returned. Range [0, 2]. Typical values: 0.1 for light dedup, 0.3 for aggressive dedup, None to disable.",
        le=2,
        ge=0,
    )
    cutoff_threshold: Optional[float] = Field(
        default=None,
        description="Minimum raw engine score for VECTOR search legs only (text/keyword legs are "
        "never cut off). Applied per leg BEFORE Reciprocal Rank Fusion, so a cut hit can still "
        "appear if another leg ranks it. The scale is the engine's transformed score, not plain "
        "cosine: for innerproduct kNN over normalized SigLIP2 embeddings OpenSearch maps "
        "ip >= 0 to 1 + ip, so the useful range is roughly 1.0 (orthogonal) to 2.0 (identical); "
        "values below 1.0 are effectively no-ops. Leave unset to keep every vector hit.",
        ge=0,
    )
    return_images: bool = Field(
        default=False,
        description="Return base64-encoded thumbnail images for each result. Recommended: true for visual inspection of search results.",
    )
    return_metadata: bool = Field(
        default=False,
        description="Return file metadata (created/modified dates, user, size, etag) for each result",
    )
    return_root_prims: bool = Field(
        default=False,
        description="Return USD root prim data (type, bounding box, properties) for each result. Provides scene structure information.",
    )
    return_default_prims: bool = Field(
        default=False,
        description="Return USD default prim data for each result. The default prim is the entry point when referencing this asset.",
    )
    return_predictions: bool = Field(
        default=False,
        description="Return ML model predictions (object classification, segmentation) for each result",
    )
    return_in_scene_instances_prims: bool = Field(
        default=False,
        description="[In-scene search only] Return prims of instances of objects found in the scene when using search_in_scene. Only meaningful when search_in_scene is set.",
    )
    embedding_knn_search_method: Optional[SearchMethod] = Field(
        default=None,
        description="Vector search method: 'exact' (brute-force, more accurate, slower) or 'approximate' (HNSW, faster, may miss some results). Default is exact. Use approximate for large-scale exploratory searches.",
    )
    limit: int = Field(
        default=32,
        description="Maximum number of results to return (1-10000, default 32). Use 20-50 for initial exploration, 100+ for exhaustive search. Higher limits increase response time.",
        gt=0,
        le=10000,
    )
    return_vision_generated_metadata: bool = Field(
        default=False,
        description="Returns the metadata fields that were generated using Vision Language Models",
    )
    return_inner_hits: bool = Field(
        default=False,
        description="Return inner hits from nested queries for debugging and detailed scoring",
    )
    return_tags: bool = Field(default=False, description="Return tags for search results")
    validate_results: bool = Field(default=False, description="Validate results with VLM")
    offset: int = Field(
        default=0,
        description=(
            "Number of results to skip — the simple, stateless way to reach page N. Prefer `cursor` from the "
            "previous response: it pins the ranking window so results stay consistent between pages, and it is "
            "the only way past OpenSearch's 10000-result window. How deep `offset` may go depends on the query "
            "shape: filter-only queries (no text/image/vector) are unbounded, a text query is capped by the "
            "deployment's pagination_max_offset, and a multi-leg (hybrid) query is capped by the RRF fusion "
            "window. Cannot be combined with validate_results=true."
        ),
        ge=0,
    )
    cursor: Optional[str] = Field(
        default=None,
        description=(
            "Opaque cursor from the previous response's `next_cursor` (v3) or `X-Next-Cursor` header (v2). "
            "Takes precedence over `offset`. The query must stay identical while paging — changing it "
            "invalidates the cursor with a 400 rather than silently re-ranking. Page size (`limit`) and the "
            "`return_*` response flags may change freely mid-walk. Cannot be combined with validate_results=true."
        ),
    )

    @field_validator("image_similarity_search")
    @classmethod
    def validate_base64_images(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v

        for img in v:
            if img.startswith("omniverse://") or img.startswith("s3://"):
                continue
            _validate_base64_image_str(img)

        return v

    class Config:
        schema_extra = {
            "example": {
                "description": "pallet",
                "return_metadata": True,
                "limit": 16,
            }
        }


class QueryRelevanceValidationResult(BaseModel):
    """VLM validation result for a search result."""

    is_match: bool = Field(..., description="Whether the result matches the query")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in the decision (0-1)")
    similarity_score: float = Field(..., ge=0, le=100, description=SIMILARITY_SCORE_DESCRIPTION)
    reasoning: str = Field(..., description="Explanation of the validation decision")
    model: Optional[str] = Field(
        default=None,
        description=(
            "Identifier of the VLM service+model that produced this verdict. Returned so "
            "clients can cache verdicts under a model-aware key — when the server-side "
            "model changes, cached entries become misses and re-validation runs."
        ),
    )


class ValidationQuery(BaseModel):
    """The query a validation judges against: text, an image, or both."""

    query_text: Optional[str] = Field(default=None, description="Text query to validate against")
    query_image: Optional[str] = Field(default=None, description="Base64 image query to validate against")

    @model_validator(mode="after")
    def validate_query(self) -> "ValidationQuery":
        # Strip the text once (the cache key, the prompt and the facts see the same text); whitespace-only
        # is absent: it carries no signal and would otherwise reach the VLM verbatim.
        if self.query_text is not None:
            self.query_text = self.query_text.strip() or None
        if not self.query_text and not self.query_image:
            raise ValueError("At least one of query_text or query_image must be provided")
        return self


class ValidateResultItem(BaseModel):
    """One asset to validate: one image reference or raw images, plus its facts."""

    asset_url: Optional[AssetUrl] = Field(
        default=None,
        description="Asset URL to validate (mutually exclusive with image_key/image_keys)",
    )
    image_key: Optional[str] = Field(
        default=None,
        description="Single image key to validate (mutually exclusive with asset_url/image_keys)",
    )
    image_keys: Optional[List[str]] = Field(
        default=None,
        description=(
            "List of image keys for multiple views of the asset. The deployment's view "
            "budget applies (USDSEARCH_VISION_VALIDATION_MAX_IMAGES_PER_VALIDATION); "
            "requests exceeding it are rejected with 400. "
            "Mutually exclusive with asset_url/image_key."
        ),
    )
    images: Optional[List[str]] = Field(
        default=None,
        description=(
            "Raw base64-encoded images (data URL or bare base64) to validate directly. "
            "When provided, the server validates these images as-is and does NOT fetch "
            "anything from the index. Mutually exclusive with asset_url/image_key/image_keys. "
            "The deployment view budget (USDSEARCH_VISION_VALIDATION_MAX_IMAGES_PER_VALIDATION) "
            "applies."
        ),
    )
    path: Optional[str] = Field(
        default=None,
        description="The asset's file path (its search hit's source.path): a text query's logprob judge reads it "
        'when USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_FACTS lists "path". Omit the facts to judge the image alone.',
    )
    vlm_metadata_caption: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("vlm_metadata_caption", "caption"),
        description="The asset's vision-metadata caption: read when USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_FACTS "
        'lists "vlm_metadata_caption" (`caption` accepted too).',
    )

    @field_validator("images")
    @classmethod
    def validate_raw_images(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for img in v:
            # This field is the inline-image escape hatch; references belong in asset_url.
            # `looks_public` also catches a rewritten (e.g. https://) asset URL, so that
            # gets the same actionable message instead of "invalid base64".
            if img.startswith("omniverse://") or img.startswith("s3://") or get_url_mapper().looks_public(img):
                raise ValueError(
                    "images must be raw base64-encoded images (or data URLs), not "
                    "omniverse:// / s3:// references; use asset_url for references"
                )
            _validate_base64_image_str(img)
        return v

    @model_validator(mode="after")
    def validate_reference(self) -> "ValidateResultItem":
        reference_sources = [self.asset_url, self.image_key, self.image_keys]
        has_raw_images = bool(self.images)
        # Raw images and index references are two different ways to name the asset
        # image, so allowing both is ambiguous — reject it explicitly.
        if has_raw_images and any(reference_sources):
            raise ValueError(
                "Raw images cannot be combined with asset_url/image_key/image_keys; "
                "provide either raw images or one image reference, not both"
            )
        reference_count = sum(1 for s in reference_sources if s)
        if reference_count == 0 and not has_raw_images:
            raise ValueError("At least one of asset_url, image_key, image_keys, or images must be provided")
        if reference_count > 1:
            raise ValueError("Only one of asset_url, image_key, or image_keys should be provided")
        # Normalize image_key to image_keys for uniform downstream handling
        if self.image_key:
            self.image_keys = [self.image_key]
            self.image_key = None
        return self

    def asset_facts(self) -> dict[str, Optional[str]]:
        """The asset's facts by name, for the logprob judge (logprob_asset_facts)."""
        return {name: getattr(self, name) for name in ASSET_FACT_NAMES}


class ValidateResultRequest(ValidateResultItem, ValidationQuery):
    """Request body for single-result VLM validation endpoint."""


BATCH_VALIDATE_MAX_ITEMS = 100


class BatchValidateItem(ValidateResultItem):
    """One result of a batch: a single-result request's asset fields, plus the caller's id."""

    id: str = Field(..., min_length=1, description="The caller's id for this result, echoed on its result")


class BatchValidateRequest(ValidationQuery):
    """Request body for batch validation: a page of results judged against one query."""

    stream: bool = Field(
        default=True,
        description="true (default): one NDJSON line per result as it lands; false: one JSON answer at the end.",
    )
    items: List[BatchValidateItem] = Field(
        ...,
        min_length=1,
        max_length=BATCH_VALIDATE_MAX_ITEMS,
        description="The results to judge, in display order: they are judged in this order.",
    )


class BatchValidateResult(BaseModel):
    """One result of a batch: its verdict, or why it has none."""

    id: str
    verdict: Optional[QueryRelevanceValidationResult] = None
    error: Optional[str] = None


class BatchValidateResponse(BaseModel):
    """A batch's results (stream=false), in the order they landed."""

    results: List[BatchValidateResult]
    completed: int
    errored: int


class SearchResult(BaseModel):
    url: str = Field(..., description="URL of the asset")
    score: float
    embed: Optional[str] = None
    root_prims: Optional[List[Prim]] = None
    default_prims: Optional[List[Prim]] = None
    image: Optional[str] = None
    predictions: Optional[List[Prediction]] = None
    vision_generated_metadata: Optional[dict[str, Any]] = None
    tags: Optional[list[dict[str, Any]]] = None
    metadata: Optional[Metadata] = None
    in_scene_instance_prims: Optional[List[Prim]] = None
    usd_dimensions: Optional[dict] = Field(None, description="USD asset bounding box dimensions")
    query_relevance: Optional[QueryRelevanceValidationResult] = Field(
        None, description="VLM validation result when validate=True"
    )

    class Config:
        schema_extra = {
            "examples": [
                {
                    "url": "omniverse://sample-nucleus-server.example.com/Projects/sample-usd-asset.usd",
                    "score": 1.2529583,
                    "root_prims": [
                        {
                            "scene_url": "omniverse://sample-nucleus-server.example.com/Projects/sample-usd-asset.usd",
                            "usd_path": "/RootNode",
                            "prim_type": "Xform",
                            "bbox_max": [
                                0.34971755743026733,
                                0.2549635171890259,
                                0.5211517214775085,
                            ],
                            "bbox_min": [
                                -0.34971755743026733,
                                -0.25496378540992737,
                                1.9483268332010084e-8,
                            ],
                            "bbox_midpoint": [
                                0,
                                -1.341104507446289e-7,
                                0.26057587048038844,
                            ],
                            "bbox_dimension_x": 0.6994351148605347,
                            "bbox_dimension_y": 0.5099273025989532,
                            "bbox_dimension_z": 0.5211517019942402,
                            "properties": {
                                "semantic:QWQQ:params:semanticData": "Q1395006",
                                "semantic:QWQL:params:semanticType": "class",
                                "semantic:QWQQ:params:semanticType": "qcode",
                                "semantic:QWQC:params:semanticData": "container/product packaging/box/cardboard box",
                                "semantic:QWQL:params:semanticData": "cardboard box",
                                "semantic:QWQC:params:semanticType": "hierarchy",
                            },
                        }
                    ],
                    "metadata": {
                        "created": "Mon Mar 20 22:06:58 2023",
                        "created_by": "user@nvidia.com",
                        "modified": "Mon Mar 20 22:06:58 2023",
                        "modified_by": "user@nvidia.com",
                        "size": 14938,
                        "etag": "169176",
                    },
                    "vision_generated_metadata": {
                        "vision_generated_object_type": "electric guitar, musical instrument, guitar",
                        "vision_generated_materials": "wood, metal, plastic",
                    },
                }
            ]
        }


class VerifyAccessRequest(BaseModel):
    urls: Annotated[AssetUrlList, Field(..., description="List of URLs to check access for")]
