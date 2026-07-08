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
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional, Tuple

from cache.src import GenericPluginStatus, PluginItemStatus
from deepsearch_utils.ds_plugin_utils import (
    DSPluginStatus,
    GetFileResponse,
    get_system_values,
)
from deepsearch_utils.farm.client import FarmClient
from deepsearch_utils.rendering_utils import (
    RenderingStatus,
    clean_up,
    get_omni_file_renderings,
    render_usd_file_async,
)
from llm_client import MetadataGeneration

# third-party modules
from opentelemetry import trace
from PIL import Image

# local/proprietary modules
from storage.src.client import NGSearchStorageHelper, Result, StorageClientInput

from search_utils.misc_utils import image_to_base64

from .base_plugin import BasePlugin, PLuginBatchItem
from .config import VisionMetadataPluginConfig
from .image_to_vision_metadata import ImageToVisionMetadata
from .models import GenericPluginErrorItem, PluginProcessingResult

tracer = trace.get_tracer(__name__)


class RenderingToVisionMetadata(ImageToVisionMetadata, BasePlugin):
    """
    Renders the asset and extracts VLM-generated metadata using the generated preview images.
    """

    def __init__(self, config: Optional[VisionMetadataPluginConfig] = None):
        if config is None:
            config = VisionMetadataPluginConfig()

        BasePlugin.__init__(
            self,
            plugin_name="rendering_to_vision_metadata",
            data_types=set(["usd", "usda", "usdc", "usdz"]),
            render=True,
            namespace=".deepsearch.rendering_to_vision_metadata",
            system_namespace=".deepsearch.rendering_to_vision_metadata_plugin",
            config=config,
        )
        self.use_elastic_search = True
        self.asset_load_timeout = 600
        self.field_name = "images_meta"
        self._metadata_generation: Optional[MetadataGeneration] = None

    def asset_state_hash(self, hash_value: str) -> str:
        return BasePlugin.asset_state_hash(self, hash_value)

    @property
    def config(self) -> VisionMetadataPluginConfig:
        return self._config

    def load_data(
        self,
        omni_path: str,
        data: Optional[dict] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        if data is None:
            data = {}
            if status is not None:
                return {
                    "omni_path": omni_path,
                    "status": status,
                    "error_message": error_message,
                }
        assert omni_path is not None, "file path in omniverse is not provided"
        return {"omni_path": omni_path, **data}

    async def add_metadata(self, path: str, content: dict, storage_client: NGSearchStorageHelper, **kwargs) -> Result:
        return await storage_client.update_meta(input=StorageClientInput(key=path, meta=content))

    async def delete_metadata(self, path: str, storage_client: NGSearchStorageHelper):
        self.logger.debug("Nothing needs to be done here, as new metadata will just overwrite the old one")

    async def get_omni_file(self, *_, **__) -> DSPluginStatus:
        return GetFileResponse(data={}, status=DSPluginStatus.valid)

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> dict:

        loop = asyncio.get_event_loop()
        processed_results: Dict[int, PluginProcessingResult] = {}

        if len(indices) > 0:
            # load model from omniverse

            # get usd paths from batch_data
            omni_paths = [b["omni_path"] for b in batch_data]

            with ThreadPoolExecutor(1) as pool:

                def fn():
                    return [[Image.fromarray(im).convert("RGB") for im in b[self.field_name]] for b in batch_data]

                previews = await loop.run_in_executor(pool, fn)

            base64_images_list = []
            for sample_preview in previews:
                base64_images_list.append([image_to_base64(im) for im in sample_preview])

            output_dict = await self.get_os_content(base64_images_list)

            sample_ind = [sample_ids[i] for i in indices]
            assert len(sample_ind) == len(
                output_dict["vision_generated_metadata"]
            ), f"Lengths do not match: {len(sample_ind)} vs {len(output_dict['vision_generated_metadata'])}"

            processed_results = self.prepare_results(
                input_dict=output_dict,
                sample_ind=sample_ind,
                omni_paths=omni_paths,
            )
        return processed_results

    def prepare_results(
        self,
        input_dict: dict[str, list[dict]],
        sample_ind: list[int],
        omni_paths: list[str],
    ) -> dict[str, PluginProcessingResult]:
        if "vision_generated_metadata" not in input_dict.keys():
            raise ValueError("Invalid classifier output: 'vision_generated_metadata' not found in keys()")

        update_list = []
        with tracer.start_as_current_span("rendering_to_vision_metadata.prepare_results") as span:
            span.set_attribute("input_dict_length", len(input_dict))
            span.set_attribute("sample_ind_length", len(sample_ind))
            span.set_attribute("omni_paths_length", len(omni_paths))
            for i in range(len(omni_paths)):
                content: dict[str, Dict[str, str]] = {}
                metadata = input_dict["vision_generated_metadata"][i]
                if "error" in metadata:
                    content["error"] = metadata["error"]
                else:
                    content[self.search_backend_field_prefix] = metadata
                update_list.append(content)

            plugin_processing_results = {}
            for smpl_ind, es_content in zip(sample_ind, update_list):
                if "error" in es_content:
                    self.logger.error(f"Error occurred while processing sample {smpl_ind}: {es_content['error']}")
                    asset_status = PluginItemStatus(
                        status=GenericPluginStatus.failed.value,
                        processing_timestamp=time.time(),
                        exception=es_content["error"],
                    )
                else:
                    asset_status = PluginItemStatus(
                        status=GenericPluginStatus.ok.value,
                        processing_timestamp=time.time(),
                    )
                plugin_processing_results[smpl_ind] = PluginProcessingResult(
                    asset_status=asset_status,
                    search_backend_content={self.plugin_name: es_content},
                    **get_system_values(system_namespace=self.system_namespace),
                )
        return plugin_processing_results

    async def preprocess(
        self,
        data: list,
        formats: list,
        client: FarmClient,
        batch_data_dict: dict = None,
        storage_client=None,
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        if batch_data_dict is None:
            batch_data_dict = {}
        with tracer.start_as_current_span("rendering_to_vision_metadata.preprocess") as span:
            span.set_attribute("data_length", len(data))
            span.set_attribute("formats_length", len(formats))
            span.set_attribute("batch_data_dict_length", len(batch_data_dict))
            batch_data, indices, error_indices_dict = await get_omni_file_renderings(
                data=data,
                formats=formats,
                data_types=self.data_types,
                client=client,
                batch_data_dict=batch_data_dict,
                plugin_name=self.plugin_name,
                rendering_fn=render_usd_file_async,
                decompression_fn=None,
                field=self.field_name,
            )
            error_indices: Dict[int, GenericPluginErrorItem] = {
                key: GenericPluginErrorItem(status=value["status"], error_message=value.get("error_message"))
                for key, value in error_indices_dict.items()
            }
        return self.verify_data(batch_data, indices, error_indices)

    def clean_up(self) -> bool:
        return clean_up()

    def verify_data(
        self,
        batch_data: list,
        indices: list,
        error_indices: Dict[int, GenericPluginErrorItem],
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:

        indexes_to_del = set([data_ind for data_ind, d in enumerate(batch_data) if len(d[self.field_name]) == 0])

        if len(indexes_to_del) > 0:
            self.logger.info("%d did not pass verification", len(indexes_to_del))

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
