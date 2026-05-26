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
from functools import partial
from typing import Any, Dict, Optional, Tuple

# third-party modules
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
from deepsearch_utils.farm._client import FarmClient
from deepsearch_utils.rendering_utils import (
    RenderingStatus,
    clean_up,
    get_omni_file_renderings,
    render_with_fields_async,
)
from opentelemetry import trace
from PIL import Image

# local/proprietary modules
from storage.src.client import NGSearchStorageHelper

from search_utils.log_utils import print_wrapper
from search_utils.misc_utils import image_to_base64

from .base_plugin import BasePlugin, BasePluginConfig, PLuginBatchItem
from .models import GenericPluginErrorItem, PluginProcessingResult

tracer = trace.get_tracer(__name__)


class RenderingToEmbedding(BasePlugin):
    """
    Renders the asset and extracts CLIP embeddings from the generated preview images.
    """

    def __init__(self, config: Optional[BasePluginConfig] = None):
        super().__init__(
            plugin_name="rendering_to_embedding",
            data_types=set(["usd", "usda", "usdc", "usdz"]),
            render=True,
            namespace=".deeptag.embedding",
            system_namespace=".deeptag.rendering_to_embedding_plugin",
            config=config,
        )
        self.use_elastic_search = True
        self.additional_fields = []
        self.field_name = "images_meta"
        self._embedding_client = get_siglip2_client()

    @property
    def embedding_client(self):
        return self._embedding_client

    def asset_state_hash(self, hash_value: str) -> str:
        return hash_value + "_" + self.embedding_client.clip_service.value

    def load_data(
        self,
        omni_path: Optional[str] = None,
        data: Optional[dict] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
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

    async def get_omni_file(self, *_, **__) -> DSPluginStatus:
        return GetFileResponse(data={}, status=DSPluginStatus.valid)

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        processed_results: Dict[int, PluginProcessingResult] = {}
        if len(indices) > 0:
            # load model from omniverse
            loop = asyncio.get_event_loop()

            model_hash = self.embedding_client.clip_service.value

            # get usd paths from batch_data
            omni_paths = [b["omni_path"] for b in batch_data]
            omni_tags = [[t + [f"model_hash:{model_hash}"] for t in b["tags"]] for b in batch_data]

            # get images and view metadata
            with (
                ThreadPoolExecutor(1) as pool,
                print_wrapper("data preparation", logger=self.logger.debug, print_after=False),
            ):

                def fn():
                    return [
                        [Image.fromarray(im).convert("RGB") for im in b[self.field_name]["images"]] for b in batch_data
                    ]

                previews = await loop.run_in_executor(pool, fn)

            # prepare some additional content that will be pushed to ES
            additional_content = {
                key: [b[self.field_name][key] for b in batch_data]
                for key in self.additional_fields + ["camera_metadata"]
            }

            output_dict = {
                "embed": await run_embedding_model_batch(
                    embedding_client=self.embedding_client,
                    image_lists=previews,
                )
            }
            sample_ind = [sample_ids[i] for i in indices]
            assert len(sample_ind) == len(output_dict["embed"]), "Lengths do not match"

            processed_results = self.prepare_results(
                output_dict,
                sample_ind,
                omni_paths,
                previews,
                omni_tags,
                **additional_content,
            )

        return processed_results

    def prepare_results(
        self,
        input_dict: dict,
        sample_ind: list,
        omni_paths: list,
        images: list,
        omni_tags: Optional[list] = None,
        camera_metadata: list = None,
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        assert "embed" in input_dict.keys(), "Invalid classifier output: 'embed' not found in keys()"

        update_list = []
        labels_dict = SearchBackendLabels(plugin_name=self.plugin_name)
        with tracer.start_as_current_span("rendering_to_embedding.prepare_results") as span:
            span.set_attribute("input_dict_length", len(input_dict))
            span.set_attribute("sample_ind_length", len(sample_ind))
            span.set_attribute("omni_paths_length", len(omni_paths))
            span.set_attribute("images_length", len(images))
            span.set_attribute("omni_tags_length", len(omni_tags))
            span.set_attribute("camera_metadata_length", len(camera_metadata))
            span.set_attribute("additional_content_length", len(kwargs))
            for it, p in enumerate(omni_paths):
                embeds = input_dict["embed"][it]
                ims = images[it]
                if omni_tags is not None:
                    tags = omni_tags[it]
                additional_content = {
                    key: kwargs.get(key)[it] for key in self.additional_fields if key in kwargs.keys()
                }
                embeds = embeds[: len(ims)]
                tags = tags[: len(ims)]

                content = {
                    "embedding": [emb for emb in embeds],
                    "image": [image_to_base64(im) for im in ims],
                    "label": [
                        orjson.dumps(
                            {
                                "thumbnail_id": f"{emb_id}",
                                **self.get_camera_name(camera_metadata[it][emb_id]),
                                **labels_dict,
                            }
                        ).decode()
                        for emb_id in range(len(embeds))
                    ],
                    **additional_content,
                }
                if omni_tags is not None:
                    content["keyword"] = tags
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
        data: list,
        formats: list,
        client: FarmClient,
        batch_data_dict: dict = None,
        storage_client=None,
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        if batch_data_dict is None:
            batch_data_dict = {}

        with tracer.start_as_current_span("rendering_to_embedding.preprocess") as span:
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
                rendering_fn=partial(render_with_fields_async, fields=["images", "camera_metadata"]),
                decompression_fn=None,
                field=self.field_name,
            )
            error_indices: Dict[int, GenericPluginErrorItem] = {
                key: GenericPluginErrorItem(status=value["status"], error_message=value.get("error_message"))
                for key, value in error_indices_dict.items()
            }

            with print_wrapper("reading camera metadata", print_after=False, logger=self.logger.debug):
                # usd naming mapping between tags and camera names to associate tags to views
                for b in batch_data:
                    b["tags"] = [view.get("searchTags", []) for view in b[self.field_name]["camera_metadata"]]

        return self.verify_data(batch_data, indices, error_indices)

    def get_camera_name(self, camera_meta: dict) -> dict:
        if camera_meta.get("deeptag_view_type") == "stage":
            return {"camera_name": camera_meta["prim_path"]}
        else:
            return {}

    def clean_up(self) -> bool:
        return clean_up()

    def verify_data(
        self,
        batch_data: list,
        indices: list,
        error_indices: Dict[int, GenericPluginErrorItem],
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:

        indexes_to_del = set(
            [data_ind for data_ind, d in enumerate(batch_data) if len(d[self.field_name]["images"]) == 0]
        )
        if len(indexes_to_del) > 0:
            failed_paths = [batch_data[i].get("omni_path", "unknown") for i in indexes_to_del]
            self.logger.info(
                "%d asset(s) did not pass verification (empty rendered images): %s",
                len(indexes_to_del),
                failed_paths,
            )

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
