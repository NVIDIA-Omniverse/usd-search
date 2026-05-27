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

# standard packages
import asyncio
import time
import uuid
from ast import literal_eval as make_tuple
from typing import Any, Dict, List, Optional, Union

# import syntheticdata functionality
import carb

# third party modules
import numpy as np
import omni.kit.app
import omni.usd
from omni.kit.hydra_texture import create_hydra_texture
from omni.syntheticdata import sensors
from omni.syntheticdata._syntheticdata import SensorType as SdSensorType

from . import SEMANTIC_LABEL, IncompleteData, logger
from .data import BBox, ModeType, Sensors
from .exceptions import DataRetrievalError, SyntheticDataStepTimeout

# local / proprietary modules
from .log_utils import prepare_message, print_wrapper


def _normalize_label_map(label_map: Optional[Dict[Any, Any]]) -> Dict[Any, str]:
    if not label_map:
        return {}
    normalized: Dict[Any, str] = {}
    for key, value in label_map.items():
        label = value
        if isinstance(value, dict) and "class" in value:
            label = value["class"]
        normalized[key] = str(label)
    return normalized


def _build_segmentation_result(
    seg_data: np.ndarray,
    label_map: Optional[Dict[Any, Any]] = None,
    default_label: str = SEMANTIC_LABEL,
) -> Dict[str, List[np.ndarray]]:
    result: Dict[str, List[np.ndarray]] = {}
    normalized_map = _normalize_label_map(label_map)

    if normalized_map:
        for key, label in normalized_map.items():
            try:
                key_value = make_tuple(key) if isinstance(key, str) else key
            except (SyntaxError, ValueError):
                key_value = key

            if isinstance(key_value, (tuple, list, np.ndarray)) and seg_data.ndim == 3:
                mask = np.all(seg_data == np.asarray(key_value), axis=-1)
            else:
                try:
                    mask = seg_data == int(key_value)
                except (TypeError, ValueError):
                    continue

            if np.any(mask):
                result[label] = result.get(label, []) + [mask]
        return result

    if seg_data.ndim >= 2:
        mask = seg_data != 0
        if np.any(mask):
            result[default_label] = [mask]
    return result


def get_semantic_segmentation_for_class(
    input_list: List[Any],
    label_map: Optional[Dict[Any, Any]] = None,
    default_label: str = SEMANTIC_LABEL,
) -> List[Dict[str, List[np.ndarray]]]:
    res_list: List[Dict[str, Any]] = []
    for seg_data in input_list:
        if isinstance(seg_data, dict):
            if "data" in seg_data:
                res_list.append(
                    _build_segmentation_result(
                        seg_data["data"],
                        seg_data.get("idToLabels", label_map),
                        default_label=default_label,
                    )
                )
                continue

            for _, annotator_content in seg_data.items():
                res_list.append(
                    _build_segmentation_result(
                        annotator_content["data"],
                        annotator_content.get("idToLabels", label_map),
                        default_label=default_label,
                    )
                )
            continue

        if not isinstance(seg_data, np.ndarray):
            logger.warning(f"Invalid segmentation data format: {type(seg_data)}")
            res_list.append({})
            continue

        res_list.append(_build_segmentation_result(seg_data, label_map, default_label=default_label))

    return res_list


def _get_bbox_field(entry: np.void, names: tuple, *candidates: str) -> float:
    for name in candidates:
        if name in names:
            return float(entry[name])
    raise KeyError(f"Missing bbox field. Tried: {candidates}")


def _get_bbox_label(
    entry: np.void,
    names: tuple,
    label_map: Optional[Dict[Any, Any]] = None,
    default_label: str = SEMANTIC_LABEL,
) -> Optional[str]:
    normalized_map = _normalize_label_map(label_map)

    if "semanticLabel" in names:
        return str(entry["semanticLabel"])
    if "label" in names:
        return str(entry["label"])

    if "semanticId" in names:
        semantic_id = int(entry["semanticId"])
        if semantic_id == 0:
            return None
        if semantic_id in normalized_map:
            return normalized_map[semantic_id]
        return default_label

    return default_label


