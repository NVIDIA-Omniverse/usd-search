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
import logging
from typing import Any, Dict, List, Optional

from asset_graph_service_client import AGSAssetGraphApi, ApiClient
from asset_graph_service_client.api.usd_graph_api import USDGraphApi
from asset_graph_service_client.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from deepsearch_api.models import Prim
from deepsearch_api.search_backend.main import SearchBackendClientV2
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    SearchResponse,
    SearchResult,
    VectorQuery,
    VectorQueryType,
)
from opentelemetry import trace

from search_utils.storage_client import RemoteFileUri, StorageClient, ThumbnailLoadMode

from . import OPENSEARCH_MAX_RESULT_WINDOW

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def get_instance_prims_from_search_results(
    search_results: SearchResponse,
    scene_url: str,
    ags_api: USDGraphApi,
    return_instance_prims: bool = False,
    return_root_prims: bool = False,
    return_default_prims: bool = False,
    n_retries: int = 3,
    n_parallel_requests: int = 10,
) -> SearchResponse:
    """Enhance search results with prim information from AGS

    Args:
        search_results: The search results to enhance
        scene_url: The URL of the scene
        ags_api: The AGS API client to use
        return_root_prims: If True, fetch and include root prims
        return_default_prims: If True, fetch and include default prims
        n_retries: Number of retries for API calls
        n_parallel_requests: Number of parallel requests to make

    Returns:
        Enhanced search results with prim information
    """

    async def get_prims_for_hit(hit: SearchResult) -> SearchResult:
        hit_url = hit.source["base_key"]
        logger.debug(f"Getting prims for {hit_url}...")

        async def fetch_with_retry(fetch_func, error_message_prefix):
            """Helper to retry a specific prim fetch operation"""
            for retry in range(n_retries):
                try:
                    return await fetch_func()
                except (BadRequestException, NotFoundException) as e:
                    # These are expected exceptions, log as warnings
                    logger.warning(f"{error_message_prefix} failed: {str(e)}")
                    return None  # Don't retry for expected exceptions
                except ApiException as e:
                    logger.error(f"{error_message_prefix} failed with API error: {str(e)}")
                    if retry == n_retries - 1:
                        # Last retry attempt, give up
                        return None
                except Exception as e:
                    # Unexpected exception
                    if retry == n_retries - 1:
                        logger.error(f"{error_message_prefix} failed after {n_retries} attempts: {str(e)}")
                        return None
                    logger.warning(f"Retrying {error_message_prefix} after error: {str(e)}")

                # Exponential backoff
                await asyncio.sleep(1 * (retry + 1))

            return None

        # Fetch instance prims if requested
        if return_instance_prims and scene_url:
            instance_prims = await fetch_with_retry(
                lambda: ags_api.get_prims_asset_graph_usd_prims_get(source_asset_url=hit_url, scene_url=scene_url),
                f"Request to get instance prims for {hit_url} in scene {scene_url}",
            )
            if instance_prims:
                hit.ags_data.instance_prims = [Prim(**prim.model_dump()) for prim in instance_prims]
                logger.debug(
                    f"Retrieved instance prims for {hit_url} in scene {scene_url}: {len(hit.ags_data.instance_prims)} prims"
                )
            else:
                hit.ags_data.instance_prims = []

        # Fetch root prims if requested
        if return_root_prims:
            root_prims = await fetch_with_retry(
                lambda: ags_api.get_prims_asset_graph_usd_prims_get(scene_url=hit_url, root_prim=True),
                f"Request to get root prims for {hit_url}",
            )
            if root_prims:
                hit.ags_data.root_prims = [Prim(**prim.model_dump()) for prim in root_prims]
                logger.debug(f"Retrieved root prims for {hit_url}: {len(hit.ags_data.root_prims)} prims")
            else:
                hit.ags_data.root_prims = []

        # Fetch default prims if requested
        if return_default_prims:
            default_prims = await fetch_with_retry(
                lambda: ags_api.get_prims_asset_graph_usd_prims_get(scene_url=hit_url, default_prim=True),
                f"Request to get default prims for {hit_url}",
            )
            if default_prims:
                hit.ags_data.default_prims = [Prim(**prim.model_dump()) for prim in default_prims]
                logger.debug(f"Retrieved default prims for {hit_url}: {len(hit.ags_data.default_prims)} prims")
            else:
                hit.ags_data.default_prims = []

        return hit

    # Process hits in parallel batches
    enhanced_hits = []
    for i in range(0, len(search_results.hits), n_parallel_requests):
        batch = search_results.hits[i : i + n_parallel_requests]
        enhanced_batch = await asyncio.gather(*[get_prims_for_hit(hit) for hit in batch])
        enhanced_hits.extend(enhanced_batch)

    search_results.hits = enhanced_hits
    return search_results


