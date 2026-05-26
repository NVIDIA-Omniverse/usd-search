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
import os
import time

# local/proprietary modules
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# third-party modules
import numpy as np
import orjson
from cache.src import GenericPluginStatus, PluginItemStatus
from deepsearch_utils.ds_plugin_utils import (
    DSPluginStatus,
    GetFileResponse,
    SearchBackendLabels,
    add_search_storage_metadata,
    delete_search_storage_metadata,
    get_siglip2_client,
    get_system_values,
    run_embedding_model_batch,
)
from deepsearch_utils.image_processing_utils import load_image_from_bytes_by_type
from deepsearch_utils.rendering_utils import RenderingStatus, clean_up
from numpy import ndarray as NDArray
from opentelemetry import trace
from PIL import Image
from storage.src.client import NGSearchStorageHelper

from search_utils.misc_utils import image_to_base64
from search_utils.storage_client import PathType, StorageClient
from search_utils.storage_client.data import ThumbnailItem, ThumbnailLoadMode

from .base_plugin import BasePlugin, PLuginBatchItem
from .config import ThumbnailToEmbeddingConfig
from .models import GenericPluginErrorItem, PluginProcessingResult

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class ThumbnailPluginStatus(str, Enum):
    thumbnail_missing = "thumbnail_missing"
    thumbnail_invalid = "thumbnail_invalid"