def get_bbounding_box_for_class(
    input_list: List[dict],
    mode: ModeType = ModeType.combined,
    label_map: Optional[Dict[Any, Any]] = None,
    default_label: str = SEMANTIC_LABEL,
) -> List[dict]:
    res_list: List[dict] = []
    for bbox_data in input_list:
        if isinstance(bbox_data, dict):
            result = {}
            for _, annotator_content in bbox_data.items():
                for id, label in annotator_content["idToLabels"].items():
                    result[label["class"]] = np.stack(
                        [
                            np.asarray([i["x_min"], i["y_min"], i["x_max"], i["y_max"]])
                            for i in annotator_content["data"]
                            if str(i[0]) == str(id)
                        ],
                        axis=0,
                    )
                if mode == ModeType.combined:
                    for label in result:
                        result[label] = BBox(
                            xmin=np.min(result[label][:, 0]),
                            ymin=np.min(result[label][:, 1]),
                            xmax=np.max(result[label][:, 2]),
                            ymax=np.max(result[label][:, 3]),
                        )
                else:
                    raise NotImplementedError(f"Bounding Box Mode: {mode} is not supported")
                res_list.append(result)
            continue

        result = {}
        if not isinstance(bbox_data, np.ndarray) or bbox_data.dtype.names is None:
            logger.warning(f"Invalid bbox data format: {type(bbox_data)}")
            res_list.append(result)
            continue

        names = bbox_data.dtype.names
        for bbox_entry in bbox_data:
            label = _get_bbox_label(bbox_entry, names, label_map=label_map, default_label=default_label)
            if not label:
                continue
            result.setdefault(label, [])

            x_min = _get_bbox_field(bbox_entry, names, "x_min", "xmin", "xMin")
            y_min = _get_bbox_field(bbox_entry, names, "y_min", "ymin", "yMin")
            x_max = _get_bbox_field(bbox_entry, names, "x_max", "xmax", "xMax")
            y_max = _get_bbox_field(bbox_entry, names, "y_max", "ymax", "yMax")
            result[label].append([x_min, y_min, x_max, y_max])

        if mode == ModeType.combined:
            for label in result:
                if len(result[label]) > 0:
                    bbox_array = np.array(result[label])
                    result[label] = BBox(
                        xmin=np.min(bbox_array[:, 0]),
                        ymin=np.min(bbox_array[:, 1]),
                        xmax=np.max(bbox_array[:, 2]),
                        ymax=np.max(bbox_array[:, 3]),
                    )
        else:
            raise NotImplementedError(f"Bounding Box Mode: {mode} is not supported")

        res_list.append(result)
    return res_list


def get_rgb_data(rgb_info: Union[dict, np.ndarray], content_field: str = "data") -> np.ndarray:
    if isinstance(rgb_info, dict):
        return rgb_info[content_field]
    return rgb_info


def _stack_sensor_data(data: Any) -> np.ndarray:
    """Stack sensor data into array format."""
    return np.stack(data, axis=0) if isinstance(data, list) else np.array([data])


def postprocess_results(content: Dict[str, Any], label_map: Optional[Dict[Any, Any]] = None) -> Dict[str, Any]:
    processed_content = {}

    if Sensors.rgb.name in content:
        rgb_data = content[Sensors.rgb.name]
        if isinstance(rgb_data, list):
            processed_content[Sensors.rgb.value] = np.stack([get_rgb_data(d) for d in rgb_data], axis=0)
        else:
            processed_content[Sensors.rgb.value] = np.array([get_rgb_data(rgb_data)])

    for sensor in (
        Sensors.distance_to_camera,
        Sensors.distance_to_image_plane,
        Sensors.normals,
    ):
        if sensor.name in content:
            processed_content[sensor.value] = _stack_sensor_data(content[sensor.name])

    for sensor in (Sensors.camera_params, Sensors.pointcloud):
        if sensor.name in content:
            processed_content[sensor.value] = content[sensor.name]

    if Sensors.semantic_segmentation.name in content:
        seg_data = content[Sensors.semantic_segmentation.name]
        seg_list = seg_data if isinstance(seg_data, list) else [seg_data]
        processed_content[Sensors.semantic_segmentation.value] = get_semantic_segmentation_for_class(
            seg_list, label_map=label_map
        )

    if Sensors.bounding_box_2d_tight_fast.name in content:
        bbox_data = content[Sensors.bounding_box_2d_tight_fast.name]
        bbox_list = bbox_data if isinstance(bbox_data, list) else [bbox_data]
        processed_content[Sensors.bounding_box_2d_tight_fast.value] = get_bbounding_box_for_class(
            bbox_list, label_map=label_map
        )

    return processed_content


