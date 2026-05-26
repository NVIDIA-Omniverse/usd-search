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
import os
import re
import tempfile
import time
from enum import Enum
from functools import partial
from typing import Dict, Optional, Tuple

# third-party modules
import numpy as np

# local/proprietary modules
from cache.src import GenericPluginStatus, PluginItemStatus
from deepsearch_utils.misc_utils import remove_omni_prefix, strip_alpha_channel
from deepsearch_utils.rendering_utils import (
    combiner_async,
    get_omni_file_renderings,
    render_usd_file_async,
    save_camera_metadata_async,
)
from monitor.src.config import AssetDBConfig as service_Config
from opentelemetry import trace
from PIL import Image

from search_utils.log_utils import prepare_message, print_wrapper
from search_utils.storage_client import PathType, RemoteFileUri, StorageClient
from search_utils.storage_client.exceptions import AccessDeniedError
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.storage_api.client import StorageAPIStorageClient

from .base_plugin import BasePlugin, BasePluginConfig, PLuginBatchItem
from .models import GenericPluginErrorItem, PluginProcessingResult
from .rendering_to_embedding import RenderingToEmbedding

tracer = trace.get_tracer(__name__)


class GeneratedStatus(str, Enum):
    success = GenericPluginStatus.ok.value
    empty_scene = "empty_scene"
    writing_disabled = "writing_disabled"
    access_denied = "access_denied"


class ThumbnailGenerationPluginConfig(BasePluginConfig):
    use_embedding_client: bool = False
    remove_existing_thumbnails: bool = False
    skip_omni_writes: bool = False


