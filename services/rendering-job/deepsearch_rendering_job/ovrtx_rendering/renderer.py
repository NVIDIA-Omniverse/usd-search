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

import logging
import os
import time
from functools import partial
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np
import ovrtx
from numpy.typing import NDArray

from ..exceptions import LoadError, TimeoutError
from .scene import (
    _ASSET_PRIM_PATH,
    ANNOTATOR_ONLY_SENSORS,
    CAMERA_CLIPPING_RANGE,
    CAMERA_PATH,
    CAMERA_TRANSFORM_ATTR,
    DEFAULT_SENSOR_SET,
    DEPTH_DERIVED_SENSORS,
    ENVIRONMENT_PRIM_PREFIX,
    FRAMING_BACKOFF,
    FRAMING_ITERATIONS,
    FRAMING_MAX_BACKOFFS,
    FRAMING_PROBE_VIEWS,
    GEOMETRY_PRIM_TYPES,
    GROUND_PATH,
    KIT_VIEWPORT_CAMERAS,
    MASK_PRODUCT_PATH,
    MASK_RENDER_VAR,
    RENDER_PRODUCT_PATH,
    RENDER_SCOPE_PREFIX,
    SEMANTIC_LABEL,
    SENSOR_RENDER_VAR_MAP,
    WORLD_MATRIX_ATTR,
    Sensors,
    asset_prim_path,
    bbox_from_mask,
    bbox_touches_border,
    build_camera_transform,
    build_ground_transform,
    build_scene_root_usda,
    camera_intrinsics,
    compute_camera_distance,
    ground_top_z,
    segmentation_from_depth,
    solve_center_offset,
    solve_distance,
    top_level_roots,
    y_up_to_z_up_matrix,
)

logger = logging.getLogger(__name__)

AZIMUTHS = [45, 135, 225, 315]
ELEVATIONS = [60, 45]
DEFAULT_FOV = 60.0
DEFAULT_WIDTH = 448
DEFAULT_HEIGHT = 448
DEFAULT_DOMELIGHT_SHADE = 255
DEFAULT_DOMELIGHT_INTENSITY = 1500.0
DEFAULT_CAMERA_DISTANCE_MULTIPLIER = 1.0
DEFAULT_CAMERA_FOV_MULTIPLIER = 4
DEFAULT_BASE_FOV_MULTIPLIER = 0.5
# Share of an asset's remaining render budget the scene cameras may use; the orbit views get the rest.
SCENE_CAMERA_BUDGET_FRACTION = 0.5


class CameraPosition:
    __slots__ = ("az", "el")

    def __init__(self, az: float, el: float):
        self.az = az
        self.el = el

    def __repr__(self) -> str:
        return f"[az: {self.az}; el: {self.el}]"


class CameraParameters:
    __slots__ = ("width", "height")

    def __init__(self, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT):
        self.width = width
        self.height = height


