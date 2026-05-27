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

from enum import Enum
from itertools import islice
from time import time
from typing import Any, Dict, Iterable, Iterator, List, Optional, TypedDict, TypeVar

import numpy as np
import orjson
from numpy.typing import NDArray
from opentelemetry import trace
from PIL import Image
from pydantic import Field
from pydantic_settings import BaseSettings
from storage.src.client import (
    NGSearchStorageHelper,
    Result,
    StorageClientInput,
    assert_status_ok,
)
from vision_endpoint import BaseCLIP, SigLIP2

from search_utils.datetime_utils import date_from_timestamp
from search_utils.log_utils import prepare_message, set_simple_logger
from search_utils.misc_utils import combine_outputs
from search_utils.storage_client import RemoteFileUri

tracer = trace.get_tracer(__name__)


class SearchBackendLabels(TypedDict):
    plugin_name: str


class BasePluginConfig(BaseSettings):
    log_level: str = Field(default="INFO", alias="plugin_loglevel")


logger = set_simple_logger(logger_name="generic_plugin_logger", loglevel=BasePluginConfig().log_level)


_T = TypeVar("_T")


def group_elements(lst: Iterable[_T], chunk_size: int) -> Iterator[List[_T]]:
    lst = iter(lst)
    return iter(lambda: list(islice(lst, chunk_size)), [])


_siglip2_client: Optional[SigLIP2] = None


def get_siglip2_client() -> SigLIP2:
    """Return a shared SigLIP2 client instance (singleton).

    All embedding plugins share one client to avoid redundant gRPC connections.
    """
    global _siglip2_client
    if _siglip2_client is None:
        _siglip2_client = SigLIP2()
    return _siglip2_client


class DSPluginStatus(str, Enum):
    valid = "valid"
    load_error = "load_error"
    thumbs_missing = "thumbs_missing"


class GetFileResponse(TypedDict):
    data: Optional[Any]
    status: DSPluginStatus


async def remove_plugin_content(
    omni_path: RemoteFileUri,
    storage_client: NGSearchStorageHelper,
    labels: SearchBackendLabels,
) -> Dict[str, List[str]]:
    """Read ES content for an asset and remove information that needs to be overwritten by the update.

    Args:
        omni_path (str): path to the asset in omniverse (ES key)
        es_cache: ES cache class

    Returns:
        dict: content of the asset with appropriate fields removed.
    """
    try:
        response: Result = await storage_client.get_item(StorageClientInput(key=omni_path))
        assert_status_ok(response)
        existing_content: dict = response.data
    except KeyError:
        return {}
    # remove all items that have the same labels
    # TODO: currently exact match triggers removal as only the plugin name in included
    #   this might be updated label with plugin version
    try:
        return {
            k: [
                it
                for it, lbl in zip(v, existing_content["label"])
                if not (lbl is None or (labels.items() <= orjson.loads(lbl).items()))
            ]
            for k, v in existing_content.items()
        }
    except KeyError as exc_info:
        logger.warning(
            "plugin content removal exception: Error: '%s'; Content: %s",
            str(exc_info),
            str(existing_content),
        )
        return existing_content


async def copy_search_storage_metadata(
    source_path: RemoteFileUri,
    target_path: RemoteFileUri,
    storage_client: NGSearchStorageHelper,
    **kwargs,
):
    """Copy plugin content from one omniverse path to another."""

    # update embedding
    response = await storage_client.get_item(StorageClientInput(key=source_path))
    assert_status_ok(response)
    assert_status_ok(await storage_client.update_item(StorageClientInput(key=target_path, values=response["data"])))


async def delete_search_storage_metadata(
    path: str,
    storage_client: NGSearchStorageHelper,
    labels: SearchBackendLabels,
):
    """Delete metadata from index that corresponds to this plugin."""

    # read embedding
    content = await remove_plugin_content(omni_path=path, storage_client=storage_client, labels=labels)

    if content != {} and len(content[list(content.keys())[0]]) != 0:
        # update embedding
        assert_status_ok(await storage_client.update_item(StorageClientInput(key=path, values=content)))
    else:
        # clean embedding
        assert_status_ok(
            await storage_client.update_item(StorageClientInput(key=path, values={"embedding": [], "image": []}))
        )


async def add_search_storage_metadata(
    path: str,
    labels: SearchBackendLabels,
    content: dict,
    storage_client: NGSearchStorageHelper,
):
    """Update appropriate metadata in the ES index.

    Args:
        path (str): path to the asset
        content (dict): content that is prepared to be stored in ES index.
    """
    existing_content = await remove_plugin_content(omni_path=path, storage_client=storage_client, labels=labels)

    if existing_content != {} and len(existing_content[list(existing_content.keys())[0]]) != 0:
        # log some info
        logger.debug(
            "%s",
            prepare_message(msg="before:", item_list=existing_content.get("label", [])),
        )
        # combine content values
        content = combine_outputs(existing_content, content)
        # log some info
        logger.debug("%s", prepare_message(msg="after:", item_list=content["label"]))
    # update embedding
    assert_status_ok(await storage_client.update_item(StorageClientInput(key=path, values=content)))


def _to_pil_images(images: List) -> List[Image.Image]:
    return [Image.fromarray(img) if isinstance(img, np.ndarray) else img for img in images]


async def run_embedding_model(
    embedding_client: BaseCLIP,
    input_embedding_list: List[NDArray[np.float32]],
) -> NDArray[np.float32]:
    """Embed a list of images.

    Args:
        embedding_client (BaseCLIP): Embedding client
        input_embedding_list (List[NDArray[np.float32]]): numpy array of inputs

    Returns:
        np.ndarray: embeddings for each of the input samples
    """
    with tracer.start_as_current_span("run_embedding_model") as span:
        span.set_attribute("clip_service", embedding_client.clip_service.value)
        span.set_attribute("input_embedding_list_length", len(input_embedding_list))
        pil_images = _to_pil_images(input_embedding_list)
        return await embedding_client.aembed_images(pil_images)


async def run_embedding_model_batch(
    embedding_client: BaseCLIP,
    image_lists: List[List],
) -> List[NDArray[np.float32]]:
    """Embed multiple assets' images in a single batched call.

    Flattens all images into one request to maximise GPU batch utilisation and
    avoid per-asset request overhead, then splits results back per asset.

    Args:
        embedding_client (BaseCLIP): Embedding client
        image_lists: list of image lists, one per asset

    Returns:
        list of embedding arrays, one per asset
    """
    all_images: List[Image.Image] = []
    counts: List[int] = []
    for images in image_lists:
        pil = _to_pil_images(images)
        all_images.extend(pil)
        counts.append(len(pil))

    if not all_images:
        return [np.array([]) for _ in image_lists]

    all_embeds = await embedding_client.aembed_images(all_images)

    results: List[NDArray[np.float32]] = []
    offset = 0
    for count in counts:
        results.append(all_embeds[offset : offset + count])
        offset += count

    return results


def get_system_values(system_namespace: str) -> Dict[str, Dict[str, str]]:
    """Prepare a dictionary of system values

    Args:
        system_namespace (str): system namespace of the plugin

    Returns:
        Dict[str, Dict[str, str]]: dictionary of system values for each sample
    """
    return {f"{system_namespace}": {"inference_date": date_from_timestamp(time())}}
