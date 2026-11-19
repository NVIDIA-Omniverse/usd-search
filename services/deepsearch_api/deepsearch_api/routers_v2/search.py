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
import logging
from typing import Annotated, List, Optional

# local / proprietary modules
from asset_graph_service_client.api_client import ApiClient
from asset_graph_service_client.exceptions import ApiException, NotFoundException
from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.telemetry_decorator import telemetry_track_search

# third party modules
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.params import Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from pydantic import ValidationError

from search_utils.telemetry_utils import SEARCH_TELEMETRY_STDOUT

from ..search_backend import response_models
from ..search_backend.compat import convert_search_response
from ..search_backend.filtered import FilteredSearchClient
from ..search_backend.image_loader import BaseImageLoader
from ..search_backend.main import EmbeddingType, SearchBackendClientV2
from ..search_backend.models import DeepSearchSearchRequestV2, SearchResponse
from ..search_backend.pagination import PaginationError
from ..search_backend.utils import (
    get_default_telemetry_context,
    get_telemetry_extra_fields,
)
from ..validation import SearchResultValidator
from . import dependencies
from .models import (
    QueryRelevanceValidationResult,
    SearchMethod,
    SearchResult,
    UsdPropertyStatsFilters,
)

search_prefix = "deepsearch"
router = APIRouter(
    prefix=f"/{search_prefix}",
    tags=["AI Search"],
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _set_pagination_headers(response: Response, results: SearchResponse) -> None:
    """Expose pagination state on a v2 response.

    Both v2 endpoints return a bare ``List[SearchResult]``: ``convert_search_response``
    flattens the envelope and drops the totals outright, so there is nowhere in the
    body for ``next_cursor``/``has_more``/``paginable_total``, and adding an envelope
    would break every existing client. Headers are purely additive — clients that do
    not know them ignore them.
    """
    if results.next_cursor:
        response.headers["X-Next-Cursor"] = results.next_cursor
    response.headers["X-Has-More"] = "true" if results.has_more else "false"
    if results.paginable_total is not None:
        response.headers["X-Paginable-Total"] = str(results.paginable_total)
    # Browsers hide non-safelisted response headers from cross-origin JavaScript
    # unless they are exposed, so without this a CORS client could not page.
    # Set here rather than in each gateway so every deployment's gateway passes
    # it through (nvbug 6899406).
    response.headers["Access-Control-Expose-Headers"] = ", ".join(PAGINATION_RESPONSE_HEADERS)


# v2 returns a bare array, so pagination cannot ride in the body — it ships as
# response headers. Declared here as well as set at runtime, so the OpenAPI spec
# (and anything generated from it) describes the v2 pagination contract instead
# of only mentioning it in prose.
PAGINATION_RESPONSE_HEADERS = {
    "X-Next-Cursor": {
        "description": "Opaque cursor for the next page. Absent on the last page.",
        "schema": {"type": "string"},
    },
    "X-Has-More": {
        "description": "Whether another page exists (`true`/`false`). Authoritative — a full page does not imply more.",
        "schema": {"type": "string", "enum": ["true", "false"]},
    },
    "X-Paginable-Total": {
        "description": "How many results paging can reach. Not a corpus count; see `paginable_total` on the v3 response.",
        "schema": {"type": "integer"},
    },
}


@router.get(
    "/search",
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "Search results",
            "content": {"application/json": {"example": [SearchResult.Config.schema_extra["examples"][0]]}},
            "headers": PAGINATION_RESPONSE_HEADERS,
        }
    },
)
@telemetry_track_search()
async def search(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    search_backend_v2: Annotated[FilteredSearchClient, Depends(dependencies.search_backend_client_v2)],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    response: Response,
    description: Annotated[
        str,
        Query(
            description="Conduct text-based searches powered by AI",
            openapi_examples={
                "None": {
                    "summary": "No text-based search",
                    "value": None,
                },
                "Find a 'box'": {
                    "summary": "Example search for 'box'",
                    "value": "box",
                },
                "Find a 'pallet'": {
                    "summary": "Example search for 'pallet'",
                    "value": "pallet",
                },
                "Search 'red rusty barrel'": {
                    "summary": "Example search for 'red rusty barrel'",
                    "value": "red rusty barrel",
                },
            },
            max_length=1024,
        ),
    ] = "",
    image_similarity_search: Annotated[
        Optional[List[str]],
        Query(
            description="Perform similarity searches based on a list of images",
            openapi_examples={
                "None": {
                    "summary": "No image similarity search",
                    "value": [],
                },
                "Base64 encoded image example": {
                    "summary": "Base64 encoded image example",
                    "value": [
                        "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC"
                    ],
                },
                "Base64 encoded image with format prefix example": {
                    "summary": "Base64 encoded image with format prefix example",
                    "value": [
                        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC"
                    ],
                },
                "Storage backend URL example": {
                    "summary": "Storage backend URL example",
                    "value": ["s3://bucket-name/Project/asset1.usd"],
                },
            },
        ),
    ] = None,
    file_name: Annotated[
        str,
        Query(
            description="Filter results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Find files named 'robot.usd'": {
                    "summary": "Example to find files matching 'robot.usd'",
                    "value": "robot.usd",
                },
                "Search for 'scene' in filenames": {
                    "summary": "Example to find files partially matching 'scene'",
                    "value": "*scene*",
                },
            },
        ),
    ] = "",
    exclude_file_name: Annotated[
        str,
        Query(
            description="Exclude results by asset file name, allowing partial matches. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Exclude files with 'draft' prefix": {
                    "summary": "Example to exclude files with 'draft' prefix",
                    "value": "draft*",
                },
                "Do not include 'temp' in filenames": {
                    "summary": "Example to exclude files with 'temp' in their names",
                    "value": "*temp*",
                },
            },
        ),
    ] = "",
    file_extension_include: Annotated[
        str,
        Query(
            description="Filter results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Only include 'usd' files": {
                    "summary": "Example to filter for '.usd' files",
                    "value": "usd",
                },
                "Only include 'usd' files (all types)": {
                    "summary": "Example to filter for all types of USD files",
                    "value": "usd*",
                },
                "Search for 'jpg' files": {
                    "summary": "Example to filter for '.jpg' files",
                    "value": "jpg",
                },
                "Search for image files": {
                    "summary": "Example to filter for image files",
                    "value": "jpg,png,gif",
                },
            },
        ),
    ] = "",
    file_extension_exclude: Annotated[
        str,
        Query(
            description="Exclude results by file extension. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Exclude 'jpg' files": {
                    "summary": "Example to exclude '.jpg' files",
                    "value": "jpg",
                },
                "Exclude image files": {
                    "summary": "Example to exclude image files",
                    "value": "jpg,png,gif",
                },
                "Do not include 'mdl' files": {
                    "summary": "Example to exclude '.mdl' files",
                    "value": "mdl",
                },
            },
        ),
    ] = "",
    created_after: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include assets created after a specified date",
            openapi_examples={
                "None": {
                    "summary": "Disable created_after filter",
                    "value": None,
                },
                "After '2023-01-01'": {
                    "summary": "Example to filter assets created after '2023-01-01'",
                    "value": "2023-01-01",
                },
                "Post '2023-06-01'": {
                    "summary": "Example to filter assets created after '2023-06-01'",
                    "value": "2023-06-01",
                },
            },
        ),
    ] = None,
    created_before: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include assets created before a specified date",
            openapi_examples={
                "None": {
                    "summary": "Disable created_before filter",
                    "value": None,
                },
                "Before '2023-01-01'": {
                    "summary": "Example to filter assets created before '2023-01-01'",
                    "value": "2023-01-01",
                },
                "Pre '2023-06-01'": {
                    "summary": "Example to filter assets created before '2023-06-01'",
                    "value": "2023-06-01",
                },
            },
        ),
    ] = None,
    modified_after: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include assets modified after a specified date",
            openapi_examples={
                "None": {
                    "summary": "Disable modified_after filter",
                    "value": None,
                },
                "Modified after '2023-02-01'": {
                    "summary": "Example to filter assets modified after '2023-02-01'",
                    "value": "2023-02-01",
                },
                "Changes post '2023-07-01'": {
                    "summary": "Example to filter assets modified after '2023-07-01'",
                    "value": "2023-07-01",
                },
            },
        ),
    ] = None,
    modified_before: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include assets modified before a specified date",
            openapi_examples={
                "None": {
                    "summary": "Disable modified_before filter",
                    "value": None,
                },
                "Modified before '2023-02-01'": {
                    "summary": "Example to filter assets modified before '2023-02-01'",
                    "value": "2023-02-01",
                },
                "Changes pre '2023-07-01'": {
                    "summary": "Example to filter assets modified before '2023-07-01'",
                    "value": "2023-07-01",
                },
            },
        ),
    ] = None,
    file_size_greater_than: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include files larger than a specific size",
            openapi_examples={
                "None": {
                    "summary": "Disable file size greater than filter",
                    "value": None,
                },
                "Larger than '5MB'": {
                    "summary": "Example to filter files larger than 5MB",
                    "value": "5MB",
                },
                "Above '10MB'": {
                    "summary": "Example to filter files larger than 10MB",
                    "value": "10MB",
                },
            },
            pattern=r"^\d+[KMGT]B$",
        ),
    ] = None,
    file_size_less_than: Annotated[
        Optional[str],
        Query(
            description="Filter results to only include files smaller than a specific size",
            openapi_examples={
                "None": {
                    "summary": "Disable file size less than filter",
                    "value": None,
                },
                "Smaller than '1GB'": {
                    "summary": "Example to filter files smaller than 1GB",
                    "value": "1GB",
                },
                "Under '500MB'": {
                    "summary": "Example to filter files smaller than 500MB",
                    "value": "500MB",
                },
            },
            pattern=r"^\d+[KMGT]B$",
        ),
    ] = None,
    created_by: Annotated[
        str,
        Query(
            description="Filter results to only include assets created by a specific user. In case AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
            # openapi_examples={
            #     "Created by user 'Alex'": {
            #         "summary": "Example to filter assets created by user 'Alex'",
            #         "value": "alex",
            #     },
            #     "Creator is 'Jordan'": {
            #         "summary": "Example to filter assets created by user 'Jordan'",
            #         "value": "jordan",
            #     },
            # },
        ),
    ] = "",
    exclude_created_by: Annotated[
        str,
        Query(
            description="Exclude assets created by a specific user from the results",
            openapi_examples={
                "Exclude creations by 'Alex'": {
                    "summary": "Example to exclude assets created by 'Alex'",
                    "value": "alex",
                },
                "Not from 'Jordan'": {
                    "summary": "Example to exclude assets created by 'Jordan'",
                    "value": "jordan",
                },
            },
        ),
    ] = "",
    modified_by: Annotated[
        str,
        Query(
            description="Filter results to only include assets modified by a specific user. In the case, when AWS S3 bucket is used as a storage backend, this field corresponds to the owner's ID. In case of an Omniverse Nucleus server, this field may depend on the configuration, but typically corresponds to user email.",
            # openapi_examples={
            #     "Modified by 'Chris'": {
            #         "summary": "Example to filter assets modified by 'Chris'",
            #         "value": "chris",
            #     },
            #     "Changes by 'Pat'": {
            #         "summary": "Example to filter assets modified by 'Pat'",
            #         "value": "pat",
            #     },
            # },
        ),
    ] = "",
    exclude_modified_by: Annotated[
        str,
        Query(
            description="Exclude assets modified by a specific user from the results",
            openapi_examples={
                "Exclude changes by 'Chris'": {
                    "summary": "Example to exclude assets modified by 'Chris'",
                    "value": "Chris",
                },
                "Not modified by 'Pat'": {
                    "summary": "Example to exclude assets modified by 'Pat'",
                    "value": "Pat",
                },
            },
        ),
    ] = "",
    similarity_threshold: Annotated[
        Optional[float],
        Query(
            description="Set the similarity threshold for embedding-based searches. This functionality allows filtering duplicates and returning only those results that are different from each other. Assets are considered to be duplicates if the cosine distance betwen the embeddings a smaller than the similarity_threshold value, which could be in the [0, 2] range.",
            openapi_examples={
                "Threshold of 0": {
                    "summary": "Example similarity threshold set to 0",
                    "value": 0,
                },
                "Similarity above 0.7": {
                    "summary": "Example similarity threshold set to 0.7",
                    "value": 0.7,
                },
            },
            ge=0,
            le=2,
        ),
    ] = None,
    cutoff_threshold: Annotated[
        Optional[float],
        Query(
            description="Minimum raw engine score for vector search legs only, applied per leg "
            "before rank fusion. Scale is the engine's transformed score (innerproduct kNN over "
            "normalized SigLIP2 maps ip >= 0 to 1 + ip), so the useful range is roughly 1.0-2.0; "
            "values below 1.0 are effectively no-ops.",
            openapi_examples={
                "None": {
                    "summary": "No cutoff threshold (keep every vector hit)",
                    "value": None,
                },
                "Mild cutoff at 1.05": {
                    "summary": "Drop vector hits with near-zero cosine similarity",
                    "value": 1.05,
                },
                "Strict cutoff at 1.3": {
                    "summary": "Keep only strongly similar vector hits (cosine >= 0.3)",
                    "value": 1.3,
                },
            },
            ge=0,
        ),
    ] = None,
    search_path: Annotated[
        str,
        Query(
            description="Specify the search path within the storage backend. This path should not contain the storage backend URL, just the asset path on the storage backend. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Search under '/Projects'": {
                    "summary": "Example to specify search location under '/Projects'",
                    "value": "/Projects",
                },
                "Browse '/Archives/2021'": {
                    "summary": "Example to specify search location in '/Archives/2021'",
                    "value": "/Archives/2021",
                },
            },
        ),
    ] = "",
    exclude_search_path: Annotated[
        str,
        Query(
            description="Specify the search path within the storage backend. This path should not contain the storage backend URL, just the asset path on the storage backend. Use wildcards: `*` for any number of characters, `?` for a single character. Separate terms with `,` for OR and `;` for AND.",
            openapi_examples={
                "Exclude '/Projects' from search": {
                    "summary": "Example to specify that '/Projects' is excluded",
                    "value": "/Projects",
                },
                "Exclude '*/Archives/2021*' from search": {
                    "summary": "Example to specify that any path with this: '*/Archives/2021*' needs to be excluded",
                    "value": "*/Archives/2021*",
                },
            },
        ),
    ] = "",
    filter_url_regexp: Annotated[
        Optional[str],
        Query(
            description="Specify an asset URL filter in the [Lucene Regexp format](https://www.elastic.co/guide/en/elasticsearch/reference/5.6/query-dsl-regexp-query.html#regexp-syntax).",
            openapi_examples={
                "None": {
                    "summary": "Disable URL regex filter",
                    "value": None,
                },
                "Include only '/Projects' folder in search": {
                    "summary": "Example to specify that only '/Projects' folder in included in search",
                    "value": ".*/Projects/.*",
                },
                "Exclude '*/Projects/*' from search": {
                    "summary": "Example to specify that any path with this: '/Projects/*' needs to be excluded",
                    "value": "~(.*/Projects/.*)",
                },
            },
        ),
    ] = None,
    search_in_scene: Annotated[
        str,
        Query(
            description="Conduct the search within a specific scene. Provide the full URL for the asset including the storage backend URL prefix.",
            openapi_examples={
                "Scene at 's3://bucket-name/Projects/scene1.usd": {
                    "summary": "Example scene URL stored on an S3 bucket",
                    "value": "s3://bucket-name/Projects/scene1.usd",
                },
                "Find in 'omniverse://example.org/scene2.usd'": {
                    "summary": "Example scene URL stored on an Omniverse Nucleus server",
                    "value": "omniverse://example.org/scene2.usd",
                },
            },
        ),
    ] = "",
    filter_by_properties: Annotated[
        str,
        Query(
            description="Filter assets by USD attributes where at least one root prim matches (note: only supported for a subset of attributes indexed). Format: `attribute1=abc,attribute2=456`, to search for key only use `key=`, and to search for value only `=value`",
            openapi_examples={
                "Filter by 'color=red,size=S'": {
                    "summary": "Example filter by 'color=red' and 'size=S'",
                    "value": "color=red,size=S",
                },
                "Properties 'material=plastic,weight=light'": {
                    "summary": "Example filter by 'material=plastic' and 'weight=light'",
                    "value": "material=plastic,weight=light",
                },
            },
        ),
    ] = "",
    filter_by_properties_include_any: Annotated[
        str,
        Query(
            description="Filter assets by USD attributes using OR logic — matches if at least one property condition is satisfied. Same format as `filter_by_properties`: `attribute1=abc,attribute2=456` or `attribute1=~*abc*,attribute2=~*456*` for wildcards",
            openapi_examples={
                "Any of 'color=red' or 'size=S'": {
                    "summary": "Example: match assets with color=red OR size=S",
                    "value": "color=red,size=S",
                },
            },
        ),
    ] = "",
    exclude_filter_by_properties: Annotated[
        str,
        Query(
            description="Exclude assets by USD attributes (note: only supported for a subset of attributes indexed). Format: `attribute1=abc,attribute2=456`",
            openapi_examples={
                "Filter by 'color=red,size=S'": {
                    "summary": "Example filter to exclude 'color=red' and 'size=S'",
                    "value": "color=red,size=S",
                },
                "Properties 'material=plastic,weight=light'": {
                    "summary": "Example filter to exclude 'material=plastic' and 'weight=light'",
                    "value": "material=plastic,weight=light",
                },
            },
        ),
    ] = "",
    filter_by_properties_numeric: Annotated[
        str,
        Query(
            description="Filter assets by numeric USD attributes with comparison operators. Format: `property>value,property<=value`. Supported operators: `>`, `>=`, `<`, `<=`, `=`. Example: `physics:mass>1.0,physics:density<=500`",
            openapi_examples={
                "Mass greater than 1.0": {
                    "summary": "Filter by mass > 1.0",
                    "value": "physics:mass>1.0",
                },
                "Mass range 1.0-10.0": {
                    "summary": "Filter by mass between 1.0 and 10.0",
                    "value": "physics:mass>=1.0,physics:mass<=10.0",
                },
                "Density at most 500": {
                    "summary": "Filter by density <= 500",
                    "value": "physics:density<=500",
                },
            },
        ),
    ] = "",
    filter_by_properties_version: Annotated[
        str,
        Query(
            description="Filter assets by version-valued USD attributes using version ordering. Format: `property>=version,property<version`; conditions are ANDed. Supported operators: `>`, `>=`, `<`, `<=`, `=`. Example: `simready_metadata_validation__profile_version>=2.0.0`",
            openapi_examples={
                "Profile version at least 2.0.0": {
                    "summary": "Filter by SimReady profile version >= 2.0.0",
                    "value": "simready_metadata_validation__profile_version>=2.0.0",
                },
                "Profile version range": {
                    "summary": "Filter by SimReady profile version between 2.0.0 and 3.0.0",
                    "value": "simready_metadata_validation__profile_version>=2.0.0,simready_metadata_validation__profile_version<=3.0.0",
                },
            },
        ),
    ] = "",
    filter_by_tags: Annotated[
        str,
        Query(
            description="Filter by tags. Format: `tag1,tag2,tag3`",
            openapi_examples={
                "Filter by tags 'tag1,tag2,tag3'": {
                    "summary": "Example filter by tags 'tag1,tag2,tag3'",
                    "value": "tag1,tag2,tag3",
                },
            },
        ),
    ] = "",
    min_bbox_x: Annotated[
        Optional[float],
        Query(
            description="Filter by minimum X axis dimension of the asset's bounding box of the default prim of the asset",
            ge=0,
        ),
    ] = None,
    min_bbox_y: Annotated[
        Optional[float],
        Query(
            description="Filter by minimum Y axis dimension of the asset's bounding box of the default prim of the asset",
            ge=0,
        ),
    ] = None,
    min_bbox_z: Annotated[
        Optional[float],
        Query(
            description="Filter by minimum Z axis dimension of the asset's bounding box of the default prim of the asset",
            ge=0,
        ),
    ] = None,
    max_bbox_x: Annotated[
        Optional[float],
        Query(
            description="Filter by maximum X axis dimension of the asset's bounding box of the default prim of the asset",
            gt=0,
        ),
    ] = None,
    max_bbox_y: Annotated[
        Optional[float],
        Query(
            description="Filter by maximum Y axis dimension of the asset's bounding box of the default prim of the asset",
            gt=0,
        ),
    ] = None,
    max_bbox_z: Annotated[
        Optional[float],
        Query(
            description="Filter by maximum Z axis dimension of the asset's bounding box of the default prim of the asset",
            gt=0,
        ),
    ] = None,
    return_images: Annotated[bool, Query(description="Return images if set to True")] = False,
    return_metadata: Annotated[bool, Query(description="Return metadata if set to True")] = False,
    return_root_prims: Annotated[bool, Query(description="Return root prims if set to True")] = False,
    return_default_prims: Annotated[bool, Query(description="Return default prims if set to True")] = False,
    return_predictions: Annotated[
        bool,
        Query(
            description="Returns predictions for each asset in the search results from the fixed vocabulary.\n\n **NOTE**: This functionality is deprecated and setting this parameter will have no effect starting from USD Search version API 1.3. This parameter will be completely removed from the list of input parameters in USD Search API version 2 and above. Please rely on VLM-based auto-captioning functionality instead.",
            deprecated=True,
        ),
    ] = False,
    return_in_scene_instances_prims: Annotated[
        bool,
        Query(description="[in-scene search only] Return prims of instances of objects found in the scene"),
    ] = False,
    embedding_knn_search_method: Annotated[
        Optional[SearchMethod],
        Query(description="Search method, approximate should be faster but is less accurate. Default is exact"),
    ] = None,
    limit: Annotated[
        int,
        Query(
            description="Set the maximum number of results to return from the search, default is 32",
            gt=0,
            le=10000,
        ),
    ] = 32,
    offset: Annotated[
        int,
        Query(
            description=(
                "Number of results to skip. Prefer the `cursor` below, which pins the ranking so pages do "
                "not overlap or skip. Depth depends on the query shape: filter-only is unbounded, a text "
                "query is capped by pagination_max_offset, a multi-leg query by the RRF fusion window. "
                "Cannot be combined with validate_results=true."
            ),
            ge=0,
        ),
    ] = 0,
    cursor: Annotated[
        Optional[str],
        Query(
            description=(
                "Opaque cursor from the previous response's `X-Next-Cursor` header. Takes precedence over "
                "`offset`. The query must stay identical while paging; `limit` and the `return_*` flags may "
                "change. Cannot be combined with validate_results=true."
            ),
        ),
    ] = None,
    vision_metadata: Annotated[
        Optional[str],
        Query(
            description="Uses a keyword match query on metadata fields that were generated using Vision Language Models"
        ),
    ] = None,
    return_vision_generated_metadata: Annotated[
        bool,
        Query(description="Returns the metadata fields that were generated using Vision Language Models"),
    ] = False,
    return_tags: Annotated[bool, Query(description="Return tags for search results")] = False,
    return_inner_hits: Annotated[
        bool,
        Query(description="Return inner hits from nested queries for debugging and detailed scoring"),
    ] = False,
    validate_results: Annotated[bool, Query(description="Validate results with VLM")] = False,
    vlm_validator: Annotated[Optional[SearchResultValidator], Depends(dependencies.vlm_validator)] = None,
    request: Request = None,
) -> List[SearchResult]:
    """
    All supported search parameters are available as query parameters.

    Search endpoint enables comprehensive searches across images (e.g., .jpg, .png) and USD-based 3D models within
    various storage backends (Nucleus, S3, etc.). It enables users to use natural language, image
    similarity, and precise metadata criteria (file name, type, date, size, creator, etc.) to locate relevant content
    efficiently. Furthermore, when integrated with the Asset Graph Service, USD Search API extends its capabilities to
    include searches based on USD properties and spatial dimensions of 3D model bounding boxes, enhancing the ability
    to find assets that meet specific requirements.

    **Pagination:** pass `offset`, or better, the previous response's `X-Next-Cursor` header back as
    `cursor` — it pins the ranking so pages do not overlap or skip. Because this endpoint returns a
    bare JSON array, the pagination state travels in response headers rather than the body:
    `X-Next-Cursor`, `X-Has-More` (`true`/`false`) and `X-Paginable-Total` (the page-count basis).
    How deep you can go depends on the query shape: filter-only queries are unbounded, a text query
    is capped by the deployment's `pagination_max_offset`, and a multi-leg query is capped by the RRF
    fusion window. `validate_results=true` is single-page and cannot be combined with `offset`/`cursor`.
    The richer envelope — including why paging stopped — is on `POST /v3/deepsearch/search`.
    """
    telemetry_context = get_default_telemetry_context()
    telemetry_extra_fields = None

    if api_key_auth:
        telemetry_extra_fields = get_telemetry_extra_fields(telemetry_context, api_key_auth)
        telemetry_extra_fields["source"] = "admin_access"
    elif token_auth:
        telemetry_extra_fields = get_telemetry_extra_fields(telemetry_context, token_auth.credentials)
    elif basic_auth:
        pass
        # TODO: Move to dependencies
        # if isinstance(get_ngsearch_client().deepsearch_backend.ng_search_service.client, NucleusStorageClient):
        #     _token = await get_ngsearch_client().deepsearch_backend.get_access_token(
        #         token=None, username=basic_auth.username, password=basic_auth.password
        #     )
        #     telemetry_extra_fields = get_telemetry_extra_fields(telemetry_context, _token)
        # else:
        #     telemetry_extra_fields = TelemetryExtraFields(
        #         source=basic_auth.username,
        #         deepsearch_session_id=telemetry_context.session_id,
        #         session_id=telemetry_context.session_id,
        #         appName=telemetry_context.app_name,
        #         appVersion=telemetry_context.app_version,
        #         uiName=telemetry_context.ui_name,
        #         uiVersion=telemetry_context.ui_version,
        #         app=f"{telemetry_context.app_name}_{telemetry_context.app_version}",
        #         kitVersion=telemetry_context.app_version,
        #     )

    if telemetry_extra_fields is not None and SEARCH_TELEMETRY_STDOUT:
        logger.debug(f"Telemetry extra fields: {telemetry_extra_fields}")

    if return_in_scene_instances_prims and not search_in_scene:
        raise HTTPException(
            status_code=422,
            detail="return_in_scene_instances_prims requires search_in_scene parameter to be set",
        )

    # Force return_images when validate_results=True (images are needed for validation)
    effective_return_images = return_images or validate_results

    try:
        search_request = DeepSearchSearchRequestV2(
            description=description,
            image_similarity_search=image_similarity_search,
            file_name=file_name,
            exclude_file_name=exclude_file_name,
            file_extension_include=file_extension_include,
            file_extension_exclude=file_extension_exclude,
            created_after=created_after,
            created_before=created_before,
            modified_after=modified_after,
            modified_before=modified_before,
            file_size_greater_than=file_size_greater_than,
            file_size_less_than=file_size_less_than,
            created_by=created_by,
            exclude_created_by=exclude_created_by,
            modified_by=modified_by,
            exclude_modified_by=exclude_modified_by,
            similarity_threshold=similarity_threshold,
            cutoff_threshold=cutoff_threshold,
            search_path=search_path,
            exclude_search_path=exclude_search_path,
            filter_url_regexp=filter_url_regexp,
            search_in_scene=search_in_scene,
            filter_by_properties=filter_by_properties,
            filter_by_properties_include_any=filter_by_properties_include_any,
            exclude_filter_by_properties=exclude_filter_by_properties,
            filter_by_properties_numeric=filter_by_properties_numeric,
            filter_by_properties_version=filter_by_properties_version,
            filter_by_tags=filter_by_tags,
            min_bbox_x=min_bbox_x,
            min_bbox_y=min_bbox_y,
            min_bbox_z=min_bbox_z,
            max_bbox_x=max_bbox_x,
            max_bbox_y=max_bbox_y,
            max_bbox_z=max_bbox_z,
            return_images=effective_return_images,
            return_metadata=return_metadata,
            return_root_prims=return_root_prims,
            return_default_prims=return_default_prims,
            return_predictions=return_predictions,
            return_tags=return_tags,
            return_in_scene_instances_prims=return_in_scene_instances_prims,
            embedding_knn_search_method=embedding_knn_search_method,
            limit=limit,
            offset=offset,
            cursor=cursor,
            validate_results=validate_results,
            vision_metadata=vision_metadata,
            return_vision_generated_metadata=return_vision_generated_metadata,
            return_inner_hits=return_inner_hits or effective_return_images,
        )
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            error_messages.append(
                {
                    "loc": error["loc"],
                    "msg": error["msg"],
                    "type": error["type"],
                }
            )
        raise RequestValidationError(errors=error_messages)

    try:
        results = await search_backend_v2.search(search_request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaginationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _set_pagination_headers(response, results)
    search_results = await convert_search_response(
        results,
        search_request,
        image_loader,
        embedding_client=search_backend_v2.search_client.embedding_clients.get(EmbeddingType.SIGLIP2_EMBEDDING),
    )

    # Perform VLM validation if requested
    if validate_results and vlm_validator:
        query_text = description if description else None
        # Read the image off the parsed request, not the raw query param: that copy
        # has been normalized to the internal URL form when it names an asset.
        query_image = search_request.image_similarity_search[0] if search_request.image_similarity_search else None

        if query_text or query_image:
            images = [r.image for r in search_results]
            validation_results = await vlm_validator.validate_results(query_text, query_image, images)
            for result, val_result in zip(search_results, validation_results):
                if val_result is not None:
                    result.query_relevance = QueryRelevanceValidationResult(
                        is_match=val_result.is_match,
                        confidence=val_result.confidence,
                        similarity_score=val_result.similarity_score,
                        reasoning=val_result.reasoning,
                    )

    return search_results


def parse_arg_input_and_or(input_str: str) -> list[list[str]]:
    return [or_group.split(",") for or_group in input_str.split(";")]


@router.post(
    "/search",
    response_model_exclude_none=True,
    responses={
        200: {
            "description": "Search results",
            "content": {"application/json": {"example": [SearchResult.Config.schema_extra["examples"][0]]}},
            "headers": PAGINATION_RESPONSE_HEADERS,
        }
    },
)
@telemetry_track_search()
async def search_post(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    req: DeepSearchSearchRequestV2,
    search_backend_v2: Annotated[FilteredSearchClient, Depends(dependencies.search_backend_client_v2)],
    image_loader: Annotated[BaseImageLoader, Depends(dependencies.image_loader)],
    response: Response,
    vlm_validator: Annotated[Optional[SearchResultValidator], Depends(dependencies.vlm_validator)] = None,
    request: Request = None,
) -> List[SearchResult]:
    """
    All supported search parameters are available as body parameters.

    Search endpoint enables comprehensive searches across images (e.g., .jpg, .png) and USD-based 3D models within
    various storage backends (Nucleus, S3, etc.). It enables users to use natural language, image
    similarity, and precise metadata criteria (file name, type, date, size, creator, etc.) to locate relevant content
    efficiently. Furthermore, when integrated with the Asset Graph Service, USD Search API extends its capabilities to
    include searches based on USD properties and spatial dimensions of 3D model bounding boxes, enhancing the ability
    to find assets that meet specific requirements.

    **Pagination:** pass `offset`, or better, the previous response's `X-Next-Cursor` header back as
    `cursor` — it pins the ranking so pages do not overlap or skip. Because this endpoint returns a
    bare JSON array, the pagination state travels in response headers rather than the body:
    `X-Next-Cursor`, `X-Has-More` (`true`/`false`) and `X-Paginable-Total` (the page-count basis).
    How deep you can go depends on the query shape: filter-only queries are unbounded, a text query
    is capped by the deployment's `pagination_max_offset`, and a multi-leg query is capped by the RRF
    fusion window. `validate_results=true` is single-page and cannot be combined with `offset`/`cursor`.
    The richer envelope — including why paging stopped — is on `POST /v3/deepsearch/search`.
    """
    # Force return_images when validate_results=True (images are needed for validation)
    if req.validate_results:
        req.return_images = True
    req.return_inner_hits = req.return_inner_hits or req.return_images
    try:
        with tracer.start_as_current_span("routers_v2.search_backend_v2.search"):
            results = await search_backend_v2.search(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PaginationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _set_pagination_headers(response, results)
    with tracer.start_as_current_span("routers_v2.convert_search_response"):
        search_results = await convert_search_response(
            results,
            req,
            image_loader,
            embedding_client=search_backend_v2.search_client.embedding_clients.get(EmbeddingType.SIGLIP2_EMBEDDING),
        )

    # Perform VLM validation if requested
    if req.validate_results and vlm_validator:
        query_text = req.description if req.description else None
        query_image = req.image_similarity_search[0] if req.image_similarity_search else None

        if query_text or query_image:
            images = [r.image for r in search_results]
            validation_results = await vlm_validator.validate_results(query_text, query_image, images)
            for result, val_result in zip(search_results, validation_results):
                if val_result is not None:
                    result.query_relevance = QueryRelevanceValidationResult(
                        is_match=val_result.is_match,
                        confidence=val_result.confidence,
                        similarity_score=val_result.similarity_score,
                        reasoning=val_result.reasoning,
                    )

    return search_results


@router.get(
    "/search/stats/usd_properties",
)
async def stats_usd_properties(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
    search_backend_v2: Annotated[SearchBackendClientV2, Depends(dependencies.search_backend_client_v2)],
    aggregations_enabled: Annotated[SearchBackendClientV2, Depends(dependencies.aggregations_access_check)],
    # Bound from query params; FastAPI always constructs it, so an unfiltered
    # call arrives here as a model with every field at its default.
    filters: Annotated[UsdPropertyStatsFilters, Query()],
) -> response_models.StatsResponse:
    """
    Inventory of USD properties across the indexed corpus: every unique property key, every unique
    value, and every unique key=value pair — each with the number of assets that carry it
    (``asset_count``), sorted by coverage. The full lists (not just counts) power property discovery;
    see the ``/usd-property-catalog`` skill, which turns this into a local catalog + filter config.

    **Filtering.** Pass any of the filter parameters that `/search` accepts (`search_path`,
    `file_extension_include`, `filter_by_properties`, `filter_by_tags`, dates, bbox dimensions,
    `search_in_scene`, …) to inventory a subset of the corpus instead — "which properties do the
    assets under /Projects/Vehicles carry?". Passing none inventories everything, as before.

    Counts stay **exact** for whatever subset is selected: this is an aggregation over the whole
    matching set, not a summary of one page of search results. Filtering is asset-scoped, so
    `filter_by_properties=class=vehicle` returns *every* property those assets carry, not just
    `class` — which is what makes drill-down work.

    Search-only parameters (`description`, vector/image queries, `limit`, `offset`) are rejected
    with a 422: an aggregation has no ranking to apply them to, and silently ignoring them would
    return corpus-wide numbers that look filtered.

    **Not access-filtered.** Results describe the index itself, not the subset of assets the
    caller could download — with or without filters. Deployments that cannot accept that should
    turn aggregations off (`enable_aggregations=false`), which makes this endpoint return 403.
    """
    try:
        return await search_backend_v2.get_usd_properties_stats(filters)
    except NotFoundException as e:
        # Unknown search_in_scene — the only 404 this endpoint can produce.
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        # e.g. vision_metadata on an index carrying no VLM-generated fields.
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ApiException as e:
        # search_in_scene needs the Asset Graph Service; degrade on that parameter
        # alone rather than taking the unfiltered inventory down with it.
        raise HTTPException(
            status_code=503,
            detail=f"Asset Graph Service is unavailable, which 'search_in_scene' requires: {e}",
        ) from e
