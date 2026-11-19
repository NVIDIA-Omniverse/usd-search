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
import base64
import logging
from typing import TYPE_CHECKING, Any, List, Optional

from asset_graph_service_client import AGSAssetGraphApi, ApiClient
from asset_graph_service_client.api.usd_graph_api import USDGraphApi
from asset_graph_service_client.exceptions import (
    ApiException,
    BadRequestException,
    NotFoundException,
)
from deepsearch_api.models import Prim
from deepsearch_api.routers_v2.models import SearchFilterFields
from deepsearch_api.search_backend.asset_images import resolve_asset_image_ids
from deepsearch_api.search_backend.exceptions import (
    ImageCacheReadError,
    ImageQueryNotFoundError,
)
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.main import SearchBackendClientV2
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    SearchResponse,
    SearchResult,
    VectorQueryType,
)
from deepsearch_api.search_backend.response_models import StatsResponse
from opentelemetry import trace

from search_utils.storage_client import RemoteFileUri, StorageClient, ThumbnailLoadMode
from search_utils.url_mapping import normalize_upstream_document

from . import OPENSEARCH_MAX_RESULT_WINDOW
from .pagination import (
    PageSpec,
    PaginationError,
    PaginationMode,
    build_cursor,
    decode_cursor,
    fingerprint_request,
    page_spec_for_request,
    rebase_cursor,
)

if TYPE_CHECKING:
    from deepsearch_api.cache import RedisImageResolutionCache

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

_ASSET_URL_SCHEMES = ("s3://", "omniverse://")


