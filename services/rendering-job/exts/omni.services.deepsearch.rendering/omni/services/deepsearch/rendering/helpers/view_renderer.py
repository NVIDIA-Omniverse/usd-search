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

import ast

# standard modules
import asyncio
import math
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from functools import partial
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

import carb

# third party modules
import numpy as np
import omni.client
import omni.kit.commands

# local/ proprietary modules
# > Kit modules
import omni.usd
import toml
from numpy.typing import NDArray
from pxr import Gf, Sdf, Usd, UsdGeom, UsdSkel
from pydantic import BaseSettings, Field

from . import (
    DEFAULT_SENSOR_SET,
    SEMANTIC_LABEL,
    DataRetrievalError,
    EmptyResponse,
    IncompleteData,
    LoadError,
    SyntheticDataStepTimeout,
    logger,
)
from .data import (
    BBox,
    CameraParameters,
    CameraPosition,
    CenterInfo,
    GetDataResponse,
    Sensors,
    Status,
)
from .log_utils import prepare_message, print_wrapper
from .misc_utils import str2bool
from .syntheticdata_async import SyntheticDataHelper

# > deeptag modules
from .utils import (
    async_loading_wrapper,
    camera_fit_to_prim_wrapper,
    create_domelight_texture,
    create_prim,
    get_auth_token_async,
    get_stage_bounds,
    get_stage_content,
    wait_n_frames,
)

bin_path = os.path.abspath(os.path.dirname(__file__))
ext_source_path = f"{bin_path}/../../../../../"
_ASSET_PRIM_PATH = "/Asset"


def _is_rgb_valid(content: Dict[str, Any]) -> bool:
    """Check if RGB data in content is valid."""
    rgb = content.get(Sensors.rgb.value)
    if rgb is None:
        return False
    rgb_sample = rgb[0] if isinstance(rgb, list) and rgb else rgb
    return hasattr(rgb_sample, "shape") and rgb_sample.size > 0 and 0 not in rgb_sample.shape


def _is_rgb_empty(rgb: Any) -> bool:
    """Check if RGB data is empty or None."""
    return rgb is None or (isinstance(rgb, list) and len(rgb) == 0) or (hasattr(rgb, "size") and rgb.size == 0)


def _find_semantic_key(segmentation_data: Dict[str, Any]) -> Optional[str]:
    """Find the key containing SEMANTIC_LABEL in segmentation data."""
    for key in segmentation_data.keys():
        if SEMANTIC_LABEL in key.split(","):
            return key
    return None


def _append_sensor_content(
    output_dict: Dict[str, list],
    content: Dict[str, Any],
    sensors: set,
    segmentation: str,
) -> None:
    """Append sensor content to output dict, handling RGB specially."""
    for k in output_dict:
        if k in sensors and k in content and k != segmentation:
            sensor_content = content[k] if isinstance(content[k], list) else [content[k]]
            if k == Sensors.rgb.value:
                output_dict[k].extend([data[..., :3] for data in sensor_content])
            else:
                output_dict[k].extend(sensor_content)


@asynccontextmanager
async def _rgb_only_fallback_settings(renderer: "ViewRenderer"):
    """Context manager to temporarily set RGB-only fallback settings."""
    prev_sensors = renderer.sensors
    prev_filter = renderer.filter_by_segmentation
    prev_adjust = renderer.adjust_camera_multiplier
    prev_existing_views = renderer.render_existing_views if hasattr(renderer, "render_existing_views") else None
    try:
        renderer.sensors = {Sensors.rgb.value, Sensors.camera_params.value}
        renderer.filter_by_segmentation = False
        renderer.adjust_camera_multiplier = False
        renderer.render_existing_views = False
        yield
    finally:
        renderer.sensors = prev_sensors
        renderer.filter_by_segmentation = prev_filter
        renderer.adjust_camera_multiplier = prev_adjust
        if prev_existing_views is not None:
            renderer.render_existing_views = prev_existing_views


class ViewRendererConfig(BaseSettings):
    n_frames_to_wait: int = Field(
        default=10,
        description="Number of frames to wait for syntheticdata to complete the async step",
    )
    n_frames_to_wait_for_scene_to_settle: int = Field(
        default=2, description="Number of frames to wait for the scene to settle"
    )