class ThumbnailToEmbedding(BasePlugin):
    """
    For any asset stored on the storage backend this plugin relies on the thumbnail of this asset to extract CLIP embeddings.
    """

    def __init__(
        self,
        config: Optional[ThumbnailToEmbeddingConfig] = None,
        thumbnail_embedding_suffix: Optional[str] = None,
    ):
        if config is None:
            config = ThumbnailToEmbeddingConfig()
        super().__init__(
            plugin_name="thumbnail_to_embedding",
            data_types=set(["any"]),
            render=False,
            namespace=".deeptag.embedding",
            system_namespace=".deeptag.thumbnail_to_embed_plugin",
            config=config,
        )
        self.thumbnail_embedding_suffix = "" if thumbnail_embedding_suffix is None else thumbnail_embedding_suffix
        self._batch_data_field = "thumbnails"
        self.thumbnail_resolutions = [256]
        self.use_elastic_search = True
        self._embedding_client = get_siglip2_client()

    @property
    def embedding_client(self):
        return self._embedding_client

    def asset_state_hash(self, hash_value: str) -> str:
        return hash_value + "_" + self.embedding_client.clip_service.value

    @property
    def config(self) -> ThumbnailToEmbeddingConfig:
        return self._config

    def res_map(self, res: int) -> Tuple[int, int]:
        if res == 108:
            return (138, 108)
        elif res == 256:
            return (256, 256)
        else:
            logger.error("Unknown resolution: %s", str(res))
            raise NotImplementedError(f"Unknown resolution: {res}")

    def load_data(
        self,
        omni_path: Optional[str] = None,
        data: Optional[NDArray[np.float32]] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        if data is None and status is None:
            logger.debug(f"content for '{omni_path}' is not provided")
            return {}
        if data is None and status is not None:
            return {
                "omni_path": omni_path,
                "status": status,
                "error_message": error_message,
            }
        return {self.batch_data_field: data, "omni_path": omni_path}

    async def add_metadata(self, path: str, content: dict, storage_client: NGSearchStorageHelper) -> None:
        return await add_search_storage_metadata(
            path=path,
            labels=SearchBackendLabels(plugin_name=self.plugin_name),
            content=content,
            storage_client=storage_client,
        )

    async def delete_metadata(self, path: str, storage_client: NGSearchStorageHelper) -> None:
        await delete_search_storage_metadata(
            path=path,
            storage_client=storage_client,
            labels=SearchBackendLabels(plugin_name=self.plugin_name),
        )

    async def get_omni_file(
        self, omni_item: PathType, storage_client: StorageClient, timeout: float = 120
    ) -> GetFileResponse:
        status = DSPluginStatus.load_error

        content: list[Image.Image] = []
        try:
            thumbnails: List[ThumbnailItem] = await storage_client.load_thumbnail(
                uri=omni_item.uri,
                thumbs_loc=self.config.thumbnail_location,
                res_map=[self.res_map(res) for res in self.thumbnail_resolutions],
                suffixes=self.config.thumbnail_suffixes,
                thumbnail_path_templates=self.config.thumbnail_filepath_patterns,
                mode=ThumbnailLoadMode.all,
                timeout=timeout,
            )
            for thumbnail in thumbnails:
                imgs = load_image_from_bytes_by_type(
                    content=thumbnail.data,
                    file_format=os.path.splitext(thumbnail.uri)[1],
                    offset_ms=self.config.gif_offset_ms,
                )
                content.extend(imgs)
            status = DSPluginStatus.valid
        except FileNotFoundError:
            status = DSPluginStatus.thumbs_missing
        except Exception as e:
            status = DSPluginStatus.load_error
            logger.exception("%s asset loading exception: %s", omni_item.uri, str(e))

        return GetFileResponse(data=content if len(content) > 0 else None, status=status)

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:

        if len(indices) == 0:
            return {}

        model_hash = self.embedding_client.clip_service.value
        omni_paths = [b["omni_path"] for b in batch_data]
        omni_tags = [[[f"model_hash:{model_hash}"] for _ in b[self.batch_data_field]] for b in batch_data]
        previews = [list(b[self.batch_data_field]) for b in batch_data]

        output_dict = {
            "embed": await run_embedding_model_batch(
                embedding_client=self.embedding_client,
                image_lists=previews,
            )
        }
        sample_ind = [sample_ids[i] for i in indices]
        assert len(sample_ind) == len(
            output_dict["embed"]
        ), f"Lengths do not match: {len(sample_ind)} vs {len(output_dict['embed'])}"
        return self.prepare_results(output_dict, sample_ind, omni_paths, previews, omni_tags)

    def prepare_results(
        self,
        input_dict: dict,
        sample_ind: list,
        omni_paths: list,
        images: list = None,
        omni_tags: Optional[list] = None,
    ) -> Dict[int, PluginProcessingResult]:
        with tracer.start_as_current_span("thumbnail_to_embedding.prepare_results") as span:
            span.set_attribute("input_dict_length", len(input_dict))
            span.set_attribute("sample_ind_length", len(sample_ind))
            span.set_attribute("omni_paths_length", len(omni_paths))
            span.set_attribute("images_length", len(images))
            span.set_attribute("omni_tags_length", len(omni_tags))
            assert "embed" in input_dict.keys(), "Invalid classifier output: 'embed' not found in keys()"

            update_list = []
            for i in range(len(omni_paths)):
                embeds: np.ndarray
                ims: list[Image.Image]

                embeds = input_dict["embed"][i]
                ims = images[i]
                if omni_tags is not None:
                    tags = omni_tags[i]

                assert len(embeds) == len(ims), f"data lengths does not match: ({len(embeds)} vs {len(ims)})"

                labels = SearchBackendLabels(plugin_name=self.plugin_name)

                content = {
                    "embedding": [emb.flatten().tolist() for emb in embeds],
                    "image": [image_to_base64(im) for im in ims],
                    "label": [
                        orjson.dumps({"thumbnail_id": f"{emb_id}", **labels}).decode() for emb_id in range(len(embeds))
                    ],
                }
                if omni_tags is not None:
                    content["keyword"] = tags
                assert (
                    len(content["embedding"])
                    == len(content["image"])
                    == len(content["label"])
                    == len(content["keyword"])
                ), "Lengths do not match"
                update_list.append(content)
        return {
            smpl_ind: PluginProcessingResult(
                asset_status=PluginItemStatus(
                    status=GenericPluginStatus.ok.value,
                    processing_timestamp=time.time(),
                ),
                search_backend_content={self.plugin_name: es_content},
                **get_system_values(system_namespace=self.system_namespace),
            )
            for smpl_ind, es_content in zip(sample_ind, update_list)
        }

    async def preprocess(
        self, data: List[Dict[str, Any]], **kwargs
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:

        error_indices: Dict[int, GenericPluginErrorItem] = {}
        indices: List[int] = []
        batch_data = []

        with tracer.start_as_current_span("thumbnail_to_embedding.preprocess") as span:
            span.set_attribute("data_length", len(data))
            logger.debug(f"Processing batch raw data: {data}")
            for item_index, item in enumerate(data):
                b_data: Dict[str, Any] = {}

                if self.batch_data_field in item.keys():
                    image_list: List[Image.Image] = []
                    im: Image.Image
                    message = ""
                    for im in item[self.batch_data_field]:
                        if im.size != (1, 1):
                            image_list.append(im.convert("RGB"))
                        else:
                            logger.warning(f"Thumbnail for {item['omni_path']} is invalid: size is {im.size}")
                            message += f"Thumbnail for {item['omni_path']} is invalid: size is {im.size}"

                    if len(image_list) == 0:
                        error_indices[item_index] = GenericPluginErrorItem(
                            status=ThumbnailPluginStatus.thumbnail_invalid,
                            error_message=message if message else "Thumbnail invalid",
                        )
                        continue
                    b_data[self.batch_data_field] = image_list
                    indices.append(item_index)
                else:
                    error_indices[item_index] = GenericPluginErrorItem(
                        status=ThumbnailPluginStatus.thumbnail_missing,
                        error_message="Thumbnail unavailable",
                    )
                    continue

                b_data["omni_path"] = item["omni_path"]
                batch_data.append(b_data)

        return self.verify_data(batch_data, indices, error_indices)

    def clean_up(self) -> bool:
        return clean_up()

    def verify_data(
        self, batch_data: list, indices: list, error_indices: Dict[str, Any]
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:

        indexes_to_del = set([data_ind for data_ind, d in enumerate(batch_data) if len(d[self.batch_data_field]) == 0])

        if len(indexes_to_del) > 0:
            logger.info("%d did not pass verification", len(indexes_to_del))

        error_indices.update(
            {
                ind: GenericPluginErrorItem(status=RenderingStatus.empty_scene)
                for ind_ind, ind in enumerate(indices)
                if ind_ind in indexes_to_del
            }
        )
        indices = [ind for ind_ind, ind in enumerate(indices) if ind_ind not in indexes_to_del]
        batch_data = [data for ind_ind, data in enumerate(batch_data) if ind_ind not in indexes_to_del]

        return batch_data, indices, error_indices
