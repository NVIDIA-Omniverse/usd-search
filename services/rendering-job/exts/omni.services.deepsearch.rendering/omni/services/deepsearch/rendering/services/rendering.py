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

# standard modules
import hashlib
import json
import os
import traceback
from tempfile import TemporaryDirectory
from typing import Dict, List, Optional

# third party modules
import numpy as np

# local/proprietary modules
import omni.client
import omni.kit
from omni.kit.thumbnails.mdl import MdlThumbnailGenerator, ThumbnailManager
from omni.services.core import routers
from PIL import Image
from typing_extensions import Any

from ..helpers import AZIMUTHS, ELEVATIONS
from ..helpers.data import CameraParameters, CameraPlacingStrategy, CameraPosition
from ..helpers.exceptions import InvalidMTLNames, LoadError
from ..helpers.log_utils import print_wrapper
from ..helpers.misc_utils import get_size, pickle_data
from ..helpers.transport import http_send, redis_send, ws_send
from ..helpers.view_renderer import ViewRenderer
from . import logger
from .data import (
    BatchRequestRenderUSD,
    ContentType,
    GetUSDRenderings,
    MDLConfig,
    RenderSettings,
    RequestRenderUSD,
    ResponsePayload,
    ResponseStatus,
)

router = routers.ServiceAPIRouter()

mdl_config = MDLConfig()


@router.get("/healthy")
async def healthy():
    return {"status": "healthy"}


@router.get("/data")
async def data(req: GetUSDRenderings, cache=router.get_facility("cache")):
    """Get renderings and other data for a USD file from service cache

    Args:
        req (GetUSDRenderings): request
        cache ([type], optional): service cache. Defaults to router.get_facility("cache").
    """
    if req.url_hash not in cache.keys():
        return {"status": "unavailable"}
    else:
        content: ContentType = cache[req.url_hash]
        return {"status": "available", **content.dict()}


@router.post("/render")
async def render(
    req: RequestRenderUSD,
    renderer: ViewRenderer = router.get_facility("view_renderer"),
    cache=router.get_facility("cache"),
):
    """Render a various views of a USD file"""

    return await batch_render(
        BatchRequestRenderUSD(
            url_list=[req.url],
            ws=req.ws,
            http=req.http,
            n_retries=req.n_retries,
            auth=req.auth,
            render_settings=req.render_settings,
        ),
        renderer=renderer,
        cache=cache,
    )


def get_annotations(subidentifier) -> Dict[str, str]:
    annotations = {"sub_identifier": subidentifier.name}
    if subidentifier.annotations is None:
        return annotations
    if "display_name" in subidentifier.annotations:
        annotations["display_name"] = subidentifier.annotations["display_name"]
    if "description" in subidentifier.annotations:
        annotations["description"] = subidentifier.annotations["description"]
    if "key_words" in subidentifier.annotations:
        annotations["key_words"] = subidentifier.annotations["key_words"]
    return annotations


async def mdlrender(
    url: str,
    thumbnail_manager: Optional[ThumbnailManager] = None,
    mtl_names: Optional[List[str]] = None,
    width: int = 448,
    height: int = 448,
    mdl_template_url: Optional[str] = None,
    mdl_stdin: Optional[str] = None,
) -> ResponsePayload:

    if thumbnail_manager is None:
        thumbnail_manager = ThumbnailManager(max_retry_count=5)

    subidentifiers = await omni.kit.material.library.get_subidentifier_from_mdl(url)
    sub_indentifier_annotations: Dict[str, Dict[str, Any]] = {}
    for subidentifier in subidentifiers:
        sub_indentifier_annotations[subidentifier.name] = get_annotations(subidentifier)

    if mtl_names is not None and not all([mtl_name in sub_indentifier_annotations for mtl_name in mtl_names]):
        raise InvalidMTLNames(f"MTL names {mtl_names} are not valid for the MDL file {url}")

    if mtl_names is None:
        subidentifiers = await omni.kit.material.library.get_subidentifier_from_mdl(url)
        mtl_names = [subidentifier.name for subidentifier in subidentifiers]
        if len(mtl_names) == 0:
            mtl_names = [None]

    logger.info(f"Rendering MDL file {url} with MTL names: {mtl_names}")

    final_result = {"images": [], "camera_metadata": []}

    for mtl_name in mtl_names:

        response = ContentType(path="", content="")

        rendering_completed = asyncio.Event()
        rendering_success = asyncio.Event()

        with TemporaryDirectory() as temp_dir:

            thumbnail_url = os.path.join(temp_dir, "mdl_material.png")

            # Define callback function for when thumbnail generation is complete
            def _on_thumbnail_done(result, url: str) -> None:
                response.path = url
                if result:
                    rendering_success.set()
                    logger.info(f"thumbnail successfully created: {url}")
                else:
                    logger.warning(f"Failed to create thumbnail: {url}")

                rendering_completed.set()

            # Generate thumbnails for each material
            mdl_generator = MdlThumbnailGenerator(
                mdl_url=url,
                output_url=thumbnail_url,
                mtl_name=mtl_name,  # No sub material
                width=width,
                height=height,
                template_url=(mdl_template_url if mdl_template_url is not None else mdl_config.mdl_template_url),
                stdin=mdl_stdin if mdl_stdin is not None else mdl_config.mdl_stdin,
                on_thumbnail_done_fn=_on_thumbnail_done,
            )
            thumbnail_manager.put(mdl_generator, timeout=60)

            await rendering_completed.wait()
            if rendering_success.is_set():
                logger.info(f"thumbnail successfully created: {url} with mtl name {mtl_name if mtl_name else 'None'}")
                image = np.asarray(Image.open(thumbnail_url).convert("RGB"), dtype=np.uint8)[np.newaxis, :, :, :]
                final_result["images"].append(image)

                metadata = {}
                if mtl_name is not None:
                    metadata["mtl_name"] = mtl_name
                annotations = subidentifier.annotations
                if "display_name" in annotations:
                    metadata["display_name"] = annotations["display_name"]
                if "description" in annotations:
                    metadata["description"] = annotations["description"]
                if "key_words" in annotations:
                    metadata["key_words"] = annotations["key_words"]

                final_result["camera_metadata"].append(sub_indentifier_annotations.get(mtl_name, {}))
            else:
                raise Exception(f"Failed to create thumbnail: {url} with mtl name {mtl_name if mtl_name else 'None'}")

    final_result["images"] = np.concatenate(final_result["images"], axis=0)
    return final_result