class HydraTextureViewportAdapter:
    def __init__(self, hydra_texture, render_products):
        self._hydra_texture = hydra_texture
        self._render_products = list(render_products or [])
        self._viewport_handle = -1
        self._frame_info_cache = None
        self._event_sub = None
        self._setup_events()

    def _setup_events(self):
        import carb.eventdispatcher
        import omni.hydratexture

        try:
            event_name = omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED
        except AttributeError:
            # Some Kit builds don't expose this event; fall back to no event subscription.
            if hasattr(self._hydra_texture, "get_viewport_handle"):
                try:
                    self._viewport_handle = self._hydra_texture.get_viewport_handle() or -1
                except Exception:
                    self._viewport_handle = -1
            logger.warning("HydraTexture event API unavailable; viewport handle updates disabled.")
            return

        def on_event(event):
            viewport_handle = event.get("viewport_handle")
            if viewport_handle is not None:
                self._viewport_handle = viewport_handle
            else:
                self._viewport_handle = -1
            self._frame_info_cache = None

        ed = carb.eventdispatcher.get_eventdispatcher()
        self._event_sub = ed.observe_event(
            observer_name="HydraTextureViewportAdapter",
            event_name=event_name,
            on_event=on_event,
            filter=self._hydra_texture.get_event_key(),
        )

    @property
    def frame_info(self):
        if self._viewport_handle == -1 and hasattr(self._hydra_texture, "get_viewport_handle"):
            try:
                self._viewport_handle = self._hydra_texture.get_viewport_handle() or -1
            except Exception:
                self._viewport_handle = -1
        if self._frame_info_cache is None:
            self._frame_info_cache = {"viewport_handle": self._viewport_handle}
        return self._frame_info_cache

    @property
    def render_product_path(self):
        if self._hydra_texture is not None:
            try:
                hydra_path = self._hydra_texture.get_render_product_path()
                if hydra_path:
                    return hydra_path
            except Exception:
                pass
        if self._render_products:
            return self._render_products[0]
        return None

    def get_render_product_path(self):
        return self.render_product_path

    def get_render_product_paths(self):
        primary = self.render_product_path
        if primary:
            return [primary]
        return list(self._render_products)

    def get_frame_info(self):
        return self.frame_info

    def __getattr__(self, name):
        return getattr(self._hydra_texture, name)


_DEFAULT_SENSOR_UPDATES = 10