def _is_asset_url(query: Any) -> bool:
    """Whether an image query is a storage URL to load, rather than inline (base64) image data."""
    return isinstance(query, str) and query.startswith(_ASSET_URL_SCHEMES)


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
                    # Prims carry `scene_url` / `source_asset_url` in AGS's published form.
                    return normalize_upstream_document(await fetch_func())
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
        image_loader: Optional[BaseImageLoader] = None,
        image_resolution_cache: Optional["RedisImageResolutionCache"] = None,
    ):
        self.search_client = search_client
        self.ags_client = ags_client
        self.storage_client = storage_client
        self.validate_access = validate_access
        self.image_loader = image_loader
        self.image_resolution_cache = image_resolution_cache
        self.usd_graph_api = USDGraphApi(api_client=self.ags_client)

    @property
    def storage_backend_host(self) -> str:
        return self.storage_client.telemetry_host

    async def _load_query_image(self, url: str) -> bytes:
        """Bytes to embed for an image query given as an asset URL: its indexed view, else its sidecar thumbnail.

        Raises ``ImageQueryNotFoundError`` when neither exists or the caller cannot see the asset, and
        ``ImageCacheReadError`` when the image cache could not be read and there is no sidecar to fall back to.
        """
        if self._access_filtering_enabled:
            # The indexed image is read with service credentials, so check visibility explicitly (as GET /images does).
            async for batch in self.storage_client.batch_verify_access([RemoteFileUri(url)]):
                if not any(result.exists for result in batch):
                    raise ImageQueryNotFoundError(f"No image available for image query asset '{url}'")

        cache_error: Optional[ImageCacheReadError] = None
        if self.image_loader is not None:
            image_ids = await resolve_asset_image_ids(url, self, self.image_resolution_cache) or []
            image_id = next((i for i in image_ids if i), None)
            try:
                image_b64 = await self.image_loader.fetch_image(image_id) if image_id else None
            except ImageCacheReadError as e:
                logger.warning("Image cache read failed for image query asset %s: %s", url, e)
                cache_error, image_b64 = e, None
            if image_b64:
                return base64.b64decode(image_b64)

        # Not indexed (yet), or no image loader: try the sidecar thumbnail on storage.
        if self.storage_client is not None:
            try:
                thumbnail = await self.storage_client.load_thumbnail(uri=RemoteFileUri(url), mode=ThumbnailLoadMode.one)
            except (FileNotFoundError, NotImplementedError):
                logger.debug("No sidecar thumbnail for image query asset %s", url)
            else:
                return (thumbnail[0] if isinstance(thumbnail, list) else thumbnail).data

        if cache_error is not None:
            raise cache_error
        raise ImageQueryNotFoundError(f"No image available for image query asset '{url}'")

    async def _download_remote_images(
        self,
        search_request: DeepSearchSearchRequestV2,
    ) -> DeepSearchSearchRequestV2:
        """Load the image behind every asset-URL image query into the request's downloaded-image store."""
        urls = [img for img in search_request.image_similarity_search or [] if _is_asset_url(img)]
        urls += [
            q.query
            for q in search_request.vector_queries or []
            if q.query_type == VectorQueryType.IMAGE and _is_asset_url(q.query)
        ]
        urls = list(dict.fromkeys(urls))
        if not urls:
            return search_request

        images = await asyncio.gather(*[self._load_query_image(url) for url in urls])
        for url, image in zip(urls, images):
            search_request.set_downloaded_image(url, image)
        return search_request

    async def get_usd_properties_stats(self, filters: Optional[SearchFilterFields] = None) -> StatsResponse:
        """USD-property inventory, optionally narrowed to the assets ``filters`` selects.

        ``filters=None`` keeps the original whole-corpus behaviour. ``search_in_scene``
        is resolved here rather than in the backend client because only this class
        holds the Asset Graph Service connection.

        Deliberately NOT access-filtered, filtered or not: visibility is decided per
        asset by the storage backend (see ``_filter_by_access_permissions``), which an
        aggregation cannot consult. These numbers describe the index, not the caller's
        visible slice — deployments that cannot accept that should disable aggregations.
        """
        if filters is None:
            return await self.search_client.get_usd_properties_stats()

        bool_filters = await self.search_client.create_bool_filters(filters)

        url_whitelist = await self._get_scene_asset_whitelist(filters)
        if url_whitelist is not None:
            bool_filters.append({"terms": {"base_key": url_whitelist}})

        return await self.search_client.get_usd_properties_stats(bool_filters=bool_filters)

    async def get_scene_assets(self, scene_url: str) -> List[str]:
        """
        Fetch all assets from a specific scene using AGS client
        """
        try:
            ags_api = AGSAssetGraphApi(api_client=self.ags_client)
            assets = await ags_api.get_dependencies_flat_dependency_graph_flat_get(
                root_node_url=scene_url, max_level=None, limit=10000
            )
            # AGS answers in the public URL form where the deployment publishes
            # one. This list becomes a whitelist matched against the index's
            # `base_key`, which is always internal — unnormalized it matches
            # nothing and `search_in_scene` quietly returns zero results.
            return [asset.url for asset in normalize_upstream_document(assets)]
        except NotFoundException as e:
            raise NotFoundException(f"Scene {scene_url} not found") from e

        except Exception as e:
            logger.error(f"Error fetching scene assets: {e}")
            raise

    async def _get_scene_asset_whitelist(
        self,
        search_request: SearchFilterFields,
    ) -> Optional[List[str]]:
        """Get whitelist of assets from a specific scene if search_in_scene is specified.

        Takes the shared filter model, not a full search request: the USD-property
        statistics path scopes itself to a scene the same way search does.
        """
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

    @property
    def _access_filtering_enabled(self) -> bool:
        return bool(self.validate_access and self.storage_client)

    async def _visible_uris(self, hits: List[SearchResult]) -> set:
        """URIs from ``hits`` the current caller is allowed to see."""
        verified_uris = set()
        async for batch_results in self.storage_client.batch_verify_access(
            [hit.source.get("base_key", "") for hit in hits]
        ):
            for result in batch_results:
                if result.exists:
                    verified_uris.add(result.uri)
        return verified_uris

    async def _filter_by_access_permissions(
        self,
        search_results: SearchResponse,
        original_size: Optional[int] = None,
    ) -> SearchResponse:
        """Filter search results based on storage access permissions."""
        if not self._access_filtering_enabled:
            return search_results

        logger.debug("Filtering results based on storage access permissions...")
        verified_uris = await self._visible_uris(search_results.hits)

        # Filter hits based on access permissions
        search_results.hits = [hit for hit in search_results.hits if hit.source.get("base_key", "") in verified_uris]

        # Cap results to original requested size
        if original_size:
            search_results.hits = search_results.hits[:original_size]

        return search_results

    def _with_window_pinned_to_the_requested_page(
        self,
        page: PageSpec,
        search_request: DeepSearchSearchRequestV2,
        target: int,
    ) -> PageSpec:
        """Size the fusion window before the over-fetch below inflates the limit it would be read from."""
        window = page.window or self.search_client.default_window_size(search_request, page.raw_offset + target)
        return page.model_copy(update={"window": window})

    async def _search_filling_page(
        self,
        search_request: DeepSearchSearchRequestV2,
        page: PageSpec,
        url_whitelist: Optional[List[str]],
        target: int,
    ) -> SearchResponse:
        """Run the search and top the page back up to ``target`` visible hits.

        Access filtering runs *after* the backend cuts the page, so a page would
        otherwise come back short and ``len(hits) < limit`` would stop meaning
        "end of results". Instead: over-fetch, keep what is visible, resume from
        where the batch stopped, at most ``access_filter_max_fetches`` times — a
        caller who can see almost nothing gets a short page plus an honest
        ``has_more`` rather than a request that walks the whole index.

        Two offsets diverge here and the cursor carries both: ``raw_offset`` is
        the position in the backend's ordering to resume from, ``offset`` is how
        many hits the caller has actually received.

        Raises:
            PaginationError: the cursor resumes somewhere ``from``/``size``
                cannot reach, which only a replayed cursor can ask for.
        """
        if not page.search_after and page.raw_offset >= OPENSEARCH_MAX_RESULT_WINDOW:
            raise PaginationError(
                f"Pagination offset {page.raw_offset} exceeds the maximum supported depth "
                f"({OPENSEARCH_MAX_RESULT_WINDOW}) for this query."
            )

        accepted: List[SearchResult] = []
        raw_offset = page.raw_offset
        resume = self._with_window_pinned_to_the_requested_page(page, search_request, target)
        response: Optional[SearchResponse] = None
        # True when the page filled up part-way through a batch, leaving visible
        # hits behind that the next page must not skip.
        cut_mid_batch = False
        # Sort values of the last hit consumed, when that was not the batch's last
        # hit. This is what lets a cut page still resume via search_after (and so
        # still page past index.max_result_window) instead of falling back to
        # raw-offset positioning.
        cut_sort_values: Optional[List[Any]] = None

        try:
            for _ in range(self.search_client.access_filter_max_fetches):
                remaining = target - len(accepted)
                if remaining <= 0:
                    break

                window_room = (
                    OPENSEARCH_MAX_RESULT_WINDOW if resume.search_after else OPENSEARCH_MAX_RESULT_WINDOW - raw_offset
                )
                if window_room <= 0:
                    break

                # Over-fetch: most callers can see most results, so one round trip
                # usually suffices. The refills below cover the ones who cannot.
                search_request.limit = min(remaining * self.search_client.access_filter_overfetch_factor, window_room)
                response = await self.search_client.search(
                    search_request=search_request,
                    url_whitelist=url_whitelist,
                    page=resume.model_copy(update={"offset": page.offset + len(accepted), "raw_offset": raw_offset}),
                )

                visible = await self._visible_uris(response.hits)
                consumed = 0
                for consumed, hit in enumerate(response.hits, start=1):
                    if hit.source.get("base_key", "") in visible:
                        accepted.append(hit)
                        if len(accepted) >= target:
                            break
                cut_mid_batch = consumed < len(response.hits)
                cut_sort_values = response.hits[consumed - 1].sort_values if cut_mid_batch else None
                raw_offset += consumed

                if not response.hits or not response.has_more or len(accepted) >= target:
                    break

                # Whole batch consumed, so the backend's resume state applies
                # verbatim — including the search_after values a deep walk needs
                # and the ranking id that lets the next fusion skip the legs.
                resume = self._resume_from(response, resume)
                if resume is None:
                    break
        finally:
            search_request.limit = target

        if response is None:  # pragma: no cover - the loop always runs at least once
            raise RuntimeError("access-filtered search produced no backend response")

        return self._finalize_filled_page(
            response=response,
            search_request=search_request,
            page=page,
            accepted=accepted,
            raw_offset=raw_offset,
            cut_mid_batch=cut_mid_batch,
            cut_sort_values=cut_sort_values,
        )

    @staticmethod
    def _resume_from(response: SearchResponse, previous: PageSpec) -> Optional[PageSpec]:
        """Carry the backend's next-page state into the following refill."""
        if not response.next_cursor:
            return None
        payload = decode_cursor(response.next_cursor)
        return previous.model_copy(
            update={
                "window": payload.window,
                "search_after": payload.search_after,
                "ranking_id": payload.ranking_id,
                "mode": payload.mode,
            }
        )

    def _finalize_filled_page(
        self,
        response: SearchResponse,
        search_request: DeepSearchSearchRequestV2,
        page: PageSpec,
        accepted: List[SearchResult],
        raw_offset: int,
        cut_mid_batch: bool,
        cut_sort_values: Optional[List[Any]] = None,
    ) -> SearchResponse:
        """Restate the last backend response in the caller-visible offset space."""
        response.hits = accepted
        # Cutting mid-batch means visible hits were left behind, so there is more
        # to serve even if the backend had reached the end of what it fetched.
        #
        # Deliberately NOT conditioned on `accepted`: a caller whose visible
        # documents all sit deeper than the refill budget reaches gets an empty
        # page, and gating has_more on it would strand them there with no way to
        # continue. Progress is still guaranteed — the raw offset advances by
        # everything consumed, and the backend only reports has_more when it
        # actually returned hits.
        has_more = cut_mid_batch or response.has_more
        next_offset = page.offset + len(accepted)
        info = response.pagination or {}
        # Sort values only steer retrieval in LEG mode — RRF fetches the whole
        # window and slices in Python, so carrying them there would be inert at
        # best and misleading at worst.
        #
        # deduplicate_by_hash is excluded for a harder reason: the server rejects
        # `collapse` alongside `search_after` outright (7.1b), so handing the next
        # page resume values would not merely be useless, it would make that page
        # fail. This mirrors the backend's own guard in _build_pagination_state.
        resume_sort = (
            cut_sort_values
            if cut_mid_batch and info.get("mode") == PaginationMode.LEG and not search_request.deduplicate_by_hash
            else None
        )

        if not has_more:
            response.next_cursor = None
        elif response.next_cursor:
            # The backend's resume values belong to the last hit of the batch, not
            # to the point we stopped at, so on a mid-batch cut they would skip
            # everything in between. Restamp them with the cut hit's own sort
            # values when we have them — that keeps the walk on search_after, the
            # only mechanism that reaches past index.max_result_window. Without
            # them (RRF mode, cached-ranking pages) drop them and position by raw
            # offset instead: exact, but capped at the result window.
            response.next_cursor = rebase_cursor(
                response.next_cursor,
                offset=next_offset,
                raw_offset=raw_offset,
                search_after=resume_sort,
                drop_search_after=cut_mid_batch,
            )
        else:
            # The backend saw no further page (it had consumed everything it
            # fetched) but we stopped short of that, so mint the continuation
            # ourselves. No ranking id is available on this path, which only costs
            # the next page a recompute of the fused order.
            response.next_cursor = build_cursor(
                mode=PaginationMode(info.get("mode", PaginationMode.RRF)),
                query_fingerprint=fingerprint_request(search_request),
                offset=next_offset,
                raw_offset=raw_offset,
                window=info.get("window"),
                search_after=resume_sort,
                ttl_seconds=self.search_client.cursor_ttl(),
            )

        response.has_more = has_more
        if response.pagination is not None:
            response.pagination["offset"] = page.offset
            response.pagination["page_size"] = len(accepted)
        return response

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
        page: Optional[PageSpec] = None,
    ) -> SearchResponse:
        """
        Enhanced search method that applies a pipeline of filters and enhancements to search results.

        Pipeline steps:
        1. Process image queries
        2. Get scene asset whitelist (if searching in scene)
        3. Resolve the requested page (offset / cursor)
        4. Perform base search with filters, refilling the page past access filtering
        5. Enhance with instance prim information

        Raises:
            PaginationError: the request's ``cursor``/``offset`` is unusable —
                corrupt, expired, issued for a different query, past the depth
                cap, or combined with ``validate_results``. Every case is
                caller-correctable, so routers map it to 400.
        """
        target = search_request.limit

        # Step 1: Process image queries
        search_request = await self._download_remote_images(search_request)

        # Step 2: Get scene asset whitelist
        url_whitelist = await self._get_scene_asset_whitelist(search_request)

        # Step 3: Resolve the page
        if page is None:
            page = page_spec_for_request(search_request, self.search_client.pagination_max_offset)
            if from_ and not page.is_paginating:
                # Legacy positional offset. Superseded by offset/cursor on the
                # request, but still honoured for existing callers.
                page = page.model_copy(update={"offset": from_, "raw_offset": from_})

        # Step 4: Perform base search
        with tracer.start_as_current_span("filtered_search_client.search"):
            if self._access_filtering_enabled:
                search_results = await self._search_filling_page(search_request, page, url_whitelist, target)
            else:
                search_results = await self.search_client.search(
                    search_request=search_request, url_whitelist=url_whitelist, page=page
                )

        # Step 5: Enhance with instance prim information
        search_results = await self._enhance_with_instance_prims(search_results, search_request, config)

        logger.debug(f"Returning {len(search_results.hits)} search results after filtering")
        return search_results