@router.post("/batchrender")
async def batch_render(
    req: BatchRequestRenderUSD,
    renderer: ViewRenderer = router.get_facility("view_renderer"),
    cache=router.get_facility("cache"),
):
    """Render a various views of a USD file"""

    # get camera parameters
    camera_parameters: CameraParameters = get_camera_parameters(req.render_settings, renderer)

    for it, url in enumerate(req.url_list):
        # get key of the element in hash
        if req.url_list_path_override is not None:
            url_hash = get_key(req.url_list_path_override[it])
        elif url.endswith(".mdl"):
            url_hash = get_key(url + json.dumps(req.mtl_name_dict.get(url)))
        else:
            url_hash = get_key(url)

        # get camera positions
        # NOTE: It is possible to move this outside of the loop, but in that case in case of random camera placement
        #  camera positions will be fixed for all assets in a batch, which may introduce some bias. Placing this
        #  operation inside the loop should not introduce a lot of complexity, but will keep camera placement random
        #  for all the assets in a batch
        camera_positions: List[CameraPosition] = get_camera_positions(req.render_settings)

        server = omni.client.break_url(url).host
        if server is None:
            server = "localhost"

        # check if this file is already processed
        content: ContentType
        if (await omni.client.stat_async(url))[0] != omni.client.Result.OK:
            if req.url_list_path_override is not None:
                content = ContentType(
                    path=req.url_list_path_override[it],
                    content="load_error",
                    exception="File not found",
                    traceback="File not found",
                )
            else:
                content = ContentType(
                    path=url,
                    content="load_error",
                    exception="File not found",
                    traceback="File not found",
                )
        elif req.render_settings.force_regenerate or url_hash not in cache.keys():
            with print_wrapper(f"Rendering of '{url}'", logger=logger.info):
                # run rendering
                message = f"Rendering of {url}"
                if req.url_list_path_override is not None and req.url_list_path_override[it] != url:
                    message += f"({req.url_list_path_override[it]})"
                logger.info(message)

                try:
                    if url.endswith(".mdl"):
                        mtl_name_dict = {}
                        if req.mtl_name_dict is not None:
                            mtl_name_dict = req.mtl_name_dict
                        rendered_content = await mdlrender(
                            url=url,
                            mtl_names=mtl_name_dict.get(url),
                            width=req.render_settings.width,
                            height=req.render_settings.height,
                            mdl_template_url=req.render_settings.mdl_template_url,
                            mdl_stdin=req.render_settings.mdl_stdin,
                        )
                    else:
                        rendered_content = await renderer.get_asset_renderings(
                            omni_path=url,
                            auth_dict=req.auth,
                            adjust_camera_multiplier=req.render_settings.adjust_camera_multiplier,
                            render_existing_views=req.render_settings.render_existing_views,
                            filter_by_segmentation=req.render_settings.filter_by_segmentation,
                            camera_positions=camera_positions,
                            camera_parameters=camera_parameters,
                            sensors=req.render_settings.sensors,
                        )

                    # store rendered content in service cache
                    if req.url_list_path_override is not None:
                        content = ContentType(
                            path=req.url_list_path_override[it],
                            content=serialize(rendered_content),
                        )
                    else:
                        content = ContentType(path=url, content=serialize(rendered_content))
                    cache[url_hash] = content
                except TimeoutError as e:
                    tb = traceback.format_exc()
                    if req.url_list_path_override is not None:
                        content = ContentType(
                            path=req.url_list_path_override[it],
                            content="timeout",
                            exception=str(e),
                            traceback=tb,
                        )
                    else:
                        content = ContentType(path=url, content="timeout", exception=str(e), traceback=tb)
                    logger.warning("Timeout error of %s", url)
                except LoadError as e:
                    tb = traceback.format_exc()
                    print("tb", tb)
                    if req.url_list_path_override is not None:
                        content = ContentType(
                            path=req.url_list_path_override[it],
                            content="load_error",
                            exception=str(e),
                            traceback=tb,
                        )
                    else:
                        content = ContentType(
                            path=url,
                            content="load_error",
                            exception=str(e),
                            traceback=tb,
                        )
                    logger.warning("Load error of %s", url)
                except InvalidMTLNames as e:
                    tb = traceback.format_exc()
                    if req.url_list_path_override is not None:
                        content = ContentType(
                            path=req.url_list_path_override[it],
                            content="invalid_mtl_names",
                            exception=str(e),
                            traceback=tb,
                        )
                    else:
                        content = ContentType(
                            path=url,
                            content="invalid_mtl_names",
                            exception=str(e),
                            traceback=tb,
                        )
                    logger.warning("Invalid MTL names of %s", url)
                except Exception as e:
                    tb = traceback.format_exc()
                    if req.url_list_path_override is not None:
                        content = ContentType(
                            path=req.url_list_path_override[it],
                            content=f"Error rendering: {str(e)}",
                            exception=str(e),
                            traceback=tb,
                        )
                    else:
                        content = ContentType(
                            path=url,
                            content=f"Error rendering: {str(e)}",
                            exception=str(e),
                            traceback=tb,
                        )
                    logger.exception("Rendering exception: %s", str(e))
        else:
            content = cache[url_hash]

        payload = ResponsePayload(request="result", url=url, url_hash=url_hash, payload=content)

        # send data back
        r = None
        with print_wrapper(
            f"sending payload of size: {get_size(content.content)}",
            logger=logger.info,
            print_after=False,
        ):
            if req.ws is not None:
                r = await ws_send(req.ws, payload)
            if req.http is not None:
                r = await http_send(req.http, payload)
            if req.redis is not None:
                r = await redis_send(req.redis, payload)
            if req.local_path is not None:
                asset_path = os.path.join(req.local_path, get_key(content.path))
                with open(asset_path, "w") as f:
                    json.dump(payload.dict(), f)

        if r is not None and r["status"] != ResponseStatus.ok:
            raise ConnectionError(r["response"])

    return {"status": "finished"}