class ViewRenderer:
    def __init__(
        self,
        config: dict = {},
        token_based_authentication: bool = str2bool(os.getenv("TOKEN_BASED_AUTH", "True")),
        rendering_timeout: float = ast.literal_eval(os.getenv("RENDERING_TIMEOUT", "1800")),
        asset_loading_tracker: str = os.getenv("ASSET_LOADING_TRACKER", "event"),
        load_asset_as_reference: bool = str2bool(os.getenv("LOAD_ASSET_AS_REFERENCE", "True")),
    ):
        # get extension version
        self.version: str = toml.load(f"{ext_source_path}/config/extension.toml", _dict=dict)["package"]["version"]

        self._view_renderer_config = ViewRendererConfig()

        self.rendering_timeout = rendering_timeout
        self.asset_loading_tracker = asset_loading_tracker
        self.token_based_authentication = token_based_authentication
        self._load_as_reference = load_asset_as_reference

        self.app = omni.kit.app.get_app()
        self.settings_interface = carb.settings.get_settings()

        self.up_axis = config.get("up_axis", "Y").upper()
        self.asset_status: Dict[str, Any] = {}
        self.config = config
        # # set some default settings
        self._restore_default_settings()

        # camera parameters
        self.base_fov_multiplier = 0.5
        self.base_camera_distance_multiplier = self.config["camera"]["base_camera_distance_multiplier"]
        self.camera_fov_multiplier = self.config["camera"]["camera_fov_multiplier"]
        self._semantic_prim_list: List[Any] = []
        self.filter_by_segmentation = False
        self._scene_has_renderable_geometry = False
        self._environment_initialized = False
        self._current_asset_sublayer: Optional[str] = None
        self._xform_layer: Optional[Sdf.Layer] = None

        # set-up pushing logs to the Queue
        carb.log_info("View renderer is initialized")

        if self.token_based_authentication:
            # initialize dictionary of tokens
            self.auth_tokens: Dict[str, Dict[str, str]] = dict()
            # register authorize callbak
            _ = omni.client.register_authorize_callback(
                lambda scheme, host_and_port: self.auth_tokens[host_and_port.rsplit(":", 1)[0]]["auth_token"]
            )

    def _restore_default_settings(self):
        # reference kit config
        kit_conf = self.config["kit"]

        # rendering settings
        self.settings_interface.set_string("/rtx/rendermode", kit_conf["renderer"])
        self.settings_interface.set_int(
            "/rtx/hydra/subdivision/refinementLevel",
            kit_conf["subdivision_refinement_level"],
        )
        # switch off texture streaming
        self.settings_interface.set_bool("/rtx-transient/resourcemanager/enableTextureStreaming", False)

        # switch off some viewport options
        self.settings_interface.set_int("/persistent/app/viewport/displayOptions", 1156)
        self.settings_interface.set_bool("/app/viewport/grid/enabled", False)

        # suppress harmless IRenderSettings errors during sublayer recomposition
        self.settings_interface.set_string("/log/channels/omni.usd-abi.plugin", "warn")

        # support for old matrial schema
        self.settings_interface.set_bool(
            "/app/hydra/supportOldMdlSchema",
            str2bool(os.getenv("OMNI_RENDER_OLD_MDL_SUPPORT", "False")),
        )

        # TODO (arozantsev): got a lot of hangs with Kit (need to check how to set-it up properly)
        self.settings_interface.set_bool("/app/hydraEngine/waitIdle", True)
        self.settings_interface.set_bool("/app/asyncRendering", False)

        # self.settings_interface.set_bool("/rtx/materialDb/syncLoads", True)
        self.settings_interface.set_bool("/omni.kit.plugin/syncUsdLoads", True)

    async def _ensure_environment_stage(self):
        """Create a persistent stage with the dome light; no-op after first call."""
        if self._environment_initialized:
            return

        usd_context = omni.usd.get_context()
        await usd_context.new_stage_async()
        await self.app.next_update_async()

        stage = usd_context.get_stage()
        create_domelight_texture(self.config["domelight_shade"])

        for prim_config in self.config["prims"]:
            if not prim_config.get("enabled", True):
                continue
            if prim_config["path"] == "/DeepSearch/CameraRig1/Ground":
                continue
            create_prim(stage, **prim_config)

        self._xform_layer = Sdf.Layer.CreateAnonymous("xform_overrides")
        root_layer = stage.GetRootLayer()
        root_layer.subLayerPaths.insert(0, self._xform_layer.identifier)

        self._environment_initialized = True
        logger.info("Persistent environment stage initialized")

    async def _load_asset_sublayer(self, omni_path: str):
        """Swap the current asset sublayer for a new one, preserving the environment."""
        if self._xform_layer:
            self._xform_layer.Clear()

        previous = self._current_asset_sublayer
        root_layer = omni.usd.get_context().get_stage().GetRootLayer()

        async with async_loading_wrapper(status=self.asset_status, mode=self.asset_loading_tracker):
            root_layer.subLayerPaths.append(omni_path)
            self._current_asset_sublayer = omni_path

        if previous and previous in root_layer.subLayerPaths:
            root_layer.subLayerPaths.remove(previous)

        asset_layer = Sdf.Layer.Find(omni_path)
        if asset_layer:
            if asset_layer.defaultPrim:
                root_layer.defaultPrim = asset_layer.defaultPrim

            stage = omni.usd.get_context().get_stage()
            asset_up = (
                asset_layer.pseudoRoot.GetInfo("upAxis")
                if asset_layer.pseudoRoot.HasInfo("upAxis")
                else asset_layer.customLayerData.get("upAxis")
            )
            if asset_up:
                UsdGeom.SetStageUpAxis(stage, asset_up)
            else:
                UsdGeom.SetStageUpAxis(stage, UsdGeom.GetFallbackUpAxis())
            logger.debug(
                "Stage upAxis set to %s for %s",
                UsdGeom.GetStageUpAxis(stage),
                omni_path,
            )

        carb.log_info(f"Asset sublayer loaded: {omni_path}")

    async def _load_asset_as_reference(self, omni_path: str):
        """Load only the asset's default prim as a reference, stripping embedded environments.

        Falls back to sublayer loading when the asset has no defaultPrim.
        """
        if self._xform_layer:
            self._xform_layer.Clear()

        stage = omni.usd.get_context().get_stage()
        root_layer = stage.GetRootLayer()

        if stage.GetPrimAtPath(_ASSET_PRIM_PATH).IsValid():
            stage.RemovePrim(_ASSET_PRIM_PATH)

        container = stage.DefinePrim(_ASSET_PRIM_PATH)

        async with async_loading_wrapper(status=self.asset_status, mode=self.asset_loading_tracker):
            container.GetReferences().AddReference(Sdf.Reference(omni_path))

        asset_layer = Sdf.Layer.Find(omni_path)
        if not asset_layer or not asset_layer.defaultPrim:
            logger.warning("Asset has no default prim, falling back to sublayer: %s", omni_path)
            stage.RemovePrim(_ASSET_PRIM_PATH)
            await self._load_asset_sublayer(omni_path)
            return

        root_layer.defaultPrim = _ASSET_PRIM_PATH.lstrip("/")

        asset_up = (
            asset_layer.pseudoRoot.GetInfo("upAxis")
            if asset_layer.pseudoRoot.HasInfo("upAxis")
            else asset_layer.customLayerData.get("upAxis")
        )
        if asset_up:
            UsdGeom.SetStageUpAxis(stage, asset_up)
        else:
            UsdGeom.SetStageUpAxis(stage, UsdGeom.GetFallbackUpAxis())
        logger.debug("Stage upAxis set to %s for %s", UsdGeom.GetStageUpAxis(stage), omni_path)

        self._current_asset_sublayer = omni_path
        carb.log_info(f"Asset reference loaded: {omni_path}")

    def _clear_asset_sublayer(self):
        """Clear transient overrides; asset removal is deferred to the next load."""
        if self._xform_layer:
            self._xform_layer.Clear()

    async def _get_image_data(self, rendering_context: SyntheticDataHelper, max_attempts: int = 5) -> GetDataResponse:
        """Capture sensor data.

        Args:
            rendering_context (SyntheticDataHelper): Context that creates SyntheticData writes and
                annotators that allow reading sensor data.
            max_attempts (int, optional): Number of attempts that the system tries to read sensor data
              (normally first attempts is successful, but it could happen that some sensor takes time
              to get initialized). Defaults to 5.

        Raises:
            DataExtractionFailed: in case some sensor data was missing

        Returns:
            GetDataResponse: mapping between sensor name and data returned by the SyntheticData API.
        """
        # make sure the rendering settings are correct
        self._restore_default_settings()

        content: Dict[str, Any] = {}
        status: Status
        for _ in range(max_attempts):
            try:
                content = await rendering_context.get_data()
                rgb_valid = _is_rgb_valid(content)
                if not rgb_valid:
                    raise IncompleteData("RGB frame is missing or empty")
                try:
                    rendering_context.verify_data(content, verify_name=False)
                    status = Status.ok
                    break
                except (AssertionError, IncompleteData) as e:
                    if not self.filter_by_segmentation and rgb_valid:
                        logger.warning(
                            "Missing optional sensor data (%s); continuing with RGB-only payload",
                            str(e),
                        )
                        status = Status.ok
                        break
                    logger.warning("Data read failed: %s", str(e))
                    status = Status.incomplete_data
            except IncompleteData as e:
                logger.warning("Incomplete data on attempt: %s", str(e))
                status = Status.incomplete_data
            except DataRetrievalError as e:
                logger.warning("SyntheticData error: %s", str(e))
                status = Status.data_retrieval_error
            except (asyncio.TimeoutError, SyntheticDataStepTimeout) as e:
                logger.warning("SyntheticData hangs on performing async step: %s", str(e))
                status = Status.syntheticdata_timeout_error
            except Exception as e:
                logger.exception(e)
                status = Status.unknown_error

        return GetDataResponse(status=status, data=content)

    def _prepare_output_dict(self) -> dict:
        return {s: [] for s in self.sensors}

    async def _render_existing_camera_views(
        self,
        paths_types_list: List[tuple],
        ignore_list: list = [
            "/OmniverseKit_Persp",
            "/OmniverseKit_Top",
            "/OmniverseKit_Right",
            "/OmniverseKit_Front",
        ],
    ) -> dict:
        """Render existing camera views in the scene.

        Args:
            paths_types_list (List[tuple]): list of paths in a USD file
            ignore_list (list, optional): list of iterms that need to be ignored.
                Defaults to ``[f"/OmniverseKit_{el}" for el in ["Persp", "Top", "Right", "Front"]]``.

        Returns:
            dict: dictionary of images and segmentations from existing camera views
        """
        log_views = []
        output_dict = self._prepare_output_dict()

        logger.debug("Rendering existing views")

        render_products_paths = []
        # render views from existing cameras
        try:
            for p, t in paths_types_list:
                # if prim is a camera - render its view
                if t.lower() == "camera" and p not in ignore_list and not p.startswith("/DeepSearch"):
                    render_products_paths.append(p)
                    # log some view information
                    log_views.append(f"{p} (stage view)")

            if len(render_products_paths) > 0:
                render_products = list(render_products_paths)

        except Exception as e:
            logger.error(f"render products creation failed: {str(e)}")
            return output_dict

        number_of_existing_views = len(render_products_paths)

        if number_of_existing_views == 0:
            logger.info("No Existing Cameras found")
            return output_dict

        for view_number, render_product in enumerate(render_products):
            with print_wrapper(
                f"Rendering view [{view_number + 1} / {number_of_existing_views}]",
                logger=logger.info,
            ):
                segmentation_enabled = (
                    Sensors.semantic_segmentation.value in self.sensors or self.filter_by_segmentation
                )
                async with SyntheticDataHelper(
                    render_products=[render_product],
                    rgb=True,
                    semantic_segmentation=segmentation_enabled,
                    distance_to_camera=Sensors.distance_to_camera.value in self.sensors,
                    distance_to_image_plane=Sensors.distance_to_image_plane.value in self.sensors,
                    normals=Sensors.normals.value in self.sensors,
                    camera_params=True,
                    pointcloud=Sensors.pointcloud.value in self.sensors,
                    syntheticdata_kwargs={
                        "width": self.camera_parameters.width,
                        "height": self.camera_parameters.height,
                    },
                ) as context:
                    await wait_n_frames(self.app, n=self._view_renderer_config.n_frames_to_wait)
                    response: GetDataResponse = await self._get_image_data(rendering_context=context)

                if response.status != Status.ok:
                    logger.warning(f"status of the operation is not Ok: {response.status}")
                    continue

                content = response.data

                if content == {}:
                    logger.warning("Empty data dictionary")
                    continue

                # alias for Sensors.semantic_segmentation.value
                segmentation: str = Sensors.semantic_segmentation.value

                try:
                    apply_segmentation_gate = self.filter_by_segmentation and segmentation in self.sensors
                    if not apply_segmentation_gate:
                        # No semantic gating; append sensor data directly.
                        for k in output_dict:
                            if k in self.sensors and k in content and k != segmentation:
                                if k == Sensors.rgb.value:
                                    output_dict[k].append(content[k][0][np.newaxis, :, :, :3])
                                else:
                                    output_dict[k].append(content[k][0])
                        if segmentation in self.sensors and segmentation in content:
                            selected_key = _find_semantic_key(content[segmentation][0])
                            if selected_key is not None:
                                output_dict[segmentation].append(content[segmentation][0][selected_key])
                    else:
                        for camera_view_counter, camera_view_content in enumerate(content[segmentation]):
                            if SEMANTIC_LABEL not in camera_view_content:
                                continue

                            segmentation_mask = camera_view_content[SEMANTIC_LABEL]
                            # append novel view only is some part of the item is present in the segmentation mask
                            if np.sum(segmentation_mask) == 0:
                                continue

                            for k in output_dict:
                                if k in self.sensors and k in content and k != segmentation:
                                    if k == Sensors.rgb.value:
                                        # take only the first 3 channels as they correspond to RGB
                                        output_dict[k].append(content[k][camera_view_counter][np.newaxis, :, :, :3])
                                    else:
                                        output_dict[k].append(content[k][camera_view_counter])

                            # merge segmentation masks from different objects
                            output_dict[segmentation].append(segmentation_mask)

                except Exception as e:
                    logger.exception(f"existing view {t} rendering error: {str(e)}")

        prepare_message(
            msg=f"Rendered {len(log_views)} views:",
            item_list=log_views,
            logger=logger.info,
        )

        return output_dict

    async def _set_camera(self, fov_multiplier: float = 0.5, clipping_range_max: float = 1000000.0):
        """Create a set of Rigs and a Camera that would used to record views of the asset.

        Args:
            fov_multiplier (float, optional): Field of View multiplier - has direct influence on
                Focal length. Defaults to 0.5.
            clipping_range_max (float, optional): Maximum clipping range distance. Defaults to 1000000.0.
        """
        stage = omni.usd.get_context().get_stage()
        self.camera_rig1 = UsdGeom.Xformable(create_prim(stage, "/DeepSearch/CameraRig1", "Xform"))
        self.camera_rig2 = UsdGeom.Xformable(create_prim(stage, "/DeepSearch/CameraRig1/CameraRig2", "Xform"))
        self.camera_rig1.AddTranslateOp().Set((0.0, 0.0, 0.0))
        self.camera_rig1.AddRotateXYZOp().Set((0.0, 0.0, 0.0))
        self.camera_rig1.AddScaleOp().Set((1.0, 1.0, 1.0))
        self.camera_rig2.AddTranslateOp().Set((0.0, 0.0, 0.0))
        self.camera_rig2.AddRotateXYZOp().Set((0.0, 0.0, 0.0))
        self.camera_rig2.AddScaleOp().Set((1.0, 1.0, 1.0))

        self.camera = create_prim(stage, "/DeepSearch/CameraRig1/CameraRig2/Camera", "Camera")

        # Set camera parameters
        horizontal_aperture = self.camera.GetAttribute("horizontalAperture").Get()
        vertical_aperture = horizontal_aperture * self.camera_parameters.width / self.camera_parameters.height
        fov = math.radians(self.config["camera"]["fov"] / 2.0)
        focal_length = horizontal_aperture / math.tan(fov) * fov_multiplier
        logger.debug("Effective focal length: %f", focal_length)

        self.camera.GetAttribute("verticalAperture").Set(vertical_aperture)
        self.camera.GetAttribute("focalLength").Set(focal_length)
        self.camera.GetAttribute("clippingRange").Set((0.01, clipping_range_max))

        await self.app.next_update_async()

    async def _render(
        self,
        el: float,
        az: float,
        prim: Usd.Typed,
        camera: Usd.Typed,
        rendering_context: SyntheticDataHelper,
        translate: Optional[Tuple[float, float, float]] = None,
        offset: Optional[Tuple[float, float, float]] = None,
        scale: Optional[Tuple[float, float, float]] = None,
        bbox_size: Optional[Tuple[float, float, float]] = None,
        camera_distance_multiplier: float = 1.2,
        n_frames_for_scene_to_settle: Optional[int] = None,
    ) -> dict:
        """Render the scene from a specific view point. Rendering includes getting all the sensor content
        defined within rendering_context.

        Args:
            el (float): Elevation of the camera.
            az (float): Azimuth of the camera.
            prim (Usd.Typed): Prim that need to be rendered (should be placed in the center of the view)
            camera (Usd.Typed): Camera that will be moved a provided azimuth and elevation and used for
                getting sensor data
            rendering_context (SyntheticDataHelper): SyntheticData context that is used for getting sensor data.
            translate (Optional[Tuple[float, float, float]], optional): Optional global translation of the
                camera rig. Defaults to None.
            offset (Optional[Tuple[float, float, float]], optional): Optional global offset of the camera
                rig. Defaults to None.
            scale (Optional[Tuple[float, float, float]], optional): Optional global scale of the camera
                rig. Defaults to None.
            bbox_size (Optional[Tuple[float, float, float]], optional): Optional size of the bounding box
                around the object of interest. Defaults to None.
            camera_distance_multiplier (float, optional): Distance from the center of the object to the
                camera, divided by the bounding circle radius. Defaults to 1.2.

        Returns:
            dict: mapping between sensor name and data returned by the SyntheticData API.
        """
        with print_wrapper("rendering view", logger=logger.debug):
            # Clear previous transforms
            self.camera_rig2.ClearXformOpOrder()
            if offset is not None:
                self.camera_rig2.AddTranslateOp().Set(Gf.Vec3d(float(offset[0]), float(offset[1]), float(offset[2])))
            # Change azimuth angle
            self.camera_rig2.AddRotateZOp().Set(az)
            # Change elevation angle
            self.camera_rig2.AddRotateXOp().Set(el)
            # change translation
            if translate is not None or scale is not None:
                self.camera_rig1.ClearXformOpOrder()
            if scale is not None:
                self.camera_rig1.AddScaleOp().Set(Gf.Vec3d(*scale))
            if translate is not None:
                self.camera_rig1.AddTranslateOp().Set(Gf.Vec3d(*translate))
            # get sensor data
            async with camera_fit_to_prim_wrapper(
                self.app,
                camera,
                prim,
                distance_multiplier=camera_distance_multiplier,
                bbox_size=bbox_size,
            ):
                with print_wrapper("waiting for scene to settle", logger=logger.debug):
                    await wait_n_frames(
                        self.app,
                        n=(
                            self._view_renderer_config.n_frames_to_wait
                            if n_frames_for_scene_to_settle is None
                            else n_frames_for_scene_to_settle
                        ),
                    )
                response: GetDataResponse = await self._get_image_data(rendering_context)

            if response.status == Status.syntheticdata_timeout_error:
                raise SyntheticDataStepTimeout()
            elif response.status == Status.incomplete_data:
                raise IncompleteData()
            elif response.status == Status.data_retrieval_error:
                raise DataRetrievalError()
            elif response.status != Status.ok:
                raise Exception(f"Unknown rendering error: Status is not Ok: {response.status}")

        return response.data

    @staticmethod
    def get_bbox_key_from_semantic_label(
        gt: Dict[str, List[Dict[str, Any]]],
    ) -> Optional[str]:
        semantic_label_key: Optional[str] = None
        for key in gt[Sensors.bounding_box_2d_tight_fast][0].keys():
            if SEMANTIC_LABEL in key:
                semantic_label_key = key
                break

        return semantic_label_key

    # Function to load get the center of the object in the camera view
    async def get_center(
        self,
        render: Callable,
        offset: NDArray[np.floating],
        x_angle: float,
        distance_multiplier: float,
        view_size: float,
    ) -> CenterInfo:
        while True:
            try:
                gt = await render(
                    x_angle,
                    0,
                    offset=offset,
                    camera_distance_multiplier=distance_multiplier,
                )

                # fix for the latest version of Synthetic data
                semantic_label_key: Optional[str] = self.get_bbox_key_from_semantic_label(gt)

                if semantic_label_key is None:
                    return CenterInfo(all_inside=False)

                bb2d: BBox = gt[Sensors.bounding_box_2d_tight_fast][0][semantic_label_key]
                all_inside = bb2d.xmin > 0 and bb2d.ymin > 0 and bb2d.xmax < view_size - 1 and bb2d.ymax < view_size - 1
                center = np.array(((bb2d.xmin + bb2d.xmax) / 2, (bb2d.ymin + bb2d.ymax) / 2))
                offset = np.array((center[0] - view_size / 2, center[1] - view_size / 2))
                res = CenterInfo(
                    center=tuple(center),
                    all_inside=all_inside,
                    offset=tuple(offset),
                    offset_norm=np.linalg.norm(offset),
                )
                return res
            except KeyError as exc_info:
                logger.warning("incomplete data: %s", str(exc_info))
                await asyncio.sleep(0.1)
            except EmptyResponse:
                return CenterInfo(all_inside=False)

    async def _adjust_center_and_multiplier(
        self,
        camera: Usd.Typed,
        prim: Usd.Typed,
        rendering_context: SyntheticDataHelper,
        translate: Tuple[float, float, float],
        scale: Tuple[float, float, float],
        bbox_size: Optional[Tuple[float, float, float]] = None,
        camera_distance_multiplier: float = 1.2,
        eps: float = 0.01,
    ) -> Tuple[float, Tuple[float, float, float]]:
        """Automatically adjust the camera center and distance to the object such that the object
        is in the center and occupies the majority of the view.

        Args:
            camera (Usd.Typed): Camera that will be moved a provided azimuth and elevation and
                used for getting sensor data
            prim (Usd.Typed): Prim that need to be rendered (should be placed in the center of the view)
            rendering_context (SyntheticDataHelper): SyntheticData context that is used for getting sensor data.
            translate (Tuple[float, float, float]): global translation of the camera rig
            scale (Tuple[float, float, float]): global scale of the camera rig
            bbox_size (Optional[Tuple[float, float, float]], optional): Optional size of the bounding
                box around the object of interest. Defaults to None.
            camera_distance_multiplier (float, optional): Distance from the center of the object to
                the camera, divided by the bounding circle radius. Defaults to 1.2.
            eps (float, optional): Threshold that stops the adjustment process if the position and
                size of the object does not change much. Defaults to 0.01.

        Raises:
            EmptyResponse: if empty data was returned from SyntheticData Sensor API

        Returns:
            Tuple[float, Tuple[float, float, float]]: distance multipler and offset that needs to
                be applied to the scene
        """
        render = partial(
            self._render,
            camera=camera,
            prim=prim,
            rendering_context=rendering_context,
            scale=scale,
            bbox_size=bbox_size,
            translate=translate,
            n_frames_for_scene_to_settle=self._view_renderer_config.n_frames_to_wait_for_scene_to_settle,  # Here we only care about the segmentation masks, so if the scene visualization is not settled - that's ok. Actual rendering happens later
        )

        ##########################
        # Adjust camera position #
        ##########################

        final_offset = np.zeros((3,), dtype=np.float32)
        min_dm: float = 0
        max_dm: float = camera_distance_multiplier
        view_size = min(self.camera_parameters.height, self.camera_parameters.width)
        distance_multiplier: float = camera_distance_multiplier

        for x_angle in [0, 270]:
            # align center
            orig_center_info: CenterInfo = await self.get_center(
                render=render,
                offset=np.zeros((3,), dtype=np.float32),
                x_angle=x_angle,
                distance_multiplier=distance_multiplier,
                view_size=view_size,
            )
            # if the scene is empty from the beginning - raise an error
            if orig_center_info.center is None:
                logger.warning(
                    "No semantic bbox found for centering; " "using default camera distance/offset for %s",
                    self.omni_path,
                )
                return camera_distance_multiplier, (0.0, 0.0, 0.0)

            # create a vector that would store the information how the object
            # needs to be shifted in either the XY-plane (in case x_angle=0)
            # or in the XZ-plane (in case x_angle=90)
            logger.debug(f"initial vector ({x_angle}): {orig_center_info.offset} ({orig_center_info.offset_norm})")
            # define a multiplecative factor (how far should the offset be with respec to original center)
            multiplicative_factor = 1.0
            if (
                orig_center_info.offset is not None
                and orig_center_info.offset_norm is not None
                and orig_center_info.offset_norm > 1
            ):
                # limit the number of possible steps
                for _ in range(1000):
                    if x_angle == 0:
                        offset = np.array((*orig_center_info.offset, 0))
                    elif x_angle == 270:
                        offset = np.array((orig_center_info.offset[0], 0, orig_center_info.offset[1]))
                    # get the new center of the object (offsetted by the "object_center_offset")
                    new_center_info: CenterInfo = await self.get_center(
                        render=render,
                        offset=multiplicative_factor * offset,
                        x_angle=x_angle,
                        distance_multiplier=distance_multiplier,
                        view_size=view_size,
                    )

                    if not new_center_info.all_inside:
                        logger.debug("not all inside..")
                        multiplicative_factor /= 3
                        continue

                    logger.debug(f"+ new vector: {new_center_info.offset} ({new_center_info.offset_norm})")
                    if new_center_info.all_inside and new_center_info.offset_norm != orig_center_info.offset_norm:
                        break
                    if new_center_info.offset_norm == orig_center_info.offset_norm:
                        multiplicative_factor *= 1.1
                        continue

                # Compute the resulting multiplication factor
                resulting_multiplicative_factor = (
                    orig_center_info.offset_norm
                    * multiplicative_factor
                    / np.linalg.norm(np.array(orig_center_info.center) - np.array(new_center_info.center))
                )
                final_offset += np.array(offset) * resulting_multiplicative_factor
                logger.debug("final translation offset: %s", str(final_offset))

        ##########################
        # Adjust camera distance #
        ##########################

        # iteration counter that allows cancelling interations after certain number of steps to
        #  prevent infinite loop
        not_all_inside_counter: int = 0
        prev_dm: float = distance_multiplier

        # This is a loop to adjust camera distance.
        # The exit conditions for the loop are:
        #  > if camera distance_multiplier value does not change from iteration to iteration
        #  > if the object is not completely inside for the number of steps higher that a threshold (10)

        while True:
            dims = []
            for cam_pos in self.camera_positions:
                gt = await render(
                    cam_pos.el,
                    cam_pos.az,
                    offset=final_offset,
                    camera_distance_multiplier=distance_multiplier,
                )
                semantic_label_key: Optional[str] = self.get_bbox_key_from_semantic_label(gt)

                if semantic_label_key is None:
                    logger.warning(
                        "No semantic bbox found for distance adjustment; "
                        "using default camera distance/offset for %s",
                        self.omni_path,
                    )
                    return camera_distance_multiplier, (0.0, 0.0, 0.0)

                bb2d: BBox = gt[Sensors.bounding_box_2d_tight_fast][0][semantic_label_key]
                all_inside = bb2d.xmin > 0 and bb2d.ymin > 0 and bb2d.xmax < view_size - 1 and bb2d.ymax < view_size - 1
                if not all_inside:
                    not_all_inside_counter += 1
                    distance_multiplier = distance_multiplier * 1.2
                    break
                dims.extend([bb2d.xmax - bb2d.xmin, bb2d.ymax - bb2d.ymin])

            # prevent infinite loop
            if not all_inside and not_all_inside_counter >= 10:
                distance_multiplier = prev_dm
                break

            if not all_inside:
                continue

            prev_dm = distance_multiplier
            if max(dims) > self.config["object_min_size"] * view_size:
                min_dm = distance_multiplier
                distance_multiplier = (min_dm + max_dm) / 2
            elif max(dims) < self.config["object_min_size"] * view_size:
                max_dm = distance_multiplier
                distance_multiplier = (min_dm + max_dm) / 2
            else:
                break

            if np.abs(prev_dm - distance_multiplier) < eps:
                break

            logger.debug(f"current distance multiplier: {distance_multiplier}")
        logger.debug(f"final distance multiplier: {distance_multiplier}")

        # make a tuple out of ND array to make sure types match
        final_offset_tuple = (final_offset[0], final_offset[1], final_offset[2])
        return distance_multiplier, final_offset_tuple

    async def _capture_viewpoints(
        self,
        camera: Usd.Typed,
        prim: Usd.Typed,
        rendering_context: SyntheticDataHelper,
        translate: Tuple[float, float, float],
        scale: Tuple[float, float, float],
        bbox_size: Optional[Tuple[float, float, float]] = None,
        camera_distance_multiplier: float = 1.2,
    ) -> Optional[Dict[str, Any]]:
        """Capture the data from the novel camera views.

        Args:
            camera (Usd.Typed): Camera prim that will be used for collecting sensor data
            prim (Usd.Typed): Prim in the scene that need to be in focus
            rendering_context (SyntheticDataHelper): _description_
            rendering_context (SyntheticDataHelper): SyntheticData context that is used for getting sensor data.
            translate (Tuple[float, float, float]): global translation of the camera rig
            scale (Tuple[float, float, float]): global scale of the camera rig
            bbox_size (Optional[Tuple[float, float, float]], optional): Optional size of the
                bounding box around the object of interest. Defaults to None.
            camera_distance_multiplier (float, optional): Distance from the center of the object
                to the camera, divided by the bounding circle radius. Defaults to 1.2.

        Returns:
            Optional[Dict[str, Any]]: Dictionary with the content from sensor data.
        """
        log_views = []
        output_dict = self._prepare_output_dict()

        if self.adjust_camera_multiplier:
            with print_wrapper("adjusting camera multiplier", logger=logger.info):
                dm, offset = await self._adjust_center_and_multiplier(
                    camera,
                    prim,
                    rendering_context=rendering_context,
                    translate=translate,
                    scale=scale,
                    bbox_size=bbox_size,
                    camera_distance_multiplier=camera_distance_multiplier,
                )
        else:
            dm, offset = camera_distance_multiplier, (0.0, 0.0, 0.0)

        render = partial(
            self._render,
            camera=camera,
            prim=prim,
            rendering_context=rendering_context,
            translate=translate,
            offset=offset,
            scale=scale,
            bbox_size=bbox_size,
            camera_distance_multiplier=dm,
        )

        segmentation: str = Sensors.semantic_segmentation.value
        apply_segmentation_gate = self.filter_by_segmentation and segmentation in self.sensors
        # render view for different view points
        for cam_pos in self.camera_positions:
            content = None
            for attempt in range(5):
                try:
                    # get sensor data
                    content = await render(cam_pos.el, cam_pos.az)

                    if not _is_rgb_valid(content):
                        logger.warning("incomplete data: RGB is missing or empty")
                        await asyncio.sleep(0.1)
                        continue

                    if apply_segmentation_gate and segmentation not in content:
                        logger.warning("incomplete data: %s is missing", segmentation)
                        await asyncio.sleep(0.1)
                        continue

                    break
                except (
                    IncompleteData,
                    DataRetrievalError,
                    SyntheticDataStepTimeout,
                ) as e:
                    logger.warning("syntheticdata retry (%s/%s): %s", attempt + 1, 5, str(e))
                    await asyncio.sleep(0.1)
                    continue
                except EmptyResponse:
                    logger.warning("syntheticdata returned empty response; skipping view")
                    content = None
                    break

            if content is None:
                logger.warning("Failed to capture RGB data after retries; skipping view")
                continue

            if not apply_segmentation_gate:
                _append_sensor_content(output_dict, content, self.sensors, segmentation)
                if segmentation in self.sensors and segmentation in content:
                    selected_key = _find_semantic_key(content[segmentation][0])
                    if selected_key is not None:
                        output_dict[segmentation].append(content[segmentation][0][selected_key])
            else:
                # NOTE: SyntheticData may return a comma-separated list of classes if segmentation masks match
                selected_key = _find_semantic_key(content[segmentation][0])
                if selected_key is None:
                    logger.warning("Segmentation label not found; skipping view")
                    continue

                segmentation_mask = content[segmentation][0][selected_key]
                # append novel view only is some part of the item is present in the segmentation mask
                if np.sum(segmentation_mask) > 0:
                    _append_sensor_content(output_dict, content, self.sensors, segmentation)
                    # merge segmentation masks from different objects
                    output_dict[segmentation].append(segmentation_mask)

            # log some information about the view that have been used
            log_views.append(f"World/Camera (added view): (elevation: {cam_pos.el}, azimuth: {cam_pos.az})")

        prepare_message(
            msg=f"Rendered {len(log_views)} views:",
            item_list=log_views,
            logger=logger.info,
        )

        # stack the results along the batch dimension
        return output_dict

    async def _setup_environment(self, stage: Usd.Stage):
        """Normalize axis, compute bounds, and create camera rig and ground plane."""
        stage.RemovePrim("/DeepSearch/CameraRig1/Ground")

        await wait_n_frames(self.app, n=10)
        await asyncio.sleep(1)

        ref_up_axis = UsdGeom.GetStageUpAxis(stage)
        logger.debug("Up axis: %s", ref_up_axis)

        try:
            if ref_up_axis == "Y":
                prev_target = stage.GetEditTarget()
                stage.SetEditTarget(Usd.EditTarget(self._xform_layer))

                prim = stage.GetDefaultPrim()
                logger.debug(f"default prim: {prim.GetPath()}")
                if prim.IsValid():
                    default_prim = UsdGeom.Xform(prim)
                    default_prim.ClearXformOpOrder()
                    default_prim.AddRotateXOp().Set(90)
                else:
                    for prim in stage.GetPseudoRoot().GetChildren():
                        if str(prim.GetPath()).startswith("/DeepSearch"):
                            continue
                        logger.debug(f"Top-level prim: {prim.GetPath()}")
                        if UsdGeom.Xformable(prim):
                            prim_xform = UsdGeom.Xform(prim)
                            prim_xform.ClearXformOpOrder()
                            prim_xform.AddRotateXOp().Set(90)
                        else:
                            logger.debug(f"  → {prim.GetName()} is NOT xformable")

                stage.SetEditTarget(prev_target)
                ref_up_axis = "Z"
        except Exception as e:
            stage.SetEditTarget(Usd.EditTarget(stage.GetRootLayer()))
            logger.exception("default prim exception: %s", str(e))

        translate, _, self._bbox_sz, self._center = get_stage_bounds(ref_up_axis=ref_up_axis)

        prepare_message(
            msg="bounding box info",
            item_list=[
                f"translate: {translate}",
                f"center: {self._center}",
                f"bbounding box size: {self._bbox_sz}",
            ],
            logger=logger.debug,
        )

        self._scale = (1, 1, 1)
        if ref_up_axis == "Y":
            ground_translation = -np.asarray((0, 0, self._bbox_sz[1] / 2 + 0.51))
        else:
            ground_translation = -np.asarray((0, 0, self._bbox_sz[2] / 2 + 0.51))

        distance = np.sqrt(np.sum((self._bbox_sz / 2) ** 2)) * 2
        distance *= self.camera_fov_multiplier * self.base_camera_distance_multiplier

        with print_wrapper("camera set-up", print_after=False, logger=logger.debug):
            await self._set_camera(
                fov_multiplier=self.camera_fov_multiplier * self.base_fov_multiplier,
                clipping_range_max=max(2 * distance, 1000000),
            )

        with print_wrapper("ds stage init", print_after=False, logger=logger.debug):
            ground_scale = max(2 * distance, 1000000)
            for prim in self.config["prims"]:
                if not prim.get("enabled", True):
                    continue
                if prim["path"] != "/DeepSearch/CameraRig1/Ground":
                    continue
                prim["translation"] = tuple(ground_translation)
                prim["scale"] = tuple([ground_scale, ground_scale, 1])
                create_prim(stage, **prim)
            self.ground_moved = False

        with print_wrapper("time offset", print_after=False, logger=logger.debug):
            await wait_n_frames(self.app, n=10)
            await asyncio.sleep(1)

        self.apply_semantic_label(SEMANTIC_LABEL)

    async def _render_new_camera_views(self):
        """Render novel camera views."""
        stage = omni.usd.get_context().get_stage()

        render_products_paths = [str(self.camera.GetPath())]
        render_products = render_products_paths[0]

        segmentation_enabled = Sensors.semantic_segmentation.value in self.sensors or self.filter_by_segmentation
        async with SyntheticDataHelper(
            render_products=render_products,
            rgb=True,
            semantic_segmentation=segmentation_enabled,
            distance_to_camera=Sensors.distance_to_camera.value in self.sensors,
            distance_to_image_plane=Sensors.distance_to_image_plane.value in self.sensors,
            normals=Sensors.normals.value in self.sensors,
            camera_params=True,
            pointcloud=Sensors.pointcloud.value in self.sensors,
            bounding_box_2d_tight_fast=True,
            syntheticdata_kwargs={
                "width": self.camera_parameters.width,
                "height": self.camera_parameters.height,
            },
        ) as context:
            with print_wrapper("rendering new views", logger=logger.info):
                translation_offset = np.asarray(self._center / np.array(self._scale), dtype=np.float64)
                views = await asyncio.wait_for(
                    self._capture_viewpoints(
                        self.camera,
                        stage.GetPseudoRoot(),
                        rendering_context=context,
                        translate=(
                            translation_offset[0],
                            translation_offset[1],
                            translation_offset[2],
                        ),
                        scale=self._scale,
                        bbox_size=self._bbox_sz,
                        camera_distance_multiplier=self.camera_fov_multiplier * self.base_camera_distance_multiplier,
                    ),
                    timeout=self.rendering_timeout,
                )
                if views and Sensors.rgb.value in views and len(views[Sensors.rgb.value]) == 0:
                    logger.warning(
                        "No RGB frames captured on first pass for %s; retrying after a longer settle time",
                        self.omni_path,
                    )
                    await wait_n_frames(self.app, n=60)
                    await asyncio.sleep(1)
                    views = await asyncio.wait_for(
                        self._capture_viewpoints(
                            self.camera,
                            stage.GetPseudoRoot(),
                            rendering_context=context,
                            translate=(
                                translation_offset[0],
                                translation_offset[1],
                                translation_offset[2],
                            ),
                            scale=self._scale,
                            bbox_size=self._bbox_sz,
                            camera_distance_multiplier=self.camera_fov_multiplier
                            * self.base_camera_distance_multiplier,
                        ),
                        timeout=self.rendering_timeout,
                    )
        if views is None:
            return self._prepare_output_dict()
        else:
            return views

    @staticmethod
    def _merge_views(
        v1: Dict[str, Union[list, np.ndarray]], v2: Dict[str, Union[list, np.ndarray]]
    ) -> Dict[str, Union[list, np.ndarray]]:
        """Merge dictionaries from different camera views

        Args:
            v1 (Dict[str, Union[list, np.ndarray]]): view 1
            v2 (Dict[str, Union[list, np.ndarray]]): view 2

        Raises:
            ValueError: if sensor data is returned in unexpected form

        Returns:
            Dict[str, Union[list, np.ndarray]]: resulting merged dictionary of sensor data from both views
        """
        try:
            # merge lists coming from different sources
            for k, v in v2.items():
                v1[k] += v

            # for some fields do concatenation of results
            for k in [
                Sensors.rgb.value,
                Sensors.semantic_segmentation.value,
                Sensors.normals.value,
            ]:
                if k in v1:
                    if len(v1[k]) > 0:
                        logger.info("merging: %s: ", k)
                        v1[k] = np.concatenate(v1[k], axis=0)

            bbox_sensor = Sensors.bounding_box_2d_tight_fast.value
            if bbox_sensor in v1:
                v1[bbox_sensor] = [{k: asdict(v) for k, v in item.items()} for item in v1[bbox_sensor]]

            return v1
        except ValueError as e:
            if str(e).find("need at least one array to stack") >= 0:
                raise EmptyResponse(str(e)) from e
            else:
                raise e

    def apply_semantic_label(self, semantic_label: str):
        for prim in self._semantic_prim_list:
            for child in Usd.PrimRange(prim):
                if child.GetTypeName() in {"Material", "Camera", "Shader", "Scope"}:
                    continue
                attr = child.GetAttribute("semantics:class")
                if not attr:
                    attr = child.CreateAttribute("semantics:class", Sdf.ValueTypeNames.String)
                attr.Set(semantic_label)

    @staticmethod
    def _has_renderable_geometry(stage: Usd.Stage) -> bool:
        def is_visible_renderable(prim: Usd.Prim) -> bool:
            if not prim.IsA(UsdGeom.Imageable):
                return True
            imageable = UsdGeom.Imageable(prim)
            if imageable.ComputeVisibility(Usd.TimeCode.Default()) == UsdGeom.Tokens.invisible:
                return False
            purpose = imageable.GetPurposeAttr().Get()
            if purpose in {UsdGeom.Tokens.guide, UsdGeom.Tokens.proxy}:
                return False
            return True

        def has_nonempty_attr(attr) -> bool:
            try:
                value = attr.Get()
            except Exception:
                return False
            return value is not None and len(value) > 0

        def is_skeleton_bound(prim: Usd.Prim) -> bool:
            if prim.HasAPI(UsdSkel.BindingAPI):
                binding = UsdSkel.BindingAPI(prim)
                skel_rel = binding.GetSkeletonRel()
                if skel_rel and skel_rel.GetTargets():
                    return True
            return False

        for prim in stage.Traverse(Usd.TraverseInstanceProxies()):
            if prim.IsA(UsdGeom.Mesh):
                mesh = UsdGeom.Mesh(prim)
                if has_nonempty_attr(mesh.GetPointsAttr()):
                    return True
            if prim.IsA(UsdGeom.Points) and is_visible_renderable(prim):
                points = UsdGeom.Points(prim)
                if has_nonempty_attr(points.GetPointsAttr()):
                    return True
            if prim.IsA(UsdGeom.BasisCurves) and is_visible_renderable(prim):
                curves = UsdGeom.BasisCurves(prim)
                if has_nonempty_attr(curves.GetPointsAttr()) and has_nonempty_attr(curves.GetCurveVertexCountsAttr()):
                    return True
            if prim.IsA(UsdGeom.Curves) and is_visible_renderable(prim):
                curves = UsdGeom.Curves(prim)
                if has_nonempty_attr(curves.GetPointsAttr()) and has_nonempty_attr(curves.GetCurveVertexCountsAttr()):
                    return True
            if prim.IsA(UsdGeom.PointInstancer) and is_visible_renderable(prim):
                instancer = UsdGeom.PointInstancer(prim)
                try:
                    if has_nonempty_attr(instancer.GetProtoIndicesAttr()) and has_nonempty_attr(
                        instancer.GetPositionsAttr()
                    ):
                        return True
                except Exception:
                    pass
            for geom_type in (
                UsdGeom.Sphere,
                UsdGeom.Cube,
                UsdGeom.Cone,
                UsdGeom.Cylinder,
                UsdGeom.Capsule,
                UsdGeom.Plane,
            ):
                if prim.IsA(geom_type) and is_visible_renderable(prim):
                    return True
        return False

    @asynccontextmanager
    async def _prepare_scene(
        self,
        omni_path: str,
        camera_positions: List[CameraPosition],
        camera_parameters: CameraParameters,
        close_scene: bool = False,
        auth_dict: Optional[dict] = None,
        adjust_camera_multiplier: bool = True,
        semantic_label: str = SEMANTIC_LABEL,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Prepare the scene for retrieval of sensor data

        Args:
            omni_path (str): path to a USD file that needs to be loaded
            camera_positions (List[CameraPosition]): Camera positions that need to be rendered.
            camera_parameters (CameraParameters): Camera parameters.
            close_scene (bool, optional): If ``True`` will close the scene after data was collected.
                Defaults to False.
            auth_dict (Optional[dict], optional): Optional authentication dictionary. Defaults to None.
            adjust_camera_multiplier (bool, optional): If True - automatically adjust the camera
                settings to have the object of interest in the center and at right scale. Defaults to True.
            semantic_label (str, optional): Optional custom semantic label. Defaults to SEMANTIC_LABEL.

        Raises:
            NotImplementedError: in case some functionality is not supported
            LoadError: in case the asset load fails
            SceneInLiveMode: in case Scene is currently in live mode

        Yields:
            dict: scene content paths
        """
        # set some helper settings
        self.adjust_camera_multiplier = adjust_camera_multiplier
        self.camera_positions = camera_positions
        self.camera_parameters = camera_parameters

        prepare_message(
            msg="Rendering settings:",
            item_list=[
                f"automatically adjust camera multiplier:    {self.adjust_camera_multiplier}",
                f"Camera positions:                          {self.camera_positions}",
                f"Camera parameters:                         {self.camera_parameters}",
                f"Sensors:                                   {self.sensors}",
            ],
            logger=logger.info,
        )

        if self.token_based_authentication and omni_path.startswith("omniverse://"):
            host = omni.client.break_url(omni_path).host
            if auth_dict is not None:
                self.auth_tokens[host] = self.auth_tokens.get(host, {})
                self.auth_tokens[host].update(auth_dict)
            elif host not in self.auth_tokens:
                self.auth_tokens[host] = await get_auth_token_async(omni_path)

        self.omni_path = omni_path
        await self._ensure_environment_stage()

        try:
            if self._load_as_reference:
                await self._load_asset_as_reference(omni_path)
            else:
                await self._load_asset_sublayer(omni_path)
        except RuntimeError as e:
            carb.log_warn(f"Error loading scene: {str(e)}")
            raise LoadError(str(e)) from e

        await asyncio.sleep(1)

        # check that the live sync mode is turned off
        context = omni.usd.get_context()
        stage = context.get_stage()
        # TODO: this is the new functionality, but still need to figure out how to use it
        # omni.kit.usd.layers.LiveSyncing():

        for _ in range(2):
            await self.app.next_update_async()
        pt_list, _, pt_dict = get_stage_content()

        # Load payloads to hydrate scene geometry
        try:
            logger.info("Loading payloads for %s", omni_path)
            stage.Load()
            await wait_n_frames(self.app, n=10)
            bg = time.time()
            while True:
                _, files_loaded, total_files = context.get_stage_loading_status()
                if total_files == 0 or files_loaded >= total_files:
                    break
                if time.time() - bg > self.rendering_timeout:
                    logger.warning("Timed out waiting for payloads to load for %s", omni_path)
                    break
                await asyncio.sleep(0.5)
            await wait_n_frames(self.app, n=30)
        except Exception as e:
            logger.warning("Failed to load payloads for %s: %s", omni_path, str(e))

        self._scene_has_renderable_geometry = self._has_renderable_geometry(stage)

        if semantic_label is not None:
            prim_root = stage.GetPseudoRoot()
            if str(prim_root.GetPath()) == "/":
                self._semantic_prim_list = [
                    p for p in stage.GetPseudoRoot().GetChildren() if not str(p.GetPath()).startswith("/DeepSearch")
                ]
            else:
                self._semantic_prim_list = [prim_root]

            self.apply_semantic_label(semantic_label)

        try:
            yield dict(pt_list=pt_list, pt_dict=pt_dict)
        finally:
            if close_scene:
                self._clear_asset_sublayer()

    async def get_asset_renderings(
        self,
        omni_path: str,
        camera_positions: List[CameraPosition],
        camera_parameters: CameraParameters,
        close_scene: bool = True,
        auth_dict: Optional[dict] = None,
        adjust_camera_multiplier: bool = True,
        render_existing_views: bool = True,
        filter_by_segmentation: bool = False,
        sensors: Optional[List[str]] = None,
        **kwargs,
    ) -> Union[Dict[str, Union[list, np.ndarray]], str]:
        """Get asset renderings

        Args:
            omni_path (str): path to a USD file that needs to be loaded
            close_scene (bool, optional): If ``True`` will close the scene after data was collected.
                Defaults to False.
            auth_dict (Optional[dict], optional): Optional authenticaiton dictionary. Defaults to None.
            adjust_camera_multiplier (bool, optional): If True - automatically adjust the camera
                settings to have the object of interest in the center and at right scale. Defaults to True.
            render_existing_views (bool, optional): If ``True`` - additionally render view from
                cameras that exist in the scene. Defaults to True.
            camera_positions (List[CameraPosition]): Camera positions that need to be rendered.
            semantic_label (str, optional): Optional custom semantic label. Defaults to SEMANTIC_LABEL.
            camera_parameters (CameraParameters): Camera parameters overrides.


        Returns:
            dict: dictionary with scene renderings and segmentations
        """
        # configure segmentation gating
        self.filter_by_segmentation = filter_by_segmentation

        # make sure sensor parameter is initialized
        if sensors is None:
            self.sensors = DEFAULT_SENSOR_SET
        else:
            self.sensors = set(sensors)

        # prepare dictionaries to hold results
        custom_v = self._prepare_output_dict()
        scene_v = self._prepare_output_dict()

        async with self._prepare_scene(
            omni_path=omni_path,
            close_scene=close_scene,
            auth_dict=auth_dict,
            adjust_camera_multiplier=adjust_camera_multiplier,
            camera_positions=camera_positions,
            camera_parameters=camera_parameters,
        ) as scene:
            if not self._scene_has_renderable_geometry:
                logger.warning("Empty scene for %s", omni_path)
                return ""

            if render_existing_views:
                try:
                    scene_v = await self._render_existing_camera_views(list(scene["pt_dict"].items()))
                except Exception as e:
                    logger.exception("Error rendering existing camera views: %s", str(e))

            stage = omni.usd.get_context().get_stage()
            await self._setup_environment(stage)

            try:
                custom_v = await self._render_new_camera_views()
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"rendering timeout (longer than {self.rendering_timeout})") from e
            except EmptyResponse:
                msg = f"Empty scene for {omni_path}"
                carb.log_warn(msg)
                logger.warning(msg)
            except Exception as e:
                logger.exception("Error rendering novel camera views: %s", str(e))

            if adjust_camera_multiplier and Sensors.rgb.value in custom_v and len(custom_v[Sensors.rgb.value]) == 0:
                logger.warning(
                    "No RGB frames captured for %s; retrying without camera auto-fit",
                    omni_path,
                )
                prev_adjust = self.adjust_camera_multiplier
                self.adjust_camera_multiplier = False
                try:
                    custom_v = await self._render_new_camera_views()
                except Exception as e:
                    logger.exception("Fallback rendering failed: %s", str(e))
                finally:
                    self.adjust_camera_multiplier = prev_adjust

        # merge and return results from different views
        try:
            merged = self._merge_views(scene_v, custom_v)
        except EmptyResponse:
            return ""

        if _is_rgb_empty(merged.get(Sensors.rgb.value)):
            logger.warning(
                "No RGB frames in merged output; trying RGB-only fallback for %s",
                omni_path,
            )
            try:
                async with _rgb_only_fallback_settings(self):
                    for attempt in range(3):
                        await wait_n_frames(self.app, n=60 * (attempt + 1))
                        await asyncio.sleep(1)
                        fallback = await self._render_new_camera_views()
                        if not _is_rgb_empty(fallback.get(Sensors.rgb.value)):
                            return fallback
            except Exception as e:
                logger.exception("RGB-only fallback failed: %s", str(e))

        if _is_rgb_empty(merged.get(Sensors.rgb.value)):
            logger.warning(
                "RGB-only fallback still empty; reopening stage and retrying for %s",
                omni_path,
            )
            try:
                async with _rgb_only_fallback_settings(self):
                    async with self._prepare_scene(
                        omni_path=omni_path,
                        close_scene=close_scene,
                        auth_dict=auth_dict,
                        adjust_camera_multiplier=False,
                        camera_positions=camera_positions,
                        camera_parameters=camera_parameters,
                    ):
                        if not self._scene_has_renderable_geometry:
                            msg = f"Empty scene for {omni_path}"
                            carb.log_warn(msg)
                            logger.warning(msg)
                            return ""
                        stage = omni.usd.get_context().get_stage()
                        await self._setup_environment(stage)
                        retry_views = await self._render_new_camera_views()
                    try:
                        merged_retry = self._merge_views(self._prepare_output_dict(), retry_views)
                    except EmptyResponse:
                        merged_retry = {}
                    if not _is_rgb_empty(merged_retry.get(Sensors.rgb.value)):
                        return merged_retry
            except Exception as e:
                logger.exception("Stage-reopen fallback failed: %s", str(e))

        return merged
