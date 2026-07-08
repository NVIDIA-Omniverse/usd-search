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
from typing import Dict, List, Optional

from cache.src import GenericPluginStatus, PluginItemStatus
from deepsearch_utils.ds_plugin_utils import get_system_values
from deepsearch_utils.misc_utils import get_pillow_supported_formats
from llm_client import MetadataGeneration
from llm_client.exceptions import LLMException, ParsingException

# third-party modules
from opentelemetry import trace
from pydantic import BaseModel

# local/proprietary modules
from storage.src.client import NGSearchStorageHelper, Result, StorageClientInput

from search_utils.misc_utils import image_to_base64
from search_utils.opensearch_utils import OpenSearchIndexSettings

from .base_plugin import BasePlugin, PLuginBatchItem
from .config import ImageToEmbeddingConfig, VisionMetadataPluginConfig
from .exceptions import MetadataException
from .image_to_embedding import ImageToEmbedding
from .models import PluginProcessingResult

SUPPORTED_VISION_GENERATED_METADATA_FIELD_TYPES = set([bool, str, list])
tracer = trace.get_tracer(__name__)


class ImageToVisionMetadataConfig(ImageToEmbeddingConfig, VisionMetadataPluginConfig):
    pass


class ImageToVisionMetadata(ImageToEmbedding, BasePlugin):
    """
    Extracts VLM-generated metadata from the images that are found on the storage backend.
    """

    def __init__(self, config: Optional[ImageToVisionMetadataConfig] = None) -> None:
        if config is None:
            config = ImageToVisionMetadataConfig()

        BasePlugin.__init__(
            self,
            plugin_name="image_to_vision_metadata",
            data_types=set(get_pillow_supported_formats() + ["exr"]),
            render=False,
            namespace=".deepsearch.image_to_vision_metadata",
            system_namespace=".deepsearch.image_to_vision_metadata_plugin",
            config=config,
        )
        self.thumbnail_resolutions = [256]
        self.max_image_load_time = 300
        self.thumbnail_final_size = 256
        self._batch_data_field = "images"
        self._metadata_generation: Optional[MetadataGeneration] = None

    def asset_state_hash(self, hash_value: str) -> str:
        return BasePlugin.asset_state_hash(self, hash_value)

    @property
    def metadata_generation(self) -> Optional[MetadataGeneration]:
        if self._metadata_generation is None:
            try:
                self._metadata_generation = MetadataGeneration()
            except Exception as e:
                self.logger.error(f"Error initializing metadata generation: {e}")
                return None
        return self._metadata_generation

    @property
    def search_backend_field_prefix(self) -> str:
        return (
            f"plugin_{self.plugin_name}_metadata_{OpenSearchIndexSettings().vision_generated_dynamic_templates_suffix}"
        )

    @property
    def config(self) -> VisionMetadataPluginConfig:
        return self._config

    async def add_metadata(self, path: str, content: dict, storage_client: NGSearchStorageHelper) -> Result:
        return await storage_client.update_meta(input=StorageClientInput(key=path, meta=content))

    async def delete_metadata(self, path: str, storage_client: NGSearchStorageHelper):
        self.logger.debug("Nothing needs to be done here, as new metadata will just overwrite the old one")

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:

        processed_results: Dict[int, PluginProcessingResult] = {}
        if len(indices) > 0:
            omni_paths = [b["omni_path"] for b in batch_data]
            previews = [list(b[self.batch_data_field]) for b in batch_data]

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

    async def _invoke_vlm_fn(self, base64_images: list[str]) -> BaseModel:
        try:
            res = await asyncio.wait_for(
                self.metadata_generation.agenerate(base64_images=base64_images),
                timeout=self.config.vlm_agenerate_timeout,
            )
        except asyncio.TimeoutError:
            self.logger.error("Timeout occurred while generating metadata")
            return MetadataException(error="Timeout occurred while generating metadata")
        except ParsingException as e:
            self.logger.error(f"A VLM output parsing error occurred while generating metadata: {e}")
            return MetadataException(error=f"A VLM output parsing error occurred while generating metadata {e}")
        except LLMException as e:
            self.logger.error(f"A VLM invocation error occurred while generating metadata: {e}")
            return MetadataException(error=f"A VLM invocation error occurred while generating metadata {e}")
        return res

    async def get_os_content(self, base64_images_list) -> dict:
        vision_generated_metadata: MetadataException | BaseModel
        vision_generated_metadata_list: list[MetadataException | BaseModel] = await asyncio.gather(
            *[self._invoke_vlm_fn(base64_images) for base64_images in base64_images_list]
        )
        os_content = {"vision_generated_metadata": []}
        for vision_generated_metadata in vision_generated_metadata_list:
            if isinstance(vision_generated_metadata, MetadataException):
                os_content["vision_generated_metadata"].append({"error": vision_generated_metadata.error})
                continue
            res: list[dict] = self.parse_vision_generated_metadata(vision_generated_metadata)
            os_content["vision_generated_metadata"].append(res)
        return os_content

    def parse_vision_generated_metadata(self, vision_generated_metadata: BaseModel) -> List[Dict[str, str | bool]]:
        """
        Parses the vision generated metadata and returns a list of dictionaries with the field name, value, and type.
        """
        vision_generated_metadata: dict = vision_generated_metadata.model_dump()
        res: List[Dict[str, str | bool]] = []
        for field_name, field_value in vision_generated_metadata.items():
            field_value_type = type(field_value)
            if field_value_type not in SUPPORTED_VISION_GENERATED_METADATA_FIELD_TYPES:
                self.logger.error(f"Unsupported metadata field type: {field_value_type} for field: {field_name}")
                continue

            if field_value_type == bool:
                vision_generated_field = {
                    "name": field_name,
                    "value_bool": field_value,
                }
                res.append(vision_generated_field)
                continue

            if field_value_type == str:
                field_value = [field_value]

            vision_generated_field = {
                "name": field_name,
                "name_sayt": field_name,
                "value_text": field_value,
                "value_sayt": field_value,
            }
            res.append(vision_generated_field)
        return res

    def prepare_results(
        self,
        input_dict: dict[str, list[dict]],
        sample_ind: list[int],
        omni_paths: list[str],
    ) -> dict[int, PluginProcessingResult]:
        if "vision_generated_metadata" not in input_dict.keys():
            raise ValueError("Invalid classifier output: 'vision_generated_metadata' not found in keys()")

        with tracer.start_as_current_span("image_to_vision_metadata.prepare_results") as span:
            span.set_attribute("input_dict_length", len(input_dict))
            span.set_attribute("sample_ind_length", len(sample_ind))
            span.set_attribute("omni_paths_length", len(omni_paths))
            update_list = []
            for i in range(len(omni_paths)):
                content: dict[str, Dict[str, str]] = {}
                metadata = input_dict["vision_generated_metadata"][i]
                if "error" in metadata:
                    content["error"] = metadata["error"]
                else:
                    content[self.search_backend_field_prefix] = metadata
                update_list.append(content)

            plugin_processing_results: Dict[int, PluginProcessingResult] = {}
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