class ThumbnailGeneration(RenderingToEmbedding, BasePlugin):
    """
    Renders the asset uploads one of the rendered images to the storage backend to serve as a thumbnail for this asset.
    """

    def __init__(self, config: Optional[ThumbnailGenerationPluginConfig] = None):
        if config is None:
            config = ThumbnailGenerationPluginConfig()

        BasePlugin.__init__(
            self,
            plugin_name="thumbnail_generation",
            data_types=set(["usd", "usda", "usdc", "usdz"]),
            render=True,
            namespace=".deeptag.thumbnail_generation",
            system_namespace=".deeptag.thumbnail_generation_plugin",
            config=config,
        )
        self.field_name = "thumbnails_meta"
        self.asset_load_timeout = 600
        self.thumbnail_suffix = ".auto"
        self.overwrite_content = False
        self.clean_nosuffix_thumbs = False
        self.thumbnail_resolutions = [256]
        self.thumbnail_number = 0
        self.error_label = "failure"
        self._writes_disabled_warning_emitted = False

    def asset_state_hash(self, hash_value: str) -> str:
        return BasePlugin.asset_state_hash(self, hash_value)

    @property
    def config(self) -> ThumbnailGenerationPluginConfig:
        return self._config

    def set_thumbnail_suffix(self, suffix: str):
        self.thumbnail_suffix = suffix

    def res_map(self, res: int):
        if res == 108:
            return (138, 108)
        elif res == 256:
            return (256, 256)
        else:
            self.logger.error("Unknown resolution: %s", str(res))
            raise NotImplementedError(f"Unknown resolution: {res}")

    def get_thumbs_location(self, p: str, res: tuple, suffix: str = None) -> str:
        if suffix is None:
            suffix = self.thumbnail_suffix
        return f"{p[:p.rfind('/')]}/.thumbs/{res[0]}x{res[1]}/{os.path.basename(p)}{suffix}.png"

    async def get_existing_thumbnail_names(
        self, usd_paths: list[RemoteFileUri], client: StorageClient, suffix: str = None
    ) -> list[RemoteFileUri]:
        if suffix is None:
            suffix = self.thumbnail_suffix
        files = [
            f
            async for f in client.list_items(
                uri_list=list(
                    set(
                        [
                            os.path.dirname(self.get_thumbs_location(path, self.res_map(res)))
                            for path in usd_paths
                            for res in self.thumbnail_resolutions
                        ]
                    )
                ),
                show_hidden=True,
                raise_on_error=False,
                ignore_patterns=[],
            )
        ]
        if suffix.startswith("."):
            suffix = f"\\{suffix}"

        files_names = [f"{os.path.basename(path)}{suffix}" for path in usd_paths]
        pattern = f".*(?:{'|'.join(files_names)})\\.(?:png|jpg)"

        res_list: list[RemoteFileUri] = []
        path: PathType
        for path in files:
            try:
                if re.match(pattern, path.uri):
                    res_list.append(path.uri)
            except re.error as exc_info:
                self.logger.exception("%s in %s: %s", pattern, path.uri, exc_info)

        return res_list

    def change_thumbnail_path(self, source_usd_paths: list[str], target_usd_path: str) -> list[str]:
        folder_name = os.path.dirname(target_usd_path)
        file_name = os.path.basename(target_usd_path)

        target_thumbnail_list = []
        for sp in source_usd_paths:
            st_thumb = sp.find(".thumbs")
            fn_thumb = st_thumb + 8 + sp[st_thumb + 8 :].find("/")
            suff = sp[sp.find(self.thumbnail_suffix) :]
            target_thumbnail_list.append(f"{folder_name}/{sp[st_thumb:fn_thumb]}/{file_name}{suff}")
        return target_thumbnail_list

    def overwrite_if_fn(self, file: PathType) -> bool:
        if file is None:
            return True
        else:
            prepare_message(
                item_list=[f"{file.uri}", f"{file.modified_by}"],
                logger=self.logger.debug,
            )
            return file.modified_by == service_Config.omni_master_user

    def load_data(
        self,
        omni_path: Optional[str] = None,
        data: Optional[dict] = None,
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        assert omni_path is not None, "file path in omniverse is not provided"
        return {"omni_path": omni_path}

    async def copy_metadata(
        self,
        client: StorageClient,
        source_path: str,
        target_path: str,
        verify_ownership: bool = True,
        on_empty_list: str = "raise",
    ):
        source_omni_files = await self.get_existing_thumbnail_names([source_path], client=client)
        target_omni_files = self.change_thumbnail_path(source_omni_files, target_path)

        if len(source_omni_files) == 0:
            if on_empty_list == "warn":
                self.logger.warning("Empty thumbnail list for '%s'", source_path)
            elif on_empty_list == "raise":
                raise KeyError(f"Empty thumbnail list for '{source_path}': cannot copy")
            else:
                raise KeyError(f"Empty thumbnail list for '{source_path}': unknown action")

        assert len(source_omni_files) == len(target_omni_files), "Lengths of thumbnail lists do not match"

        for sf, tf in zip(source_omni_files, target_omni_files):
            overwrite = True
            if verify_ownership:
                file = await client.get_item(uri=tf)
                overwrite = self.overwrite_if_fn(file)
            if overwrite:
                _, result = await client.copy(sf, tf)
                client.assert_on_bad_status(result)

    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list,
        sample_ids: list,
        storage_client: StorageClient,
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        generated_status: list[GeneratedStatus] = []
        if len(batch_data) > 0:
            with (
                tempfile.TemporaryDirectory() as tmp_folder,
                tracer.start_as_current_span("thumbnail_generation.process_valid_items") as span,
            ):
                span.set_attribute("batch_data_length", len(batch_data))
                span.set_attribute("indices_length", len(indices))
                span.set_attribute("sample_ids_length", len(sample_ids))
                span.set_attribute("storage_client", storage_client)
                span.set_attribute("kwargs_length", len(kwargs))
                with print_wrapper(
                    f"{self.plugin_name}: generation",
                    print_after=False,
                    logger=self.logger.debug,
                ):
                    for sample in batch_data:
                        local_files: list[str] = []
                        omni_files: list[str] = []
                        asset_paths: list[str] = []

                        local_files, omni_files, generated = self.create_thumbnails(
                            sample[self.field_name]["images"][0],
                            omni_path=sample["omni_path"],
                            tmp_folder=tmp_folder,
                        )
                        asset_paths.extend([sample["omni_path"]] * len(local_files))
                        local_files.extend(local_files)
                        omni_files.extend(omni_files)

                        if self.thumbnail_number < 0:
                            limit = len(sample[self.field_name]["images"])
                        else:
                            limit = min(
                                self.thumbnail_number,
                                len(sample[self.field_name]["images"]),
                            )

                        view_counter = 0
                        for it in range(limit):
                            post_suffix, view_counter = self.camera_thumbnail_name(
                                sample[self.field_name]["camera_metadata"][it],
                                view_counter,
                            )
                            local_files, omni_files, generated = self.create_thumbnails(
                                sample[self.field_name]["images"][it],
                                omni_path=sample["omni_path"],
                                post_suffix=post_suffix,
                                tmp_folder=tmp_folder,
                            )
                            local_files.extend(local_files)
                            omni_files.extend(omni_files)

                        # if writing is disabled - proceed to the next item
                        if self.config.skip_omni_writes:
                            generated_status.append(GeneratedStatus.writing_disabled)
                            continue

                        with print_wrapper(
                            f"uploading thumbnails to {storage_client.connection_info}",
                            logger=self.logger.debug,
                        ):
                            try:
                                await storage_client.upload_items(
                                    item_dict={remote: local for remote, local in zip(omni_files, local_files)},
                                    overwrite_content=self.overwrite_content,
                                    overwrite_if_fn=self.overwrite_if_fn,
                                )
                                generated_status.append(GeneratedStatus.success)
                            except AccessDeniedError:
                                generated_status.append(GeneratedStatus.access_denied)
                                # if item cannot be uploaded - proceed to the next one
                                continue

                        if isinstance(storage_client, (S3StorageClient, StorageAPIStorageClient)):
                            self.logger.debug("ACL update functionality is not supported in S3 or Storage API clients")
                        else:
                            with print_wrapper("updating ACLs to omniverse", logger=self.logger.debug):
                                # update permissions for the generated thumbnail files
                                for src, tgt in zip([p for p in asset_paths], [p for p in omni_files]):
                                    backend = storage_client.get_backend_from_uri(tgt)
                                    if not isinstance(
                                        backend,
                                        (S3StorageClient, StorageAPIStorageClient),
                                    ):
                                        await backend.update_acl(path_dict={src: tgt})
                                    else:
                                        self.logger.debug(
                                            "ACL update functionality is not supported in S3 or Storage API clients"
                                        )

                            # thumbnail servers
                            thumbs_folders = list(set([os.path.dirname(os.path.dirname(uri)) for uri in omni_files]))
                            with print_wrapper(
                                "updating ACLs to .thumbs folders",
                                logger=self.logger.debug,
                            ):
                                # update permissions for the generated thumbnail files
                                for src, tgt in zip(
                                    [os.path.dirname(p) + "/" for p in thumbs_folders],
                                    [p + "/" for p in thumbs_folders],
                                ):
                                    backend = storage_client.get_backend_from_uri(tgt)
                                    if not isinstance(
                                        backend,
                                        (S3StorageClient, StorageAPIStorageClient),
                                    ):
                                        await backend.update_acl(path_dict={src: tgt})
                                    else:
                                        self.logger.debug(
                                            "ACL update functionality is not supported in S3 or Storage API clients"
                                        )

                            # 256x256 folders
                            thumbs_folders = list(set([os.path.dirname(uri) for uri in omni_files]))
                            with print_wrapper(
                                "updating ACLs to 256x256 folders",
                                logger=self.logger.debug,
                            ):
                                # update permissions for the generated thumbnail files
                                for src, tgt in zip(
                                    [os.path.dirname(p) + "/" for p in thumbs_folders],
                                    [p + "/" for p in thumbs_folders],
                                ):
                                    backend = storage_client.get_backend_from_uri(tgt)
                                    if not isinstance(
                                        backend,
                                        (S3StorageClient, StorageAPIStorageClient),
                                    ):
                                        await backend.update_acl(path_dict={src: tgt})
                                    else:
                                        self.logger.debug(
                                            "ACL update functionality is not supported in S3 or Storage API clients"
                                        )

        sample_ind = [sample_ids[i] for i in indices]
        assert len(sample_ind) == len(
            generated_status
        ), "Lengths of generated statuses do not match with number of assets"
        return {
            ind: PluginProcessingResult(
                asset_status=PluginItemStatus(status=status, processing_timestamp=time.time()),
            )
            for ind, status in zip(sample_ind, generated_status)
        }

    async def preprocess(
        self,
        data: list,
        formats: list,
        client,
        storage_client: StorageClient,
        batch_data_dict: dict = None,
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        if batch_data_dict is None:
            batch_data_dict = ({},)

        # Skip render + upload entirely when the S3 destination is configured read-only for
        # non-system paths. Thumbnails live under `.thumbs/` (not under system_path_prefix), so
        # `allow_non_system_writes=False` means every upload would fail with AccessDenied. Doing
        # this here keeps the renderer from ever being called on a read-only backend (e.g. the
        # public NVIDIA quickstart bucket).
        if isinstance(storage_client, S3StorageClient) and not storage_client.allow_non_system_writes:
            if not self._writes_disabled_warning_emitted:
                self.logger.warning(
                    "Thumbnail generation disabled: S3 client %s has allow_non_system_writes=False. "
                    "All items will be marked %s without rendering.",
                    storage_client.connection_info,
                    GeneratedStatus.writing_disabled.value,
                )
                self._writes_disabled_warning_emitted = True
            error_indices: Dict[int, GenericPluginErrorItem] = {
                i: GenericPluginErrorItem(status=GeneratedStatus.writing_disabled, error_message=None)
                for i in range(len(data))
            }
            return [], [], error_indices

        files_dict = dict(files=[])
        with print_wrapper("get thumbnail names", logger=self.logger.debug, print_after=False):
            files_dict["files"] = await self.get_existing_thumbnail_names(
                [d["omni_path"] for d in data], client=storage_client
            )

        prepare_message(item_list=files_dict["files"], logger=self.logger.debug)

        self.logger.debug("Number of thumbnails: %d", len(files_dict["files"]))

        omni_files = files_dict["files"]

        for f in omni_files:
            assert f.find(".thumbs") >= 0, f"Trying to delete the wrong file: {f}"

        prepare_message(
            msg="removing thumbnail files",
            item_list=omni_files,
            logger=self.logger.debug,
        )

        if not self.config.skip_omni_writes and self.config.remove_existing_thumbnails:
            with print_wrapper("removing thumbnails", logger=self.logger.debug, print_after=False):
                await storage_client.delete_items(omni_files)

        func_dict = {
            "images": render_usd_file_async,
            "camera_metadata": save_camera_metadata_async,
        }
        self.logger.debug("Extracting: %s", str(func_dict.keys()))

        with (
            print_wrapper("get new thumbnails", logger=self.logger.debug, print_after=False),
            tracer.start_as_current_span("thumbnail_generation.preprocess") as span,
        ):
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
                rendering_fn=partial(combiner_async, func_dict=func_dict),
                decompression_fn=None,
                field=self.field_name,
            )

        error_indices: Dict[int, GenericPluginErrorItem] = {
            key: GenericPluginErrorItem(status=value["status"], error_message=value.get("error_message"))
            for key, value in error_indices_dict.items()
        }

        for idx, i in enumerate(indices):
            batch_data[idx]["omni_path"] = remove_omni_prefix(data[i]["omni_path"])

        return self.verify_data(batch_data, indices, error_indices)

    def get_local_thumbs_location(self, tmp_folder: str) -> str:
        return f"{tmp_folder}/{time.time()}.png"

    def prepare_image(self, image, res: tuple) -> Image.Image:
        if image is None:
            return None
        max_res = max(res)
        im = Image.fromarray(image).resize((max_res, max_res))

        left = (max_res - res[0]) / 2
        top = (max_res - res[1]) / 2
        right = (max_res + res[0]) / 2
        bottom = (max_res + res[1]) / 2

        return im.crop((left, top, right, bottom))

    def create_thumbnails(
        self,
        image,
        omni_path: str,
        tmp_folder: str,
        post_suffix: str = None,
    ):
        if post_suffix is None:
            post_suffix = ""
        local_files: list[str] = []
        omni_files: list[str] = []

        for res in self.thumbnail_resolutions:
            im = self.prepare_image(image, self.res_map(res))
            lfile = self.get_local_thumbs_location(tmp_folder=tmp_folder)
            ofile = self.get_thumbs_location(
                omni_path,
                self.res_map(res),
                suffix=f"{self.thumbnail_suffix}{post_suffix}",
            )

            prepare_message(
                msg="uploading thumbnail:",
                item_list=[f"local file: {lfile}", f"omniverse file: {ofile}"],
                logger=self.logger.debug,
            )
            if im is not None and np.std(strip_alpha_channel(np.array(im))) > 1:
                im.save(lfile)
                local_files.append(lfile)
                omni_files.append(ofile)
                generated = GeneratedStatus.success
            else:
                self.logger.warning("Thumbnail: %s has no content", ofile)
                generated = GeneratedStatus.empty_scene

        return local_files, omni_files, generated

    def camera_thumbnail_name(self, camera_metadata: dict, view_counter: int, strategy: str = "index"):
        if strategy == "index":
            camera_name = f".{view_counter}"
            view_counter += 1
            return camera_name, view_counter
        elif strategy == "camera_name":
            camera_name = camera_metadata["prim_path"].replace("/", "-")
            if camera_metadata["deeptag_view_type"] == "generated":
                camera_name = f"{camera_name}_{view_counter}"
                view_counter += 1
            return f".{camera_name}", view_counter
        else:
            raise NotImplementedError(f"thumbnail naming strategy: '{strategy}' is not implemented")
