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
from typing import Any, Dict, Optional, Tuple

from deepsearch_utils.ds_plugin_utils import DSPluginStatus

# local/proprietary modules
from llm_client import MetadataGeneration

from search_utils.storage_client import StorageClient

from .base_plugin import BasePlugin
from .config import ThumbnailToEmbeddingConfig, VisionMetadataPluginConfig
from .image_to_vision_metadata import ImageToVisionMetadata
from .models import GenericPluginErrorItem
from .thumbnail_to_embedding import ThumbnailToEmbedding

# third-party modules


class ThumbnailToVisionMetadataConfig(ThumbnailToEmbeddingConfig, VisionMetadataPluginConfig):
    pass


class ThumbnailToVisionMetadata(ImageToVisionMetadata, ThumbnailToEmbedding, BasePlugin):
    """
    For any asset stored on the storage backend this plugin relies on the thumbnail of this asset to extract VLM-generated metadata.
    """

    def __init__(self, config: Optional[ThumbnailToVisionMetadataConfig] = None):
        if config is None:
            config = ThumbnailToVisionMetadataConfig()

        BasePlugin.__init__(
            self,
            plugin_name="thumbnail_to_vision_metadata",
            data_types=set(["any"]),
            render=False,
            namespace=".deepsearch.thumbnail_to_vision_metadata",
            system_namespace=".deepsearch.thumbnail_to_vision_metadata_plugin",
            config=config,
        )
        self.asset_load_timeout = 600
        self.field_name = "images_meta"
        self._batch_data_field = self.field_name
        self.use_elastic_search = True
        self.thumbnail_resolutions = [256]
        self.thumbnail_final_size = 256
        self._metadata_generation: Optional[MetadataGeneration] = None

    def asset_state_hash(self, hash_value: str) -> str:
        return BasePlugin.asset_state_hash(self, hash_value)

    @property
    def config(self) -> ThumbnailToVisionMetadataConfig:
        return self._config

    def load_data(
        self,
        omni_path: str,
        data: Optional[dict] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        return ThumbnailToEmbedding.load_data(
            self,
            omni_path=omni_path,
            data=data,
            status=status,
            error_message=error_message,
        )

    async def get_omni_file(self, omni_item, storage_client: StorageClient, timeout: float = 60) -> DSPluginStatus:
        return await ThumbnailToEmbedding.get_omni_file(
            self, omni_item=omni_item, storage_client=storage_client, timeout=timeout
        )

    async def preprocess(
        self,
        data: list,
        batch_data_dict: Optional[dict] = None,
        storage_client: Optional[StorageClient] = None,
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        return await ThumbnailToEmbedding.preprocess(
            self,
            data=data,
            batch_data_dict=batch_data_dict,
            storage_client=storage_client,
        )

    def verify_data(
        self, batch_data: list, indices: list, error_indices: Dict[str, Any]
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        return ThumbnailToEmbedding.verify_data(
            self, batch_data=batch_data, indices=indices, error_indices=error_indices
        )