class FilteredSearchClient:
    def __init__(
        self,
        search_client: SearchBackendClientV2,
        ags_client: ApiClient,
        storage_client: Optional[StorageClient] = None,
        validate_access: bool = False,
    ):
        self.search_client = search_client
        self.ags_client = ags_client
        self.storage_client = storage_client
        self.validate_access = validate_access
        self.usd_graph_api = USDGraphApi(api_client=self.ags_client)

    @property
    def storage_backend_host(self) -> str:
        return self.storage_client.base_uri

    async def _download_remote_images(
        self,
        search_request: DeepSearchSearchRequestV2,
    ) -> DeepSearchSearchRequestV2:
        """Process image queries by downloading images from S3 or Omniverse URLs.

        Args:
            search_request: The search request containing vector queries

        Returns:
            Modified search request with downloaded image data
        """
        if not search_request.vector_queries and not search_request.image_similarity_search:
            return search_request

        # Handle image_similarity_search field if present
        if search_request.image_similarity_search:

            async def download_image(image_query: str) -> str:
                """Helper function to download a single image"""
                if isinstance(image_query, str) and image_query.startswith(("s3://", "omniverse://")):
                    if not self.storage_client:
                        logger.warning(f"Storage client not provided, skipping image download for {image_query}")
                        return image_query
                    # Use load_thumbnail to get an efficient image representation
                    thumbnail_data = await self.storage_client.load_thumbnail(
                        uri=RemoteFileUri(image_query),
                        mode=ThumbnailLoadMode.one,
                    )
                    # thumbnail_data will be either a tuple or list of tuples, we want the first image
                    image_data = thumbnail_data[0] if isinstance(thumbnail_data, list) else thumbnail_data
                    search_request.set_downloaded_image(image_query, image_data.data)
                    return image_query  # Return URL, actual data is stored in _downloaded_images
                return image_query

            # Process all images in parallel
            processed_images = await asyncio.gather(
                *[download_image(img) for img in search_request.image_similarity_search],
                return_exceptions=False,
            )
            search_request.image_similarity_search = processed_images

        # Handle vector queries
        async def process_vector_query(query: VectorQuery) -> VectorQuery | None:
            """Helper function to process a single vector query"""
            if query.query_type != VectorQueryType.IMAGE:
                return query

            image_query = query.query
            if not isinstance(image_query, str):
                return query

            if image_query.startswith(("s3://", "omniverse://")):
                if not self.storage_client:
                    logger.warning(f"Storage client not provided, skipping image download for {image_query}")
                    return None

                # Use load_thumbnail to get an efficient image representation
                thumbnail_data = await self.storage_client.load_thumbnail(
                    uri=RemoteFileUri(image_query),
                    mode=ThumbnailLoadMode.one,
                )
                # thumbnail_data will be either a tuple or list of tuples, we want the first image
                image_data = thumbnail_data[0] if isinstance(thumbnail_data, list) else thumbnail_data
                search_request.set_downloaded_image(image_query, image_data.data)  # image_data[0] is the bytes
                # Return query with original URL, actual data is stored in _downloaded_images
                return VectorQuery(
                    field_name=query.field_name,
                    query_type=query.query_type,
                    query=image_query,
                )
            return query

        # Process all vector queries in parallel
        if search_request.vector_queries:
            processed_vector_queries = await asyncio.gather(
                *[process_vector_query(query) for query in search_request.vector_queries],
                return_exceptions=False,
            )
            # Filter out None values (failed downloads)
            search_request.vector_queries = [q for q in processed_vector_queries if q is not None]

        return search_request

    async def get_usd_properties_stats(self) -> Dict[str, Any]:
        return await self.search_client.get_usd_properties_stats()

    async def get_scene_assets(self, scene_url: str) -> List[str]:
        """
        Fetch all assets from a specific scene using AGS client
        """
        try:
            ags_api = AGSAssetGraphApi(api_client=self.ags_client)
            assets = await ags_api.get_dependencies_flat_dependency_graph_flat_get(
                root_node_url=scene_url, max_level=None, limit=10000
            )
            return [asset.url for asset in assets]
        except NotFoundException as e:
            raise NotFoundException(f"Scene {scene_url} not found") from e

        except Exception as e:
            logger.error(f"Error fetching scene assets: {e}")
            raise

    async def _get_scene_asset_whitelist(
        self,
        search_request: DeepSearchSearchRequestV2,
    ) -> Optional[List[str]]:
        """Get whitelist of assets from a specific scene if search_in_scene is specified."""
        if not search_request.search_in_scene:
            return None

        try:
            url_whitelist = await self.get_scene_assets(search_request.search_in_scene)
            logger.debug(f"Retrieved {len(url_whitelist)} assets from scene: {search_request.search_in_scene}")
            return url_whitelist
        except NotFoundException as e:
            raise NotFoundException(f"Scene {search_request.search_in_scene} not found") from e
        except Exception as e:
            logger.error(f"Failed to get scene assets: {e}")
            raise

    async def _filter_by_access_permissions(
        self,
        search_results: SearchResponse,
        original_size: Optional[int] = None,
    ) -> SearchResponse:
        """Filter search results based on storage access permissions."""
        if not (self.validate_access and self.storage_client):
            return search_results

        logger.debug("Filtering results based on storage access permissions...")
        uri_list = [hit.source.get("base_key", "") for hit in search_results.hits]

        # Batch verify access to all URIs
        verified_uris = set()
        async for batch_results in self.storage_client.batch_verify_access(uri_list):
            for result in batch_results:
                if result.exists:
                    verified_uris.add(result.uri)

        # Filter hits based on access permissions
        search_results.hits = [hit for hit in search_results.hits if hit.source.get("base_key", "") in verified_uris]

        # Cap results to original requested size
        if original_size:
            search_results.hits = search_results.hits[:original_size]

        return search_results

    async def _enhance_with_instance_prims(
        self,
        search_results: SearchResponse,
        search_request: DeepSearchSearchRequestV2,
        config: Optional[Any] = None,
    ) -> SearchResponse:
        """Enhance search results with prim information if requested."""
        if not any(
            [
                search_request.return_in_scene_instances_prims,
                search_request.search_in_scene,
                search_request.return_root_prims,
                search_request.return_default_prims,
            ]
        ):
            logger.debug("AGS results processing not requested, skipping...")
            return search_results

        logger.debug("Getting prims from AGS...")

        return await get_instance_prims_from_search_results(
            search_results=search_results,
            scene_url=search_request.search_in_scene,
            ags_api=self.usd_graph_api,
            return_instance_prims=search_request.return_in_scene_instances_prims,
            return_root_prims=search_request.return_root_prims,
            return_default_prims=search_request.return_default_prims,
            n_retries=config.asset_graph_service_n_retries if config else 3,
            n_parallel_requests=(config.asset_graph_service_n_parallel_requests if config else 10),
        )

    async def search(
        self,
        search_request: DeepSearchSearchRequestV2,
        from_: int = 0,
        config: Optional[Any] = None,
    ) -> SearchResponse:
        """
        Enhanced search method that applies a pipeline of filters and enhancements to search results.

        Pipeline steps:
        1. Process image queries
        2. Get scene asset whitelist (if searching in scene)
        3. Perform base search with filters
        4. Apply access permission filtering
        5. Enhance with instance prim information
        """
        # Store original size for later capping if access validation is enabled
        original_size = search_request.limit
        if self.validate_access and self.storage_client:
            # cap the limit to 10000 to avoid OpenSearch max_result_window limit
            search_request.limit = min(
                search_request.limit * 3 if search_request.limit else 300,
                OPENSEARCH_MAX_RESULT_WINDOW,
            )

        # Step 1: Process image queries
        search_request = await self._download_remote_images(search_request)

        # Step 2: Get scene asset whitelist
        url_whitelist = await self._get_scene_asset_whitelist(search_request)

        # Step 3: Perform base search
        with tracer.start_as_current_span("filtered_search_client.search"):
            search_results = await self.search_client.search(
                search_request=search_request, from_=from_, url_whitelist=url_whitelist
            )

        # Step 4: Apply access permission filtering
        search_results = await self._filter_by_access_permissions(search_results, original_size)

        # Step 5: Enhance with instance prim information
        search_results = await self._enhance_with_instance_prims(search_results, search_request, config)

        logger.debug(f"Returning {len(search_results.hits)} search results after filtering")
        return search_results
