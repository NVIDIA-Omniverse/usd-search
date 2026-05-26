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

import logging
from typing import Dict, List, Optional

from deepsearch_api.routers_v2.models import Metadata, Prediction, SearchResult
from deepsearch_api.search_backend.embeddings import BaseEmbeddingInterface
from deepsearch_api.search_backend.image_loader import BaseImageLoader
from deepsearch_api.search_backend.models import (
    DeepSearchSearchRequestV2,
    SearchResponse,
)
from deepsearch_api.search_backend.utils import extract_embeddings_from_hit_source

logger = logging.getLogger(__name__)


async def convert_search_response(
    original_response: SearchResponse,
    search_request: DeepSearchSearchRequestV2,
    image_loader: Optional[BaseImageLoader] = None,
    embedding_client: Optional[BaseEmbeddingInterface] = None,
) -> List[SearchResult]:
    """
    Convert the original SearchResponse format to the new SearchResult format.

    Args:
        original_response: The SearchResponse from the search backend
        search_request: The original search request
        image_loader: Optional image loader for fetching actual image data
    """
    converted_results = []

    if not image_loader:
        logger.warning("No image loader provided, images will not be loaded. " "Results will contain only image IDs.")

    # Collect all image IDs that need to be loaded
    image_ids_to_load = []
    embeddings: Dict[str, List[float]] = {}
    if search_request.return_images and image_loader:
        for hit in original_response.hits:
            # First try to get image IDs from inner_hits (preferred method for nested queries)
            inner_hits_found = False
            if hit.inner_hits:
                inner_hits = hit.inner_hits

                # Look for siglip2-embedding inner hits
                for inner_hit_key in [
                    "siglip2-embedding",
                    "embedding_description",
                    "embedding_image_similarity_search",
                ]:
                    if inner_hit_key in inner_hits:
                        inner_hit_data = inner_hits[inner_hit_key]
                        if isinstance(inner_hit_data, dict) and "hits" in inner_hit_data:
                            for inner_hit in inner_hit_data["hits"].get("hits", []):
                                inner_source = inner_hit.get("_source", {})
                                image_id = inner_source.get("image")
                                if image_id and image_id not in image_ids_to_load:
                                    image_ids_to_load.append(image_id)
                                    inner_hits_found = True

            # Fallback to source siglip2-embedding if no inner_hits found
            if not inner_hits_found:
                source = hit.source
                if "siglip2-embedding" in source:
                    siglip2_embeddings = source["siglip2-embedding"]
                    if isinstance(siglip2_embeddings, list) and len(siglip2_embeddings) > 0:
                        image_id = siglip2_embeddings[0].get("image")
                        if image_id and image_id not in image_ids_to_load:
                            image_ids_to_load.append(image_id)

    if search_request.return_predictions:
        for hit in original_response.hits:
            embeddings[hit.source.get("base_key", "")] = extract_embeddings_from_hit_source(hit.source)

    # Load all images in batch if needed
    loaded_images = {}
    if image_ids_to_load:
        loaded_images = await image_loader.load_images(image_ids_to_load)

    # load predictions if needed:
    predictions_dict: Dict[str, List[Prediction]] = {}
    if len(embeddings) > 0 and search_request.return_predictions and embedding_client:
        key_list = []
        values_list = []
        for key, emd in embeddings.items():
            if emd is None:
                predictions_dict[key] = []
            else:
                key_list.append(key)
                values_list.append(emd)
        if len(values_list) > 0:
            predictions = await embedding_client.get_predictions(values_list)
            if predictions is not None:
                for i, k in enumerate(key_list):
                    predictions_dict[k] = predictions[i]
            else:
                for k in key_list:
                    predictions_dict[k] = None

    for hit in original_response.hits:
        # Extract source data
        source = hit.source

        # Create Prim objects from source data if available

        # Create Metadata object
        metadata = Metadata.model_construct(
            created=source.get("created_timestamp"),
            created_by=source.get("created_by"),
            modified=source.get("modified_timestamp"),
            modified_by=source.get("modified_by"),
            size=source.get("size"),
            etag=source.get("etag"),
        )

        # Extract and load image data
        image = None
        if search_request.return_images:
            # First try to get image ID from inner_hits (preferred method for nested queries)
            image_id = None
            inner_hits_found = False

            if hit.inner_hits:
                inner_hits = hit.inner_hits

                # Look for siglip2-embedding inner hits
                for inner_hit_key in [
                    "siglip2-embedding",
                    "embedding_description",
                    "embedding_image_similarity_search",
                ]:
                    if inner_hit_key in inner_hits:
                        inner_hit_data = inner_hits[inner_hit_key]
                        if isinstance(inner_hit_data, dict) and "hits" in inner_hit_data:
                            hits_list = inner_hit_data["hits"].get("hits", [])
                            if hits_list:
                                # Take the first (highest scoring) inner hit
                                inner_source = hits_list[0].get("_source", {})
                                image_id = inner_source.get("image")
                                if image_id:
                                    inner_hits_found = True
                                    break

            # Fallback to source siglip2-embedding if no inner_hits found
            if not inner_hits_found:
                source = hit.source
                if "siglip2-embedding" in source:
                    siglip2_embeddings = source["siglip2-embedding"]
                    if isinstance(siglip2_embeddings, list) and len(siglip2_embeddings) > 0:
                        image_id = siglip2_embeddings[0].get("image")

            # Set image data
            if image_id:
                if image_loader:
                    # Use loaded image data from batch load
                    image = loaded_images.get(image_id)
                else:
                    # Fallback to using the image ID directly
                    image = image_id

        # Extract vision generated metadata
        vision_generated_metadata = {}
        for key, value in source.items():
            if key.endswith("_vlm_generated"):
                vision_generated_metadata[key] = value

        # Extract tags
        tags = []
        for tag in source.get("tags", []):
            tags.append(
                {
                    "tag": tag.get("tag"),
                    "value": tag.get("value"),
                    "namespace": tag.get("namespace"),
                }
            )

        # Extract USD dimensions
        usd_dimensions = {}
        for key, value in source.items():
            if key.startswith("usd_dimensions.") and value is not None:
                # Remove the "usd_dimensions." prefix
                dimension_key = key[15:]
                usd_dimensions[dimension_key] = value

        # Create new SearchResult
        url = source.get("base_key", "")
        new_result = SearchResult.model_construct(
            url=url,
            score=hit.score,
            image=image,
            metadata=metadata if search_request.return_metadata else None,
            embed=None,
            predictions=(predictions_dict[url] if search_request.return_predictions else None),
            in_scene_instance_prims=hit.ags_data.instance_prims,
            root_prims=hit.ags_data.root_prims,
            default_prims=hit.ags_data.default_prims,
            vision_generated_metadata=(vision_generated_metadata if vision_generated_metadata else None),
            tags=tags if tags else None,
            usd_dimensions=usd_dimensions if usd_dimensions else None,
        )

        converted_results.append(new_result)

    return converted_results