def get_camera_positions(render_settings: RenderSettings) -> List[CameraPosition]:
    """Get camera postions depending on the placement strategy

    Args:
        render_settings (RenderSettings): rendering settings

    Raises:
        NotImplementedError: in case placement strategy is unknown

    Returns:
        List[CameraPosition]: list of camera positions that need to be rendered
    """
    camera_placing_strategy = CameraPlacingStrategy(render_settings.camera_placing_strategy)
    camera_positions = []
    if camera_placing_strategy == CameraPlacingStrategy.manual:
        if render_settings.camera_positions is None:
            camera_positions = [CameraPosition(el=el, az=az) for el in ELEVATIONS for az in AZIMUTHS]
        else:
            camera_positions = render_settings.camera_positions
    elif camera_placing_strategy == CameraPlacingStrategy.random:
        camera_positions = [
            CameraPosition(el=np.random.rand() * 90, az=np.random.rand() * 360)
            for _ in range(render_settings.n_random_cameras)
        ]
    else:
        raise NotImplementedError(f"Unknown camera placing strategy: {camera_placing_strategy}")
    return camera_positions


def get_camera_parameters(render_settings: RenderSettings, render: ViewRenderer) -> CameraParameters:
    """Get camera parameters from render settings or set default variables.

    Args:
        render_settings (RenderSettings): rendering settings from rendering request
        render (ViewRenderer): rendering class

    Returns:
        CameraParameters: resulting camera parameters
    """
    # get rendering settings
    if render_settings.camera_parameters is None:
        return CameraParameters(width=render.config["kit"]["width"], height=render.config["kit"]["height"])
    else:
        return render_settings.camera_parameters


def serialize(content) -> str:
    return pickle_data(content, compression_type="zlib")


def get_key(url: str) -> str:
    return hashlib.sha256(str(url).encode()).hexdigest()
