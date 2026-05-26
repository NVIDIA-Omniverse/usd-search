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
import io
import logging
import os
import time
from contextlib import nullcontext
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
)

import numpy as np
from ngsearch_backend import ClientUnavailable
from ngsearch_backend.elasticsearch_backend import ElasticSearchBackend
from ngsearch_backend.opensearch_backend import OpenSearchBackend
from opentelemetry import trace

# third party modules
from PIL import Image, ImageOps
from siglip2_triton_client.client import (
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
)

from search_utils import observability_utils
from search_utils.log_utils import print_wrapper, set_simple_logger
from search_utils.misc_utils import aiter_limit, image_from_base64

# properietary modules
from search_utils.storage_client import StorageClient, StorageConnection
from search_utils.storage_client.data import VerifyBatchAccessResponse
from search_utils.telemetry_utils import (
    AsyncIteratorWrapper,
    SearchTelemetry,
    Telemetry,
)

from .data import (
    BackendSearchItem,
    ImagePreProcessing,
    ProcessedQuery,
    SearchGenResponse,
)
from .exceptions import ThumbnailMissing
from .utils import strip_alpha_channel

logger = set_simple_logger("clip backend", os.getenv("LOG_LEVEL", "INFO"))

DEBUG_LOGGING = logger.isEnabledFor(logging.DEBUG)

tracer = trace.get_tracer(__name__)