class OvrtxViewRenderer:
    """In-process USD renderer powered by ovrtx.

    Replaces the Kit subprocess + extension pipeline with a single renderer
    that loads USD assets, sets up a standard environment (dome light, camera
    rig, ground plane), and captures images from multiple viewpoints.

    The ground only appears in the colour output: depth, normals and the
    depth-derived mask/bbox are captured in a second pass with it hidden, so they
    describe the asset alone.

    Supports multiple sensor outputs matching the Kit SyntheticData contract:
    RGB, depth, linear depth, and normals are backed by ovrtx render
    variables.  Semantic segmentation and 2D bounding boxes are derived
    from the depth buffer (foreground pixels = finite positive depth).
    Sensors that relied on Kit-specific annotators with no depth-based
    fallback (pointcloud) are silently excluded from the output.

    Like Kit, the camera is auto-framed per asset: the orbit pivot is shifted so the
    asset's mask is centred and the distance is set so it fills
    ``FRAMING_TARGET_FILL`` of the view (see :meth:`_auto_frame`).
    """

    def __init__(
        self,
        fov: float = DEFAULT_FOV,
        domelight_shade: int = DEFAULT_DOMELIGHT_SHADE,
        domelight_intensity: float = DEFAULT_DOMELIGHT_INTENSITY,
        base_camera_distance_multiplier: float = DEFAULT_CAMERA_DISTANCE_MULTIPLIER,
        camera_fov_multiplier: float = DEFAULT_CAMERA_FOV_MULTIPLIER,
        base_fov_multiplier: float = DEFAULT_BASE_FOV_MULTIPLIER,
        load_asset_as_reference: bool = (os.getenv("LOAD_ASSET_AS_REFERENCE", "True").lower() in ("true", "1")),
        ground_plane: bool = (os.getenv("RENDER_GROUND_PLANE", "True").lower() in ("true", "1")),
        adjust_framing: bool = (os.getenv("RENDER_ADJUST_FRAMING", "True").lower() in ("true", "1")),
        sync_mode: bool = True,
    ):
        self._fov = fov
        self._domelight_shade = domelight_shade
        self._domelight_intensity = domelight_intensity
        self._base_camera_distance_multiplier = base_camera_distance_multiplier
        self._camera_fov_multiplier = camera_fov_multiplier
        self._base_fov_multiplier = base_fov_multiplier
        self._load_as_reference = load_asset_as_reference
        self._ground_plane = ground_plane
        self._ground_visible = ground_plane
        self._ground_top: Optional[float] = None
        self._adjust_framing = adjust_framing
        self._sync_mode = sync_mode

        self._renderer: Optional[ovrtx.Renderer] = None
        self._current_asset_path: Optional[str] = None
        self._active_sensors: Set[str] = DEFAULT_SENSOR_SET

    def _ensure_renderer(self) -> ovrtx.Renderer:
        if self._renderer is None:
            datastore_cache = None
            shader_cache_dir = os.getenv("OVRTX_SHADER_CACHE_DIR")
            if shader_cache_dir:
                # UJITSO's local backend; without this ovrtx compiles shaders into a
                # path baked into the package install tree instead of a mounted volume.
                datastore_cache = f"local://{shader_cache_dir}"
            config = ovrtx.RendererConfig(sync_mode=self._sync_mode, datastore_cache=datastore_cache)
            self._renderer = ovrtx.Renderer(config=config)
            logger.info("ovrtx renderer initialized (version %s)", self._renderer.version)
        return self._renderer

    def _load_scene(
        self,
        usd_path: str,
        width: int,
        height: int,
        force_full_stage: bool = False,
        default_material_roots: Optional[List[str]] = None,
    ) -> None:
        """Compose the runtime stage: root (environment + render product) + asset.

        ovrtx expects cameras and render products to be authored in the root
        layer, so the environment and render product are composed inline via
        ``open_usd_from_string``.  The asset is either referenced by its
        ``defaultPrim`` (reference mode) or sublayered as a full stage
        (full-stage mode), which strips no embedded content.

        Reference mode applies to remote URLs too: a full-stage load also composes
        the asset's sibling root prims, e.g. a SimReady ``/Tagging/ThumbRig`` whose
        studio backdrop and dome light would swamp the framing.
        """
        renderer = self._ensure_renderer()

        as_reference = self._load_as_reference and not force_full_stage
        # A root-layer binding over /Asset would block add_usd_reference there, so reference inline.
        inline_reference = as_reference and _ASSET_PRIM_PATH in (default_material_roots or [])
        root_usda = build_scene_root_usda(
            domelight_intensity=self._domelight_intensity,
            fov=self._fov,
            fov_multiplier=self._camera_fov_multiplier * self._base_fov_multiplier,
            width=width,
            height=height,
            domelight_shade=self._domelight_shade,
            requested_sensors=self._active_sensors,
            asset_sublayer=None if as_reference else usd_path,
            default_material_roots=default_material_roots,
            ground_plane=self._ground_plane,
            mask_product=self._adjust_framing,
            asset_reference=usd_path if inline_reference else None,
        )
        self._ground_visible = self._ground_plane
        self._ground_top = None
        try:
            renderer.open_usd_from_string(root_usda)
            if inline_reference:
                logger.info("Asset loaded as inline reference: %s", usd_path)
            elif as_reference:
                renderer.add_usd_reference(usd_path, _ASSET_PRIM_PATH)
                logger.info("Asset loaded as reference: %s", usd_path)
            else:
                logger.info("Asset loaded as full stage: %s", usd_path)
        except RuntimeError as exc:
            raise LoadError(f"Failed to open asset {usd_path}: {exc}") from exc

        self._current_asset_path = usd_path
        logger.debug("Scene composed (%dx%d)", width, height)

    def _find_geometry_prims(self) -> List[str]:
        """Return paths of renderable geometry prims, excluding our environment."""
        renderer = self._ensure_renderer()
        result = renderer.query_prims(
            require_any=[(ovrtx.FilterKind.PRIM_TYPE, prim_type) for prim_type in GEOMETRY_PRIM_TYPES],
            attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
        )
        return [
            prim_path
            for prim_path in result
            if not (prim_path.startswith(ENVIRONMENT_PRIM_PREFIX) or prim_path.startswith(RENDER_SCOPE_PREFIX))
        ]

    def _find_scene_cameras(self) -> List[str]:
        """Return paths of the asset's own cameras, excluding ours and Kit's viewport cameras."""
        renderer = self._ensure_renderer()
        result = renderer.query_prims(
            require_any=[(ovrtx.FilterKind.PRIM_TYPE, "Camera")],
            attribute_filter_mode=ovrtx.AttributeFilterMode.NONE,
        )
        # Sorted: ovrtx returns prims in no stable order, and the first view is the asset's thumbnail.
        return sorted(
            prim_path
            for prim_path in result
            if not (prim_path.startswith(ENVIRONMENT_PRIM_PREFIX) or prim_path.startswith(RENDER_SCOPE_PREFIX))
            and prim_path.rsplit("/", 1)[-1] not in KIT_VIEWPORT_CAMERAS
        )

    def _compute_world_bounds(self, prim_paths: List[str]) -> Tuple[NDArray, NDArray]:
        """Compute an axis-aligned world bounding box (size, center) from prims.

        Reads the runtime-populated ``_worldExtent`` attribute (one
        ``[minX, minY, minZ, maxX, maxY, maxZ]`` row per prim) and aggregates.
        """
        renderer = self._ensure_renderer()
        extents = np.asarray(np.from_dlpack(renderer.read_attribute("_worldExtent", prim_paths)), dtype=np.float64)
        if extents.ndim == 1:
            extents = extents.reshape(1, -1)
        mins = extents[:, 0:3].min(axis=0)
        maxs = extents[:, 3:6].max(axis=0)
        center = (mins + maxs) / 2.0
        box_size = maxs - mins
        return box_size, center

    def _orient_to_world_up(self, up_axis: Optional[str], geometry_prims: List[str]) -> None:
        """Rotate a Y-up asset onto the Z-up world (Kit up-axis parity); a no-op unless the authored upAxis is Y."""
        if up_axis != "Y":
            return
        roots = top_level_roots(geometry_prims)
        if not roots:
            return
        renderer = self._ensure_renderer()
        rotation = np.asarray(y_up_to_z_up_matrix(), dtype=np.float64).reshape(1, 4, 4).repeat(len(roots), axis=0)
        renderer.write_attribute(roots, CAMERA_TRANSFORM_ATTR, rotation)
        self._warm_up(n_frames=2)
        logger.info("Normalized Y-up asset to Z-up (rotated %s +90 about X)", roots)

    def _set_camera_transform(self, transform: NDArray) -> None:
        renderer = self._ensure_renderer()
        xform_array = np.asarray(transform, dtype=np.float64).reshape(1, 4, 4)
        renderer.write_attribute(
            [CAMERA_PATH],
            CAMERA_TRANSFORM_ATTR,
            xform_array,
        )

    def _set_camera_lens(
        self,
        focal_length: float,
        horizontal_aperture: float,
        aspect: float,
        clipping_range: Tuple[float, float],
        projection: str = "perspective",
    ) -> None:
        """Set the capture camera's lens; the vertical aperture follows the output aspect (height / width)."""
        renderer = self._ensure_renderer()
        for attr, value in (
            ("focalLength", [focal_length]),
            ("horizontalAperture", [horizontal_aperture]),
            ("verticalAperture", [horizontal_aperture * aspect]),
            ("clippingRange", [clipping_range]),
        ):
            renderer.write_attribute([CAMERA_PATH], attr, np.asarray(value, dtype=np.float32))
        renderer.write_attribute([CAMERA_PATH], "projection", [projection])

    def _place_ground(self, bbox_size: NDArray, center: NDArray, distance: float) -> None:
        """Move the ground under the asset's (already Z-up) world bounds."""
        if not self._ground_plane:
            return
        transform = np.asarray(build_ground_transform(bbox_size, center, distance), dtype=np.float64)
        self._ensure_renderer().write_attribute([GROUND_PATH], CAMERA_TRANSFORM_ATTR, transform.reshape(1, 4, 4))
        self._ground_top = ground_top_z(bbox_size, center)

    def _set_ground_visible(self, visible: bool) -> None:
        if not self._ground_plane or visible == self._ground_visible:
            return
        self._ensure_renderer().write_attribute([GROUND_PATH], "visibility", ["inherited" if visible else "invisible"])
        self._ground_visible = visible

    def _render_view(self, transform: NDArray, warm_up_frames: int, ground_free_pass: bool) -> Dict[str, NDArray]:
        """Render one view: colour with the ground, everything else without it.

        The ground is hidden for cameras below it, which would otherwise look at its underside,
        and whenever colour is not requested, so a single ground-free frame suffices.
        """
        self._set_camera_transform(transform)
        above_ground = self._ground_top is not None and float(transform[3, 2]) > self._ground_top
        self._set_ground_visible(above_ground and Sensors.rgb.value in self._active_sensors)
        self._warm_up(n_frames=warm_up_frames)
        frame_data = self._render_frame()
        if ground_free_pass and self._ground_visible:
            self._set_ground_visible(False)
            self._warm_up(n_frames=warm_up_frames)
            ground_free = self._render_frame()
            frame_data.update({key: arr for key, arr in ground_free.items() if key != Sensors.rgb.value})
        return frame_data

    def _capture_views(
        self,
        camera_positions: List[CameraPosition],
        center: NDArray,
        distance: float,
        offset: NDArray,
        warm_up_frames: int,
        depth_derived_requested: Set[str],
        per_sensor_frames: Dict[str, list],
        camera_metadata: list,
        deadline: Optional[float],
        omni_path: str,
    ) -> None:
        ground_free_pass = bool(self._active_sensors - {Sensors.rgb.value, Sensors.camera_params.value})
        for cam_pos in camera_positions:
            self._check_deadline(deadline, omni_path)
            transform = build_camera_transform(
                elevation=cam_pos.el,
                azimuth=cam_pos.az,
                center=center,
                distance=distance,
                offset=tuple(offset),
            )
            frame_data = self._render_view(transform, warm_up_frames, ground_free_pass)
            if not self._collect_frame(frame_data, depth_derived_requested, per_sensor_frames):
                logger.warning("Empty frame for view el=%.1f az=%.1f of %s", cam_pos.el, cam_pos.az, omni_path)
                continue
            camera_metadata.append(
                {
                    "elevation": cam_pos.el,
                    "azimuth": cam_pos.az,
                    "distance": distance,
                    "offset": [float(v) for v in offset],
                }
            )

    def _capture_scene_cameras(
        self,
        camera_paths: List[str],
        width: int,
        height: int,
        warm_up_frames: int,
        depth_derived_requested: Set[str],
        per_sensor_frames: Dict[str, list],
        camera_metadata: list,
        budget_deadline: Optional[float],
        omni_path: str,
        default_prim: Optional[str],
    ) -> None:
        """Render through the asset's own cameras, as Kit's ``render_existing_views`` did.

        The capture camera takes each camera's world transform, lens and projection in turn,
        rendering at the requested resolution, then gets its own lens back.  ``default_prim``
        maps reference-mode paths back to the asset's own.

        Like Kit, a camera that cannot be read or rendered is logged and skipped, so the orbit
        views still come back.  ``budget_deadline`` is soft: once passed, the remaining cameras
        are skipped rather than failing the asset, leaving the rest of its budget to the orbit views.
        """
        # ovrtx reads tokens back as opaque ids; USD only allows perspective or orthographic,
        # and the capture camera is still perspective here.
        perspective = np.from_dlpack(self._ensure_renderer().read_attribute("projection", [CAMERA_PATH])).reshape(-1)[0]
        ground_free_pass = bool(self._active_sensors - {Sensors.rgb.value, Sensors.camera_params.value})
        try:
            for index, path in enumerate(camera_paths):
                if budget_deadline is not None and time.monotonic() > budget_deadline:
                    logger.warning(
                        "Scene camera budget spent; skipping %d of %d camera(s) of %s",
                        len(camera_paths) - index,
                        len(camera_paths),
                        omni_path,
                    )
                    break
                try:
                    transform, focal_length, aperture, clipping_range, projection = self._read_scene_camera(
                        path, perspective
                    )
                    self._set_camera_lens(focal_length, aperture, height / width, clipping_range, projection)
                    frame_data = self._render_view(transform, warm_up_frames, ground_free_pass)
                except TimeoutError:
                    raise
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("Skipping scene camera %s of %s: %s", path, omni_path, exc)
                    continue
                if not self._collect_frame(frame_data, depth_derived_requested, per_sensor_frames):
                    logger.warning("Empty frame for scene camera %s of %s", path, omni_path)
                    continue
                camera_metadata.append(
                    {
                        "prim_path": asset_prim_path(path, default_prim),
                        "deeptag_view_type": "stage",
                        "transform": [float(v) for v in transform.ravel()],
                        "focal_length": focal_length,
                        "horizontal_aperture": aperture,
                        "projection": projection,
                    }
                )
        finally:
            focal_length, aperture = camera_intrinsics(
                self._fov, self._camera_fov_multiplier * self._base_fov_multiplier
            )
            self._set_camera_lens(focal_length, aperture, height / width, CAMERA_CLIPPING_RANGE)

    def _read_scene_camera(self, path: str, perspective: Any) -> Tuple[NDArray, float, float, Tuple[float, float], str]:
        """World transform, focal length, horizontal aperture, clipping range and projection of one camera."""
        renderer = self._ensure_renderer()

        def read(attr: str) -> NDArray:
            return np.asarray(np.from_dlpack(renderer.read_attribute(attr, [path])), dtype=np.float64).reshape(-1)

        clipping_range = read("clippingRange")
        token = np.from_dlpack(renderer.read_attribute("projection", [path])).reshape(-1)[0]
        return (
            read(WORLD_MATRIX_ATTR).reshape(4, 4),
            float(read("focalLength")[0]),
            float(read("horizontalAperture")[0]),
            (float(clipping_range[0]), float(clipping_range[1])),
            "perspective" if token == perspective else "orthographic",
        )

    def _collect_frame(
        self,
        frame_data: Dict[str, NDArray],
        depth_derived_requested: Set[str],
        per_sensor_frames: Dict[str, list],
    ) -> bool:
        """Append a rendered view to ``per_sensor_frames``; ``False`` (nothing kept) for an empty frame."""
        if not any(getattr(arr, "size", 0) > 0 for arr in frame_data.values()):
            return False
        for sensor_key, arr in frame_data.items():
            if sensor_key in per_sensor_frames:
                per_sensor_frames[sensor_key].append(arr)
        self._collect_depth_derived(frame_data, depth_derived_requested, per_sensor_frames)
        return True

    def _render_frame(self) -> Dict[str, NDArray]:
        """Execute one render step and extract all requested render variables."""
        renderer = self._ensure_renderer()
        products = renderer.step(
            render_products={RENDER_PRODUCT_PATH},
            delta_time=1.0 / 60.0,
        )

        # ovrtx keys frame outputs by the RenderVar's full prim path, not its sourceName.
        requested_vars = {
            f"{RENDER_PRODUCT_PATH}/{render_var}": sensor_key
            for sensor_key, render_var in SENSOR_RENDER_VAR_MAP.items()
            if sensor_key in self._active_sensors
        }

        result: Dict[str, NDArray] = {}
        for _product_name, product in products.items():
            for frame in product.frames:
                for render_var_name, sensor_key in requested_vars.items():
                    if render_var_name not in frame.render_vars:
                        continue
                    mapped = frame.render_vars[render_var_name].map(device=ovrtx.Device.CPU)
                    pixels = np.array(np.from_dlpack(mapped), copy=True)
                    del mapped

                    if sensor_key == Sensors.rgb.value:
                        if pixels.ndim == 3 and pixels.shape[2] >= 3:
                            pixels = pixels[:, :, :3]
                    result[sensor_key] = pixels
                break
            break

        return result

    @staticmethod
    def _collect_depth_derived(
        frame_data: Dict[str, NDArray],
        requested: Set[str],
        per_sensor_frames: Dict[str, list],
    ) -> None:
        if not requested:
            return
        depth = frame_data.get(Sensors.distance_to_camera.value)
        if depth is None:
            return
        depth_2d = depth[:, :, 0] if depth.ndim == 3 else depth
        if Sensors.semantic_segmentation.value in requested:
            per_sensor_frames[Sensors.semantic_segmentation.value].append(
                segmentation_from_depth(depth_2d),
            )
        if Sensors.bounding_box_2d_tight_fast.value in requested:
            mask = segmentation_from_depth(depth_2d)
            per_sensor_frames[Sensors.bounding_box_2d_tight_fast.value].append(
                bbox_from_mask(mask),
            )

    def _warm_up(self, n_frames: int = 5, product: str = RENDER_PRODUCT_PATH) -> None:
        """Render a few warm-up frames so shaders compile and the scene settles."""
        renderer = self._ensure_renderer()
        for _ in range(n_frames):
            renderer.step(render_products={product}, delta_time=1.0 / 60.0)

    def _measure_view(self, transform: NDArray, warm_up_frames: int) -> Optional[Dict[str, float]]:
        """Tight 2D bbox of the asset's mask from ``transform``, or ``None`` when nothing is visible."""
        self._set_camera_transform(transform)
        self._warm_up(n_frames=warm_up_frames, product=MASK_PRODUCT_PATH)
        products = self._ensure_renderer().step(render_products={MASK_PRODUCT_PATH}, delta_time=1.0 / 60.0)
        render_var = f"{MASK_PRODUCT_PATH}/{MASK_RENDER_VAR}"
        for product in products.values():
            for frame in product.frames:
                if render_var not in frame.render_vars:
                    continue
                mapped = frame.render_vars[render_var].map(device=ovrtx.Device.CPU)
                depth = np.array(np.from_dlpack(mapped), copy=True)
                del mapped
                depth_2d = depth[:, :, 0] if depth.ndim == 3 else depth
                return bbox_from_mask(segmentation_from_depth(depth_2d)).get(SEMANTIC_LABEL)
        return None

    def _measure_views(
        self,
        camera_positions: List[CameraPosition],
        center: NDArray,
        distance: float,
        offset: NDArray,
        deadline: Optional[float],
        omni_path: str,
    ) -> Tuple[List[NDArray], List[Optional[Dict[str, float]]]]:
        """Camera transforms and mask bboxes of ``camera_positions``, checking the deadline before each render."""
        transforms = [
            build_camera_transform(
                elevation=cam_pos.el, azimuth=cam_pos.az, center=center, distance=distance, offset=tuple(offset)
            )
            for cam_pos in camera_positions
        ]
        bboxes = []
        for transform in transforms:
            self._check_deadline(deadline, omni_path)
            bboxes.append(self._measure_view(transform, warm_up_frames=2))
        return transforms, bboxes

    def _auto_frame(
        self,
        camera_positions: List[CameraPosition],
        center: NDArray,
        distance: float,
        width: int,
        height: int,
        deadline: Optional[float],
        omni_path: str,
    ) -> Tuple[NDArray, float]:
        """Port of Kit's auto-center / auto-zoom: return the pivot offset and camera distance.

        Like Kit, the pivot is first centred on the asset's mask in a top and a side
        view, then the distance is set so the largest mask side across the requested
        views is ``FRAMING_TARGET_FILL`` of the view.  Masks are rendered with the ground
        hidden.  Falls back to the unadjusted framing when the asset is not visible.
        """
        intrinsics = camera_intrinsics(self._fov, self._camera_fov_multiplier * self._base_fov_multiplier)
        self._set_ground_visible(False)
        offset = self._center_pivot(center, distance, width, height, intrinsics, deadline, omni_path)
        fitted = (
            None
            if offset is None
            else self._fit_distance(camera_positions, center, distance, offset, width, height, deadline, omni_path)
        )
        if offset is None or fitted is None:
            logger.warning("Auto-framing found no mask for %s; keeping the default framing", omni_path)
            return np.zeros(3), distance
        logger.info("Auto-framed %s: offset=%s distance=%.4g", omni_path, np.round(offset, 6).tolist(), fitted)
        return offset, fitted

    def _center_pivot(
        self,
        center: NDArray,
        distance: float,
        width: int,
        height: int,
        intrinsics: Tuple[float, float],
        deadline: Optional[float],
        omni_path: str,
    ) -> Optional[NDArray]:
        """Pivot offset centring the mask in Kit's top and side probe views (``FRAMING_PROBE_VIEWS``).

        A probe that clips the asset is moved back first, since a clipped bbox is off-centre;
        the offset is in world units, so the probe distance does not carry over.
        """
        probes = [CameraPosition(az=az, el=el) for az, el in FRAMING_PROBE_VIEWS]
        offset = np.zeros(3)
        backoffs = iterations = 0
        while iterations < FRAMING_ITERATIONS:
            transforms, bboxes = self._measure_views(probes, center, distance, offset, deadline, omni_path)
            if not any(bboxes):
                return None
            if backoffs < FRAMING_MAX_BACKOFFS and any(
                bbox and bbox_touches_border(bbox, width, height) for bbox in bboxes
            ):
                backoffs += 1
                distance *= FRAMING_BACKOFF
                continue
            offset = offset + solve_center_offset(bboxes, transforms, distance, width, height, *intrinsics)
            iterations += 1
        return offset

    def _fit_distance(
        self,
        camera_positions: List[CameraPosition],
        center: NDArray,
        distance: float,
        offset: NDArray,
        width: int,
        height: int,
        deadline: Optional[float],
        omni_path: str,
    ) -> Optional[float]:
        """Distance at which the largest mask side across the requested views is ``FRAMING_TARGET_FILL``.

        As in Kit, the camera moves back by ``FRAMING_BACKOFF`` while any view clips the asset
        (at most ``FRAMING_MAX_BACKOFFS`` times) and otherwise never ends up further than that,
        so an asset that already fills more than the target keeps its distance.
        """
        max_distance = distance
        backoffs = iterations = 0
        while True:
            _, bboxes = self._measure_views(camera_positions, center, distance, offset, deadline, omni_path)
            if not any(bboxes):
                return None
            if any(bbox and bbox_touches_border(bbox, width, height) for bbox in bboxes):
                if backoffs >= FRAMING_MAX_BACKOFFS:
                    logger.warning("Asset still clipped after %d back-offs: %s", backoffs, omni_path)
                    return distance
                backoffs += 1
                distance *= FRAMING_BACKOFF
                max_distance = max(max_distance, distance)
                continue
            new_distance = min(solve_distance(bboxes, distance, width, height), max_distance)
            if iterations >= FRAMING_ITERATIONS or np.isclose(new_distance, distance, rtol=1e-3):
                return distance
            distance = new_distance
            iterations += 1

    @staticmethod
    def _check_deadline(deadline: Optional[float], omni_path: str) -> None:
        if deadline is not None and time.monotonic() > deadline:
            raise TimeoutError(f"Rendering exceeded the allotted time for {omni_path}")

    def get_asset_renderings(
        self,
        omni_path: str,
        camera_positions: Optional[List[CameraPosition]] = None,
        camera_parameters: Optional[CameraParameters] = None,
        render_existing_views: bool = True,
        sensors: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        up_axis: Optional[str] = None,
        apply_default_material: bool = False,
        adjust_framing: bool = True,
        default_prim: Optional[str] = None,
        **kwargs,
    ) -> Union[Dict[str, Any], str]:  # pylint: disable=unused-argument
        """Render an asset from multiple viewpoints and return sensor data.

        Returns a dict keyed by sensor output names (e.g. ``"images"``,
        ``"depth"``, ``"normal"``) or an empty string for empty scenes.
        The ``sensors`` parameter controls which outputs are captured.

        ``timeout`` bounds the wall-clock render budget for this asset.  The
        in-process ovrtx render is a blocking call with no ``await`` point, so
        it cannot be cancelled by ``asyncio.wait_for``; the deadline is enforced
        cooperatively between render stages instead.

        ``adjust_framing`` (the request's ``adjust_camera_multiplier``) can turn auto-framing
        off per request; it only runs when ``RENDER_ADJUST_FRAMING`` also enables it.

        ``render_existing_views`` also renders through the asset's own cameras; like Kit, those
        views come first, with ``prim_path`` (under ``default_prim``, the asset's ``defaultPrim``)
        and ``deeptag_view_type="stage"`` in their camera metadata.
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        if camera_parameters is None:
            camera_parameters = CameraParameters()
        if camera_positions is None:
            camera_positions = [CameraPosition(az=az, el=el) for el in ELEVATIONS for az in AZIMUTHS]

        if sensors is None:
            self._active_sensors = DEFAULT_SENSOR_SET.copy()
        else:
            self._active_sensors = set(sensors)
            unsupported = self._active_sensors & ANNOTATOR_ONLY_SENSORS
            if unsupported:
                logger.warning(
                    "Sensors not available in ovrtx backend (require Kit annotators): %s",
                    ", ".join(sorted(unsupported)),
                )
                self._active_sensors -= unsupported

        depth_derived_requested = self._active_sensors & DEPTH_DERIVED_SENSORS
        needs_implicit_depth = (
            bool(depth_derived_requested) and Sensors.distance_to_camera.value not in self._active_sensors
        )
        if needs_implicit_depth:
            self._active_sensors.add(Sensors.distance_to_camera.value)

        width = camera_parameters.width
        height = camera_parameters.height

        logger.info("Rendering %s (%dx%d, %d views)", omni_path, width, height, len(camera_positions))

        self._load_scene(omni_path, width, height)
        self._warm_up(n_frames=2)
        self._check_deadline(deadline, omni_path)

        geometry_prims = self._find_geometry_prims()
        used_full_stage = False
        if not geometry_prims and self._load_as_reference:
            logger.warning("No geometry via reference (missing defaultPrim?), retrying as full stage: %s", omni_path)
            used_full_stage = True
            self._load_scene(omni_path, width, height, force_full_stage=True)
            self._warm_up(n_frames=2)
            geometry_prims = self._find_geometry_prims()

        if not geometry_prims:
            logger.warning("Empty scene: %s", omni_path)
            return ""

        if apply_default_material:
            roots = top_level_roots(geometry_prims)
            logger.info("Applying grey default material to material-less asset: %s", roots)
            self._load_scene(omni_path, width, height, force_full_stage=used_full_stage, default_material_roots=roots)
            self._warm_up(n_frames=2)
            geometry_prims = self._find_geometry_prims()

        self._orient_to_world_up(up_axis, geometry_prims)

        bbox_size, center = self._compute_world_bounds(geometry_prims)

        distance = compute_camera_distance(
            bbox_size,
            self._camera_fov_multiplier * self._base_camera_distance_multiplier,
        )

        offset = np.zeros(3)
        if self._adjust_framing and adjust_framing:
            offset, distance = self._auto_frame(camera_positions, center, distance, width, height, deadline, omni_path)

        self._place_ground(bbox_size, center, distance)
        self._warm_up(n_frames=10)

        output_keys = {s for s in self._active_sensors if s in SENSOR_RENDER_VAR_MAP} | depth_derived_requested
        scene_frames: Dict[str, list] = {k: [] for k in output_keys}
        scene_metadata: list = []
        scene_cameras = self._find_scene_cameras() if render_existing_views else []
        if scene_cameras:
            logger.info("Rendering %d scene camera(s) of %s", len(scene_cameras), omni_path)
            # Scene cameras get at most this share of the remaining budget, so a camera-heavy
            # scene cannot time out the asset before its orbit views are rendered.
            budget_deadline = (
                None
                if deadline is None
                else time.monotonic() + (deadline - time.monotonic()) * SCENE_CAMERA_BUDGET_FRACTION
            )
            self._capture_scene_cameras(
                scene_cameras,
                width,
                height,
                warm_up_frames=2,
                depth_derived_requested=depth_derived_requested,
                per_sensor_frames=scene_frames,
                camera_metadata=scene_metadata,
                budget_deadline=budget_deadline,
                omni_path=omni_path,
                # Only a referenced asset is composed under /Asset; a sublayered one keeps its own paths.
                default_prim=default_prim if self._load_as_reference and not used_full_stage else None,
            )

        per_sensor_frames: Dict[str, list] = {k: [] for k in output_keys}
        camera_metadata: list = []
        capture = partial(
            self._capture_views,
            camera_positions,
            center,
            distance,
            offset,
            depth_derived_requested=depth_derived_requested,
            per_sensor_frames=per_sensor_frames,
            camera_metadata=camera_metadata,
            deadline=deadline,
            omni_path=omni_path,
        )
        capture(warm_up_frames=2)

        if not any(per_sensor_frames.values()):
            logger.warning("No output captured for %s, retrying with more warm-up", omni_path)
            self._warm_up(n_frames=30)
            capture(warm_up_frames=3)

        for sensor_key, frames in scene_frames.items():
            per_sensor_frames[sensor_key][:0] = frames
        camera_metadata[:0] = scene_metadata

        if not any(per_sensor_frames.values()):
            logger.warning("No renderable output for %s after retries", omni_path)
            return ""

        output: Dict[str, Any] = {}
        for sensor_key, frames in per_sensor_frames.items():
            if not frames:
                continue
            if sensor_key == Sensors.bounding_box_2d_tight_fast.value:
                output[sensor_key] = frames
            else:
                stacked = np.stack(frames, axis=0)
                if sensor_key == Sensors.rgb.value:
                    stacked = stacked.astype(np.uint8)
                output[sensor_key] = stacked

        if needs_implicit_depth:
            output.pop(Sensors.distance_to_camera.value, None)

        if Sensors.camera_params.value in self._active_sensors:
            output[Sensors.camera_params.value] = camera_metadata

        logger.info(
            "Captured %d views for %s (sensors: %s)",
            len(camera_metadata),
            omni_path,
            ", ".join(sorted(output.keys())),
        )

        return output

    def shutdown(self) -> None:
        if self._renderer is not None:
            del self._renderer
            self._renderer = None
            self._current_asset_path = None
            logger.info("ovrtx renderer shut down")
