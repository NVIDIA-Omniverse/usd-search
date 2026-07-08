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
import asyncio
import os
import time

# third-party modules
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
from deepsearch_utils.misc_utils import get_pillow_supported_formats
from deepsearch_utils.rendering_utils import RenderingStatus, clean_up
from opentelemetry import trace
from PIL import Image

# local/proprietary modules
from storage.src.client import NGSearchStorageHelper

from search_utils.log_utils import print_wrapper
from search_utils.misc_utils import image_to_base64
from search_utils.storage_client import PathType, StorageClient

from .base_plugin import BasePlugin, PLuginBatchItem
from .config import ImageToEmbeddingConfig
from .models import GenericPluginErrorItem, PluginProcessingResult

tracer = trace.get_tracer(__name__)


class ImageToEmbeddingPluginStatus(str, Enum):
    image_invalid = "image_invalid"
    file_too_large = "file_too_large"


class ImageToEmbedding(BasePlugin):
    """
    Extracts CLIP embeddings from the images that are found on the storage backend.
    """

    def __init__(self, config: Optional[ImageToEmbeddingConfig] = None):
        if config is None:
            config = ImageToEmbeddingConfig()
        super().__init__(
            plugin_name="image_to_embedding",
            data_types=set(get_pillow_supported_formats() + ["exr"]),
            render=False,
            namespace=".deepsearch.embedding",
            system_namespace=".deepsearch.image_to_embed_plugin",
            config=config,
        )
        self.same_hash_copy = False
        self.max_image_load_time = 300
        self.thumbnail_final_size = 384
        self._batch_data_field = "images"
        self._embedding_client = get_siglip2_client()

    @property
    def embedding_client(self):
        return self._embedding_client

    def asset_state_hash(self, hash_value: str) -> str:
        return hash_value + "_" + self.embedding_client.clip_service.value

    @property
    def config(self) -> ImageToEmbeddingConfig:
        return self._config

    async def add_metadata(self, path: str, content: dict, storage_client: NGSearchStorageHelper):
        return await add_search_storage_metadata(
            path=path,
            labels=SearchBackendLabels(plugin_name=self.plugin_name),
            content=content,
            storage_client=storage_client,
        )

    async def delete_metadata(self, path: str, storage_client: NGSearchStorageHelper):
        await delete_search_storage_metadata(
            path=path,
            storage_client=storage_client,
            labels=SearchBackendLabels(plugin_name=self.plugin_name),
        )

    async def get_omni_file(
        self, omni_item: PathType, storage_client: StorageClient, timeout: float = 60
    ) -> GetFileResponse:
        status = DSPluginStatus.load_error
        max_file_size_bytes = self.config.max_file_size_mb * 1024 * 1024 if self.config.max_file_size_mb > 0 else 0
        error_message = None

        # Pre-download check: use file size from storage metadata if available
        if max_file_size_bytes > 0 and omni_item.size is not None and omni_item.size > max_file_size_bytes:
            self.logger.warning(
                "Skipping %s: file size %d bytes exceeds limit of %d MB",
                omni_item.uri,
                omni_item.size,
                self.config.max_file_size_mb,
            )
            return GetFileResponse(
                data=None,
                status=ImageToEmbeddingPluginStatus.file_too_large.value,
                error_message=f"File size {omni_item.size} bytes exceeds limit of {self.config.max_file_size_mb} MB",
            )

        try:
            self.logger.info("Downloading: %s", omni_item.uri)
            with tracer.start_as_current_span("image_to_embedding.get_omni_file"):
                data = await asyncio.wait_for(
                    storage_client.download_file_content(uri=omni_item.uri, timeout=timeout),
                    timeout=self.max_image_load_time,
                )

            # Post-download check: verify actual downloaded size
            if max_file_size_bytes > 0 and len(data) > max_file_size_bytes:
                self.logger.warning(
                    "Discarding %s: downloaded size %d bytes exceeds limit of %d MB",
                    omni_item.uri,
                    len(data),
                    self.config.max_file_size_mb,
                )
                return GetFileResponse(
                    data=None,
                    status=ImageToEmbeddingPluginStatus.file_too_large.value,
                    error_message=f"Downloaded size {len(data)} bytes exceeds limit of {self.config.max_file_size_mb} MB",
                )

            imgs = load_image_from_bytes_by_type(
                content=data,
                file_format=os.path.splitext(omni_item.uri)[1],
                downsize=self.thumbnail_final_size,
                gif_frame_sample_frequency=self.config.gif_frame_sample_frequency,
                gif_max_frames=self.config.gif_max_frames,
                gif_sampling_mode=self.config.gif_sampling_mode,
            )
            return GetFileResponse(data=imgs, status=DSPluginStatus.valid)
        except Exception as exc_info:
            status = DSPluginStatus.load_error
            error_message = f"Asset loading exception: {str(exc_info)}"
            self.logger.exception("%s asset loading exception: %s", omni_item.uri, str(exc_info))

        return GetFileResponse(data=None, status=status, error_message=error_message)

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        processed_results: Dict[int, PluginProcessingResult] = {}
        if len(indices) > 0:
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
            processed_results = self.prepare_results(output_dict, sample_ind, omni_paths, previews, omni_tags)

        return processed_results

    def prepare_results(
        self,
        input_dict: dict,
        sample_ind: list,
        omni_paths: list,
        images: Optional[list] = None,
        omni_tags: Optional[list] = None,
    ) -> Dict[int, PluginProcessingResult]:
        assert "embed" in input_dict.keys(), "Invalid classifier output: 'embed' not found in keys()"
        with tracer.start_as_current_span("image_to_embedding.prepare_results") as span:
            span.set_attribute("input_dict_length", len(input_dict))
            span.set_attribute("sample_ind_length", len(sample_ind))
            span.set_attribute("omni_paths_length", len(omni_paths))
            span.set_attribute("images_length", len(images))
            span.set_attribute("omni_tags_length", len(omni_tags))

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
                        orjson.dumps({"image_id": f"{emb_id}", **labels}).decode() for emb_id in range(len(embeds))
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
        self,
        data: List[Dict[str, Any]],
        batch_data_dict: dict = None,
        storage_client=None,
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        if batch_data_dict is None:
            batch_data_dict = {}

        error_indices: Dict[int, GenericPluginErrorItem] = {}
        batch_data, indices = [], []

        with (
            print_wrapper(
                f"{self.plugin_name}: processing batch raw data",
                print_after=False,
                logger=self.logger.debug,
                enabled=self.render,
            ),
            tracer.start_as_current_span("image_to_embedding.preprocess") as span,
        ):
            span.set_attribute("data_length", len(data))
            for item_index, item in enumerate(data):
                b_data = dict()

                if self.batch_data_field in batch_data_dict.get(item_index, {}):
                    b_data[self.batch_data_field] = batch_data_dict[item_index][self.batch_data_field]
                else:
                    if self.batch_data_field in item.keys():
                        image_list: list[Image.Image] = []
                        message = ""
                        for im in item[self.batch_data_field]:
                            if im.size != (1, 1):
                                image_list.append(im.convert("RGB"))
                            else:
                                self.logger.warning(
                                    "Image for %s is invalid: size is %s",
                                    item["omni_path"],
                                    im.size,
                                )
                                message += f"Image for {item['omni_path']} is invalid: size is {im.size}. "

                        if len(image_list) == 0:
                            error_indices[item_index] = GenericPluginErrorItem(
                                status=ImageToEmbeddingPluginStatus.image_invalid.value,
                                error_message=(message if message else "All images are 1x1"),
                            )
                            continue
                        b_data[self.batch_data_field] = image_list
                        indices.append(item_index)
                    else:
                        error_indices[item_index] = GenericPluginErrorItem(
                            status=item.get("status", "error"),
                            error_message=item.get("error_message"),
                        )
                        continue
                # add item path to batch
                b_data["omni_path"] = item["omni_path"]
                batch_data.append(b_data)

        return self.verify_data(batch_data, indices, error_indices)

    def clean_up(self) -> bool:
        return clean_up()

    def verify_data(
        self,
        batch_data: list,
        indices: List[int],
        error_indices: Dict[int, GenericPluginErrorItem],
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        indexes_to_del = set([data_ind for data_ind, d in enumerate(batch_data) if len(d[self.batch_data_field]) == 0])
        if len(indexes_to_del) > 0:
            self.logger.info("%d did not pass verification", len(indexes_to_del))
        error_indices.update(
            {
                ind: GenericPluginErrorItem(status=f"{RenderingStatus.empty_scene}")
                for ind_ind, ind in enumerate(indices)
                if ind_ind in indexes_to_del
            }
        )
        indices = [ind for ind_ind, ind in enumerate(indices) if ind_ind not in indexes_to_del]
        batch_data = [data for ind_ind, data in enumerate(batch_data) if ind_ind not in indexes_to_del]
        return batch_data, indices, error_indices
