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

from deepsearch_api._constants import IMAGE_MAGIC_TO_MIME, MAX_IMAGES_PER_VALIDATION
from deepsearch_api.models import Prediction, Prim
from pydantic import BaseModel, Field, field_validator, model_validator, validator


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


class DeepSearchSearchRequest(BaseModel):
    """Base search request for the USD Search API.

    Supports text-based AI search, image similarity search, and extensive filtering by
    file metadata, dates, USD properties, dimensions, and tags. For best results, use via
    DeepSearchSearchRequestV2 with the POST /search_hybrid endpoint, combining
    hybrid_text_query + vector_queries for semantic + keyword matching.

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
    image_similarity_search: Optional[List[str]] = Field(
        default=None,
        description="Find visually similar assets by providing reference images. Accepts base64-encoded images (JPEG/PNG/GIF), data URLs (data:image/jpeg;base64,...), or asset URLs (omniverse:// or s3://). Up to 10 images. Can be combined with text search for multimodal queries.",
        max_length=10,
    )
    file_name: Optional[str] = Field(
        default=None,
        description="Filter results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
    )
    exclude_file_name: Optional[str] = Field(
        default=None,
        description="Exclude results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
    )
    file_extension_include: Optional[str] = Field(
        default=None,
        description="Filter results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
    )
    file_extension_exclude: Optional[str] = Field(
        default=None,
        description="Exclude results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
    )
    created_after: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created after a specified date",
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    created_before: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created before a specified date",
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    modified_after: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified after a specified date",
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    modified_before: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified before a specified date",
        # pattern=r"^\d{4}-\d{2}-\d{2}$",
    )
    file_size_greater_than: Optional[str] = Field(
        default=None,
        description="Filter results to only include files larger than a specific size",
        pattern=r"^\d+[KMGT]B$",
    )
    file_size_less_than: Optional[str] = Field(
        default=None,
        description="Filter results to only include files smaller than a specific size",
        pattern=r"^\d+[KMGT]B$",
    )
    created_by: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets created by a specific user. In case AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
    )
    exclude_created_by: Optional[str] = Field(
        default=None,
        description="Exclude assets created by a specific user from the results",
    )
    modified_by: Optional[str] = Field(
        default=None,
        description="Filter results to only include assets modified by a specific user. In the case, when AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
    )
    exclude_modified_by: Optional[str] = Field(
        default=None,
        description="Exclude assets modified by a specific user from the results",
    )
    similarity_threshold: Optional[float] = Field(
        default=None,
        description="Deduplication threshold using embedding cosine distance. Assets with cosine distance below this value are considered duplicates — only the highest-scoring one is returned. Range [0, 2]. Typical values: 0.1 for light dedup, 0.3 for aggressive dedup, None to disable.",
        le=2,
        ge=0,
    )
    cutoff_threshold: Optional[float] = Field(
        default=None,
        description="Minimum embedding similarity score required for results. Results below this threshold are excluded. Use to filter out low-relevance matches. Typical range depends on query type.",
        ge=0,
    )
    search_path: Optional[str] = Field(
        default=None,
        description="Limit search to assets within this directory path on the storage backend. Do NOT include the storage backend URL prefix (e.g., use '/Projects/Vehicles/' not 'omniverse://server/Projects/Vehicles/'). Supports wildcards: `*` for any characters, `?` for single character.",
    )
    exclude_search_path: Optional[str] = Field(
        default=None,
        description="Exclude assets within this directory path. Same format as search_path — do NOT include the storage backend URL prefix. Supports wildcards: `*` for any characters, `?` for single character.",
    )
    filter_url_regexp: Optional[str] = Field(
        default=None,
        description="Specify an asset URL filter in the [Lucene Regexp format](https://www.elastic.co/guide/en/elasticsearch/reference/5.6/query-dsl-regexp-query.html#regexp-syntax).",
    )
    search_in_scene: Optional[str] = Field(
        default=None,
        description="Conduct the search within a specific scene. Provide the full URL for the asset including the storage backend URL prefix.",
    )
    filter_by_properties: Optional[str] = Field(
        default=None,
        description="Filter assets by USD attributes where at least one root prim matches ALL listed conditions (AND logic). Format: `key=value` pairs comma-separated. Use `=~` prefix on value for wildcard matching. Examples: `class=vehicle` (exact), `class=~*vehicle*` (wildcard), `class=vehicle,material=metal` (both must match). Only a subset of indexed attributes is searchable.",
    )
    filter_by_properties_include_any: Optional[str] = Field(
        default=None,
        description="Filter assets by USD attributes using OR logic — an asset matches if ANY of the listed property conditions match. Same format as filter_by_properties: `key=value` for exact, `key=~*pattern*` for wildcard. Example: `class=car,class=truck` matches assets with either class.",
    )
    exclude_filter_by_properties: Optional[str] = Field(
        default=None,
        description="Exclude assets by USD attributes where at least one root prim matches (note: only supported for a subset of attributes indexed). Format: `attribute1=abc,attribute2=456` for exact matches or `*attribute1*=~*abc*,*attribute2*=~*456*` for wildcard matches",
    )
    filter_by_properties_numeric: Optional[str] = Field(
        default=None,
        description="Filter assets by numeric USD attributes with comparison operators. Format: `property>value,property<=value`. Supported operators: `>`, `>=`, `<`, `<=`, `=`. Example: `physics:mass>1.0,physics:density<=500`",
    )
    filter_by_tags: Optional[str] = Field(
        default=None,
        description="Filter assets by tags. Format: `tag1=,=value2,tag3=value3`",
    )
    min_bbox_x: Optional[float] = Field(
        default=None,
        description="Filter by minimum X axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
    )
    min_bbox_y: Optional[float] = Field(
        default=None,
        description="Filter by minimum Y axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
    )
    min_bbox_z: Optional[float] = Field(
        default=None,
        description="Filter by minimum Z axis dimension of the asset's bounding box of the default prim of the asset",
        ge=0,
    )
    max_bbox_x: Optional[float] = Field(
        default=None,
        description="Filter by maximum X axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
    )
    max_bbox_y: Optional[float] = Field(
        default=None,
        description="Filter by maximum Y axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
    )
    max_bbox_z: Optional[float] = Field(
        default=None,
        description="Filter by maximum Z axis dimension of the asset's bounding box of the default prim of the asset",
        gt=0,
    )
    bbox_use_scaled_dimensions: bool = Field(
        default=True, description="Use scaled dimensions for bounding box filtering"
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
    vision_metadata: Optional[str] = Field(
        default=None,
        description="Uses a keyword match query on metadata fields that were generated using Vision Language Models. Format: `attribute1=abc,attribute2=456`",
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

    @field_validator("image_similarity_search")
    @classmethod
    def validate_base64_images(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v

        for img in v:
            if img.startswith("omniverse://") or img.startswith("s3://"):
                continue

            # Check if it's a data URL
            if img.startswith("data:image/"):
                # Extract the base64 part from data URL
                pattern = r"^data:image/[a-zA-Z]+;base64,(.+)$"
                match = re.match(pattern, img)
                if not match:
                    raise ValueError("Invalid data URL format for image")
                base64_str = match.group(1)
            else:
                base64_str = img

            # Validate base64
            try:
                # Try to decode the base64 string
                decoded = base64.b64decode(base64_str)

                # Reject bytes that don't start with a known image magic number.
                is_valid_image = any(decoded.startswith(magic) for magic in IMAGE_MAGIC_TO_MIME.keys())
                if not is_valid_image:
                    raise ValueError("Invalid image format. Must be JPEG, PNG, or GIF")

            except base64.binascii.Error:
                raise ValueError("Invalid base64 encoding")

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
    similarity_score: int = Field(..., ge=0, le=100, description="Query-asset relevancy score (0-100)")
    reasoning: str = Field(..., description="Explanation of the validation decision")


class ValidateResultRequest(BaseModel):
    """Request body for single-result VLM validation endpoint."""

    asset_url: Optional[str] = Field(
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
            f"List of image keys for multiple views of the asset (up to {MAX_IMAGES_PER_VALIDATION}). "
            "Mutually exclusive with asset_url/image_key."
        ),
        max_length=MAX_IMAGES_PER_VALIDATION,
    )
    query_text: Optional[str] = Field(default=None, description="Text query to validate against")
    query_image: Optional[str] = Field(default=None, description="Base64 image query to validate against")

    @model_validator(mode="after")
    def validate_inputs(self) -> "ValidateResultRequest":
        sources = [self.asset_url, self.image_key, self.image_keys]
        provided = sum(1 for s in sources if s)
        if provided == 0:
            raise ValueError("At least one of asset_url, image_key, or image_keys must be provided")
        if provided > 1:
            raise ValueError("Only one of asset_url, image_key, or image_keys should be provided")
        if not self.query_text and not self.query_image:
            raise ValueError("At least one of query_text or query_image must be provided")
        # Normalize image_key to image_keys for uniform downstream handling
        if self.image_key:
            self.image_keys = [self.image_key]
            self.image_key = None
        return self


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
    urls: Annotated[list[str], Field(..., description="List of URLs to check access for")]