class CLIPEmbed:
    def __init__(
        self,
        search_observability: observability_utils.SearchBackendObservability,
        ov_server: str,
        backend_type: str = os.getenv("SEARCH_BACKEND_TYPE", "es_index"),
        ims_per_sample: int = int(os.getenv("DEFAULT_IMS_PER_SAMPLE", "8")),
        hidden_urls: list = ["omniverse://ov-content.nvidia.com:3009/Projects/MidnightCreatives/Projects/RnD/"],
        exclude_uri_substrings: Optional[list] = None,
        batch_size: int = 5,
        storage_client: Optional[StorageClient] = None,
        **backend_kwargs,
    ):
        self.backend_type = backend_type
        self.exclude_uri_substrings = exclude_uri_substrings
        self.batch_size = batch_size
        self.storage_client = storage_client
        self.ov_server = ov_server

        if backend_type == "es_index":
            assert "index_name" in backend_kwargs.keys(), "Path to images is not found, please specify 'index_name'"
            self.backend = ElasticSearchBackend(**backend_kwargs, es_observability=search_observability)
        elif backend_type == "os_index":
            self.backend = OpenSearchBackend(**backend_kwargs, es_observability=search_observability)
        else:
            raise NotImplementedError(f"The selected backend '{backend_type}' is not supported")

        self.ims_per_sample = ims_per_sample

    def __len__(self) -> int:
        """Return length of the datasource

        Returns:
            int: total number of items in the datasource
        """
        return len(self.backend)

    def keys(self):
        """Generator for backend keys

        Yields:
            str: backend key
        """
        for k in self.backend.keys():
            yield k

    @staticmethod
    def preprocess_image(
        img: Image,
        image_size: Tuple[int, int] = (224, 224),
        image_pre_processing: ImagePreProcessing = ImagePreProcessing.fit,
    ) -> Image:
        with tracer.start_as_current_span("preprocess_image") as span:
            span.set_attribute("image_size", image_size)
            span.set_attribute("image_pre_processing", image_pre_processing.value)

            if ImagePreProcessing(image_pre_processing) == ImagePreProcessing.fit:
                img = ImageOps.fit(img, image_size)
            elif ImagePreProcessing(image_pre_processing) == ImagePreProcessing.resize:
                logger.warning("Resizing input image may lead to incorrect aspect ratios")
                img = img.resize(image_size)
            elif ImagePreProcessing(image_pre_processing) == ImagePreProcessing.pad:
                logger.warning("Padding image with zeros - may influence resulting embedding")
                img = ImageOps.pad(img, image_size)
            else:
                raise NotImplementedError(f"image preprocessing method: '{image_pre_processing}' is not supported")

            return img

    async def process_input_query(
        self,
        query: List[str],
        embedding_client: TritonEnsembleTextClient | TritonEnsembleImageClient,
        image_size: Tuple[int, int] = (384, 384),
        image_pre_processing: ImagePreProcessing = ImagePreProcessing.fit,
        connection: Optional[StorageConnection] = None,
    ):
        """Process input query

        Args:
            query (list, str): input list of querries (can be text or base64 encoded image)

        Returns:
            encoded representation of the query
        """
        if query is None:
            return query

        if not isinstance(query, list):
            query = [query]

        content: Dict[str, List[str]] = {"image": [], "text": []}
        indexes: Dict[str, List[int]] = {"image": [], "text": []}

        with print_wrapper("forward pass", logger=logger.debug):
            for it, q in enumerate(query):
                if q.startswith("data:image/"):
                    with tracer.start_as_current_span("decode_base64_image"):
                        st = q.find(";base64,")
                        q = q[st + 8 :]
                        msg = base64.b64decode(q.encode())
                        buf = io.BytesIO(msg)
                        img = Image.open(buf)
                    img: Image = self.preprocess_image(
                        img,
                        image_size=image_size,
                        image_pre_processing=image_pre_processing,
                    )

                    content["image"].append(strip_alpha_channel(np.asarray(img)))
                    indexes["image"].append(it)
                elif self.storage_client.is_supported_uri(q):
                    try:
                        with tracer.start_as_current_span("omni_load_thumbnail"):
                            client: StorageClient
                            async with self.storage_client.connection_context(connection=connection) as client:
                                data, _ = await client.load_thumbnail(q)

                        with io.BytesIO(data) as stream:
                            img = Image.open(stream).convert("RGBA")

                    except FileNotFoundError as e:
                        logger.warning(
                            "Thumbnail missing in nucleus, loading from es_cache",
                            exc_info=e,
                        )

                        with tracer.start_as_current_span("es_load_thumbnail"):
                            try:
                                # get item from storage

                                item_content = await self.backend.search_cache.async_getitem(
                                    key=self.storage_client.get_uri_from_path(self.storage_client.get_path_from_uri(q)),
                                    raw=False,
                                    skip_storage=True,
                                )

                                if len(item_content.get("image", [])) > 0:
                                    base64_im = await self.backend.search_cache.storage["image"].async_getitem(
                                        key=item_content["image"][0]
                                    )
                                    img = image_from_base64(base64_im)
                                else:
                                    logger.warning("Thumbnail missing in es_cache", exc_info=e)
                                    raise ThumbnailMissing(f"thumbnail for {q} is missing") from e
                            except KeyError:
                                logger.warning("Thumbnail missing in es_cache", exc_info=e)
                                raise ThumbnailMissing(f"thumbnail for {q} is missing") from e

                    img: Image = self.preprocess_image(
                        img,
                        image_size=image_size,
                        image_pre_processing=image_pre_processing,
                    )

                    content["image"].append(strip_alpha_channel(np.asarray(img)))
                    indexes["image"].append(it)
                else:
                    content["text"].append(q)
                    indexes["text"].append(it)

            query_feats_dict = {}

            if embedding_client is None:
                raise ClientUnavailable("Embedding client unavailable")

            if len(content["image"]) > 0:
                with tracer.start_as_current_span("embedding_process_image_list") as span:
                    span.set_attribute("content_len", len(content["image"]))
                    image_query_feats = await embedding_client.predict(content["image"])
                query_feats_dict.update({it: feat for it, feat in zip(indexes["image"], image_query_feats)})

            if len(content["text"]) > 0:
                with tracer.start_as_current_span("embedding_process_text_list") as span:
                    span.set_attribute("content_len", len(content["text"]))
                    text_query_feats = await embedding_client.predict(content["text"])
                query_feats_dict.update({it: feat for it, feat in zip(indexes["text"], image_query_feats)})

        return [query_feats_dict[it] for it in range(len(query_feats_dict))]

    @staticmethod
    def cosine_dist(x1, x2):
        n1 = np.linalg.norm(x1, axis=-1, keepdims=True)
        n2 = np.linalg.norm(x2, axis=0, keepdims=True)
        return (1 - np.dot(x1, x2) / (n1 * n2)) / 2

    async def filter_search_results_async(
        self,
        search_gen: AsyncGenerator[Any, None],
        N: int,
        filter_repeating: bool = True,
        similarity_threshold: float = 0,
        batch_size: int = 5,
    ) -> AsyncGenerator[Any, None]:
        """Process search results.

        Args:
            search_gen: generator of search results
            N (int): Number of requested search results.
            filter_repeating (bool, optional): if ``True`` - filter out items with the same path. Defaults to ``True``.
            similarity_threshold (float, optional): if > 0 filter those items, which embeddings are smaller then a given distance. Defaults to 0.

        Returns:
            tuple: list of file names, list of resulting values, list of unique file IDs
        """

        with print_wrapper("post-processing", logger=logger.debug, print_after=False):
            # prepare results for output
            fnames, res_values, embeds = set([]), set([]), None
            # outer loop through batch generator
            counter = 0
            filtered_results = []
            items: Optional[List[SearchGenResponse]] = None
            async for items in search_gen:
                # inner loop through batch
                it: SearchGenResponse
                for it in items:
                    processed_item: ProcessedQuery = it.item

                    embed = (
                        np.array(processed_item["embedding"], dtype=np.float32)
                        if processed_item.get("embedding")
                        else None
                    )
                    # check if file should be ignored
                    if self.check_excluded(processed_item["path"]):
                        continue
                    # > filter based on file names and unique IDs (hashes)
                    if filter_repeating:
                        if processed_item["path"] in fnames:
                            continue
                        # > filter based on similarity
                        if similarity_threshold > 0 and embeds is not None and embed is not None:
                            dist = self.cosine_dist(embeds, embed.reshape(-1, 1))
                            if np.min(dist) < similarity_threshold:
                                continue

                        # append values to respective lists
                        if similarity_threshold > 0 and embed is not None:
                            if embeds is None:
                                embeds = embed.reshape(1, -1)
                            else:
                                embeds = np.concatenate([embeds, embed.reshape(1, -1)], axis=0)
                    # update output lists
                    fnames.add(processed_item["path"])
                    res_values.add(processed_item["score"])

                    filtered_results.append(
                        self.get_base_item_dict(
                            f=processed_item["path"],
                            value=processed_item["score"],
                            id=counter,
                            omni_file=processed_item.get("source"),
                            acl=it.acl,
                            embed=embed,
                            image_key=processed_item.get("image_key"),
                        )
                    )
                    counter += 1
                    if batch_size > 0 and len(filtered_results) >= batch_size:
                        yield filtered_results
                        filtered_results = []

                    # added a possibility to have endless generator
                    if N > 0 and len(fnames) >= N:
                        break

                # added a possibility to have endless generator
                if N > 0 and len(fnames) >= N:
                    break

            # return results
            if items is not None and (len(items) == 0 or len(filtered_results) > 0):
                yield filtered_results
                filtered_results = []

    def get_base_item_dict(
        self,
        f: str,
        value: float,
        id: str,
        image_key: Optional[str] = None,
        omni_file: Optional[Dict[Any, Any]] = None,
        acl: Optional[List[str]] = None,
        embed: Optional[np.ndarray] = None,
    ) -> BackendSearchItem:
        return dict(
            name=f,
            value=str(100 * value),
            enabled=True,
            f=f,
            id=id,
            image_key=image_key,
            omni_file=omni_file,
            acl=acl,
            es_score=value,
            embed=embed,
        )

    async def item_preparation_async(
        self,
        item: BackendSearchItem,
        noimages: bool,
        nopredictions: bool,
        embedding_client: TritonEnsembleTextClient | TritonEnsembleImageClient,
    ) -> BackendSearchItem:
        if not noimages:
            item["render"] = await self.backend.async_get_image(item["image_key"]) if item["image_key"] else None
        if not nopredictions:
            # here we run get predictions method for a single item
            predictions = await self.backend.get_pred(
                embed=item["embed"].reshape(1, -1),
                embedding_client=embedding_client,
            )
            if len(predictions) > 0:
                item["prediction"] = [{"tag": k, "prob": float(v)} for k, v in predictions[0].items()]
            else:
                item["prediction"] = []
        return item

    async def prepare_response_async(
        self,
        results_gen: AsyncGenerator[Any, None],
        noimages: bool,
        nopredictions: bool,
        embedding_client: TritonEnsembleTextClient | TritonEnsembleImageClient,
    ) -> AsyncGenerator[Any, None]:
        async for items in results_gen:
            if noimages and nopredictions:
                yield items
            else:
                res_list = []
                for it in range(0, len(items), self.batch_size):
                    processed_items = await asyncio.gather(
                        *[
                            self.item_preparation_async(
                                item,
                                noimages,
                                nopredictions,
                                embedding_client=embedding_client,
                            )
                            for item in items[it : it + self.batch_size]
                        ]
                    )
                    for p_item in processed_items:
                        res_list.append(p_item)
                yield res_list

    async def get_top_n_async(
        self,
        query: str,
        max_queries: int,
        embedding_client: TritonEnsembleTextClient | TritonEnsembleImageClient,
        N: int = 5,
        searchable_items_subset: Optional[list[str]] = None,
        noimages: bool = False,
        nopredictions: bool = False,
        noembeddings: bool = True,
        filter_repeating: bool = True,
        similarity_threshold: float = 0,
        cutoff_threshold: Optional[float] = None,
        verify_access: bool = False,
        connection: Optional[dict] = None,
        get_uri: Optional[Callable[..., Any]] = None,
        max_nucleus_requests: int = 512,
        telemetry_token=None,
        batch_size: int = 5,
        only_key: bool = False,
        use_telemetry: bool = True,
        telemetry_obj: Telemetry = SearchTelemetry,
        model_name: str = "clip",
        **kwargs,
    ):
        # make sure required parameter are set-up
        if verify_access:
            # assert connection is not None, "Omniverse connection is not available"
            assert get_uri is not None, "Function for retrieving omniverse path is not available"

        telemetry_context = (
            telemetry_obj.time_context(name="embedding extraction", key=telemetry_token)
            if use_telemetry
            else nullcontext()
        )
        # process input query with telemetry
        try:
            with telemetry_context, tracer.start_as_current_span("embedding_extraction"):
                query_feats = await self.process_input_query(query, embedding_client, connection=connection)
        except ClientUnavailable as exc:
            if kwargs.get("force_global_filter") is None and kwargs.get("force_nested_filter") is None:
                raise ClientUnavailable("Embedding client unavailable") from exc
            else:
                logger.warning("Embedding client unavailable")
                query_feats = None

        # get the first element from the query feat list
        if query_feats is not None:
            query_feats = query_feats[0]

        if only_key:
            logger.debug("Only Key is requested - similarity-based post-filtering of results is deactivated")
            filter_repeating = False
            similarity_threshold = 0
            assert noimages, "Images are requested - incompatible"
            assert nopredictions, "Predictions are requested - incompatible"

        # get source filter
        search_config = self.backend.get_source_filter(
            noembeddings=noembeddings,
            noimages=noimages,
            only_key=only_key,
            searchable_items_subset=searchable_items_subset,
        )
        if DEBUG_LOGGING:
            logger.debug(f"Search Config: {search_config}")

        async def search_gen() -> AsyncIterator[List[SearchGenResponse]]:
            # always return results in batches.
            #  If users would like to get all the data at once - they should increate the batch size
            n_items = batch_size

            # add telemetry
            es_search_counter = 0
            es_search_start = time.time()
            cutoff_trigger = False

            if DEBUG_LOGGING:
                logger.debug(f"{query_feats}, {n_items}, {search_config}, {kwargs}")

            items: List[ProcessedQuery]
            async for items in aiter_limit(
                AsyncIteratorWrapper(
                    self.backend.search_streaming_async(query_feats, n_items, search_config=search_config, **kwargs),
                    "search_streaming_async",
                ),
                max_queries,
            ):
                if use_telemetry:
                    telemetry_obj.add(
                        {f"es_search_{es_search_counter}": time.time() - es_search_start},
                        key=telemetry_token,
                    )
                es_search_counter += 1

                if cutoff_threshold is not None:
                    cut_items = [item for item in items if item["score"] > cutoff_threshold]

                    if len(cut_items) == 0:
                        yield []
                        break

                    if len(cut_items) < len(items):
                        cutoff_trigger = True
                        items = cut_items

                if verify_access:
                    it = 0
                    verification_start = time.time()

                    client: StorageClient
                    async with self.storage_client.connection_context(connection=connection) as client:
                        res: List[VerifyBatchAccessResponse]
                        async for res in AsyncIteratorWrapper(
                            client.batch_verify_access(
                                uri_list=[itm["path"] for itm in items],
                                max_nucleus_requests=max_nucleus_requests,
                            ),
                            "batch_verify_access",
                        ):
                            batch = items[it * max_nucleus_requests : (it + 1) * max_nucleus_requests]
                            assert len(batch) == len(res)
                            # add a note to telemetry DB
                            if use_telemetry:
                                telemetry_obj.add(
                                    {f"verification_{es_search_counter}_{it}": time.time() - verification_start},
                                    key=telemetry_token,
                                )
                            yield [SearchGenResponse(item=b, acl=r.acl) for b, r in zip(batch, res) if r.exists]
                            it += 1
                            verification_start = time.time()
                else:
                    yield [SearchGenResponse(item=b, acl=None) for b in items]

                if cutoff_trigger:
                    break

                es_search_start = time.time()

        # process search results
        search_results_gen = self.filter_search_results_async(
            AsyncIteratorWrapper(search_gen(), "search_gen"),
            N,
            filter_repeating,
            similarity_threshold,
            batch_size,
        )

        if only_key:
            return search_results_gen
        else:
            # prepare the response
            return self.prepare_response_async(
                search_results_gen,
                noimages,
                nopredictions,
                embedding_client=embedding_client,
            )

    async def async_list_keywords(self, **kwargs):
        return await self.backend.async_list_keywords(**kwargs)

    def check_excluded(self, f: str) -> bool:
        """check ignored substrings

        Args:
            f (str): path to a file in omniverse

        Returns:
            bool: ``True`` if the item should be ignored
        """
        if self.exclude_uri_substrings is None or len(self.exclude_uri_substrings) == 0:
            return False
        # check ignored substrings
        for s in self.exclude_uri_substrings:
            if s in f:
                return True
        return False