class SyntheticDataHelper:
    _SENSOR_TYPE_MAP = {
        "rgb": SdSensorType.Rgb,
        "semantic_segmentation": SdSensorType.SemanticSegmentation,
        "instance_segmentation": SdSensorType.InstanceSegmentation,
        "distance_to_camera": SdSensorType.DistanceToCamera,
        "distance_to_image_plane": SdSensorType.DistanceToImagePlane,
        "normals": SdSensorType.Normal,
        "bounding_box_2d_tight": SdSensorType.BoundingBox2DTight,
    }

    def __init__(
        self,
        render_products: List,
        rgb: bool = True,
        semantic_segmentation: bool = False,
        instance_segmentation: bool = False,
        distance_to_camera: bool = False,
        distance_to_image_plane: bool = False,
        normals: bool = False,
        camera_params: bool = False,
        pointcloud: bool = False,
        bounding_box_2d_tight_fast: bool = False,
        max_attempts: int = 3,
        step_timeout: float = 5,
        syntheticdata_kwargs: Dict | None = None,
    ) -> None:
        self.render_products = render_products
        self.verify_render_products()
        self._rgb = rgb
        self._max_attempts = max_attempts
        self._semantic_segmentation = semantic_segmentation
        self._instance_segmentation = instance_segmentation
        self._distance_to_camera = distance_to_camera
        self._distance_to_image_plane = distance_to_image_plane
        self._normals = normals
        self._camera_params = camera_params
        self._pointcloud = pointcloud
        self._bounding_box_2d_tight_fast = bounding_box_2d_tight_fast
        self._step_timeout = step_timeout
        self._syntheticdata_kwargs = syntheticdata_kwargs if syntheticdata_kwargs else {}
        self._data_raw = None
        self._wait_sim_frame = True

        self._hydra_texture = None
        self._viewport = None
        self.sensors: List[Dict[str, Any]] = []

        self._num_sensor_updates = _DEFAULT_SENSOR_UPDATES

    def verify_render_products(self) -> None:
        if not isinstance(self.render_products, list):
            self.render_products = [self.render_products]

    def _get_enabled_sensors(self) -> list:
        enabled = []
        if self._rgb:
            enabled.append(self._SENSOR_TYPE_MAP["rgb"])
        if self._semantic_segmentation:
            enabled.append(self._SENSOR_TYPE_MAP["semantic_segmentation"])
        if self._instance_segmentation:
            enabled.append(self._SENSOR_TYPE_MAP["instance_segmentation"])
        if self._distance_to_camera:
            enabled.append(self._SENSOR_TYPE_MAP["distance_to_camera"])
        if self._distance_to_image_plane:
            enabled.append(self._SENSOR_TYPE_MAP["distance_to_image_plane"])
        if self._normals:
            enabled.append(self._SENSOR_TYPE_MAP["normals"])
        if self._bounding_box_2d_tight_fast:
            enabled.append(self._SENSOR_TYPE_MAP["bounding_box_2d_tight"])
        return enabled

    async def __aenter__(self) -> "SyntheticDataHelper":
        settings = carb.settings.get_settings()
        render_product = self.render_products[0]

        if hasattr(render_product, "get_camera_path"):
            camera_path = render_product.get_camera_path()
        elif hasattr(render_product, "camera_path"):
            camera_path = render_product.camera_path
        elif isinstance(render_product, str):
            camera_path = render_product
        else:
            camera_path = str(render_product)

        stage = omni.usd.get_context().get_stage()
        if not stage:
            raise RuntimeError("No valid USD stage for syntheticdata")
        camera_prim = stage.GetPrimAtPath(camera_path)
        if not camera_prim or not camera_prim.IsValid():
            raise RuntimeError(f"Camera prim does not exist or is invalid: {camera_path}")

        if hasattr(render_product, "get_resolution"):
            width, height = render_product.get_resolution()
        elif hasattr(render_product, "resolution"):
            width, height = render_product.resolution
        else:
            width = self._syntheticdata_kwargs.get("width", 512)
            height = self._syntheticdata_kwargs.get("height", 512)

        logger.debug(f"Creating HydraTexture: camera={camera_path}, resolution={width}x{height}")

        unique_name = f"deepsearch_rendering_{uuid.uuid4().hex[:8]}"
        self._hydra_texture = create_hydra_texture(
            name=unique_name,
            width=width,
            height=height,
            usd_context_name="",
            usd_camera_path=camera_path,
            hydra_engine_name="rtx",
            is_async=settings.get("/app/asyncRendering"),
            is_async_low_latency=False,
            hydra_tick_rate=60,
            engine_creation_flags=0,
            device_mask=0,
        )

        if not self._hydra_texture:
            raise RuntimeError(f"Failed to create HydraTexture for camera: {camera_path}")

        app = omni.kit.app.get_app()
        for _ in range(20):
            await app.next_update_async()
        await asyncio.sleep(0.5)

        render_product_path = None
        if hasattr(self._hydra_texture, "get_render_product_path"):
            for attempt in range(100):
                try:
                    render_product_path = self._hydra_texture.get_render_product_path()
                except Exception:
                    render_product_path = None
                if render_product_path:
                    break
                await asyncio.sleep(0.1)
                if attempt % 3 == 0:
                    await app.next_update_async()

        if not render_product_path:
            raise RuntimeError(f"Failed to initialize render product for camera: {camera_path}")

        self._viewport = HydraTextureViewportAdapter(self._hydra_texture, [render_product_path])

        if enabled_sensors := self._get_enabled_sensors():
            sensors.enable_sensors(self._viewport, enabled_sensors)

        for _ in range(10):
            await app.next_update_async()
        await asyncio.sleep(0.2)

        return self

    async def __aexit__(self, *args, **kwargs) -> None:
        with print_wrapper("syntheticdata cleanup", logger=logger.debug):
            if self._viewport:
                try:
                    if enabled_sensors := self._get_enabled_sensors():
                        sensors.disable_sensors(self._viewport, enabled_sensors)
                except Exception as e:
                    logger.warning(f"Error disabling sensors: {e}")

            if self._hydra_texture:
                try:
                    context = omni.usd.get_context()
                    if hasattr(self._hydra_texture, "get_viewport_handle"):
                        if viewport_handle := self._hydra_texture.get_viewport_handle():
                            context.destroy_viewport(viewport_handle)
                    if hasattr(self._hydra_texture, "destroy"):
                        self._hydra_texture.destroy()
                    elif hasattr(self._hydra_texture, "shutdown"):
                        self._hydra_texture.shutdown()
                except Exception as e:
                    logger.warning(f"Error destroying hydra texture: {e}")

            self._hydra_texture = None
            self._viewport = None

            try:
                app = omni.kit.app.get_app()
                for _ in range(5):
                    await app.next_update_async()
            except Exception:
                pass

    async def get_data(self) -> Dict[str, Any]:
        for attempt in range(self._max_attempts):
            try:
                for _ in range(self._num_sensor_updates):
                    await asyncio.wait_for(
                        sensors.next_sensor_data_async(
                            viewport=self._viewport,
                            waitSimFrame=self._wait_sim_frame,
                        ),
                        timeout=self._step_timeout,
                    )

                captured_data = {}
                label_map = None

                sensor_captures = [
                    (self._rgb, sensors.get_rgb, Sensors.rgb),
                    (
                        self._semantic_segmentation,
                        sensors.get_semantic_segmentation,
                        Sensors.semantic_segmentation,
                    ),
                    (
                        self._distance_to_camera,
                        sensors.get_distance_to_camera,
                        Sensors.distance_to_camera,
                    ),
                    (
                        self._distance_to_image_plane,
                        sensors.get_distance_to_image_plane,
                        Sensors.distance_to_image_plane,
                    ),
                    (self._normals, sensors.get_normals, Sensors.normals),
                    (
                        self._bounding_box_2d_tight_fast,
                        sensors.get_bounding_box_2d_tight,
                        Sensors.bounding_box_2d_tight_fast,
                    ),
                ]
                for enabled, getter, sensor in sensor_captures:
                    if enabled:
                        data = getter(self._viewport)
                        if data is not None:
                            captured_data[sensor.name] = [data.copy()]

                if self._camera_params:
                    captured_data[Sensors.camera_params.name] = [{}]

                with print_wrapper("postprocess syntheticdata", logger=logger.debug):
                    self._data_raw = captured_data
                    return postprocess_results(captured_data, label_map=label_map)

            except asyncio.TimeoutError:
                logger.warning(f"Sensor capture timeout on attempt {attempt + 1}/{self._max_attempts}")
                if attempt == self._max_attempts - 1:
                    raise SyntheticDataStepTimeout(f"Sensor capture timeout after {self._max_attempts} attempts")
            except Exception as e:
                message = str(e)
                if "waiting for next frame failed" in message:
                    if self._wait_sim_frame:
                        logger.warning("SyntheticData next frame failed; disabling waitSimFrame and retrying.")
                        self._wait_sim_frame = False
                    else:
                        logger.warning("SyntheticData next frame failed with waitSimFrame disabled; retrying.")
                    continue
                logger.warning(
                    "SyntheticData error on attempt %s/%s: %s",
                    attempt + 1,
                    self._max_attempts,
                    message,
                )
                if attempt == self._max_attempts - 1:
                    raise DataRetrievalError(message)

        raise DataRetrievalError(f"Reached maximum number of attempts: {self._max_attempts}")

    @staticmethod
    def assert_data_field(data: dict, field: Sensors, verify_name: bool = True) -> None:
        if verify_name:
            assert field.name in data, f"{field.name} is missing"
        else:
            assert field.value in data, f"{field.value} is missing"

    def verify_data(self, data: dict, verify_name: bool = True) -> None:
        """Verify that extracted data contains all the required fields

        Args:
            data (dict): extracted data, content of which need to be verified
            verify_name (bool): if True - checks for the name field in Sensors type, otherwise the value
        """
        sensor_checks = [
            (self._rgb, Sensors.rgb),
            (self._semantic_segmentation, Sensors.semantic_segmentation),
            (self._distance_to_camera, Sensors.distance_to_camera),
            (self._distance_to_image_plane, Sensors.distance_to_image_plane),
            (self._normals, Sensors.normals),
            (self._camera_params, Sensors.camera_params),
            (self._pointcloud, Sensors.pointcloud),
            (self._bounding_box_2d_tight_fast, Sensors.bounding_box_2d_tight_fast),
        ]
        for enabled, sensor in sensor_checks:
            if enabled:
                self.assert_data_field(data, sensor, verify_name)

        # check completeness
        missing_data_content = [
            f"{k} has missing data: {len(v)} vs {len(self.render_products)}"
            for k, v in data.items()
            if len(v) < len(self.render_products)
        ]
        if missing_data_content:
            raise IncompleteData(prepare_message(msg="missing data", item_list=missing_data_content))
