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
import math
import os
import tempfile
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

ENVIRONMENT_PRIM_PREFIX = "/DeepSearch"
RENDER_SCOPE_PREFIX = "/Render"
CAMERA_PATH = f"{ENVIRONMENT_PRIM_PREFIX}/CameraRig1/CameraRig2/Camera"
GROUND_PATH = f"{ENVIRONMENT_PRIM_PREFIX}/Ground"
GROUND_MATERIAL_PATH = f"{ENVIRONMENT_PRIM_PREFIX}/Looks/GroundGrey"
RENDER_PRODUCT_PATH = f"{RENDER_SCOPE_PREFIX}/RenderProduct"
# Depth-only product stepped on its own to measure the asset's silhouette for auto-framing.
MASK_PRODUCT_PATH = f"{RENDER_SCOPE_PREFIX}/MaskProduct"
MASK_RENDER_VAR = "DistanceToCameraSD"
_ASSET_PRIM_PATH = "/Asset"

CAMERA_TRANSFORM_ATTR = "omni:xform"
# Composed world transform, maintained by ovrtx; ``omni:xform`` is only the local one.
WORLD_MATRIX_ATTR = "omni:fabric:worldMatrix"
CAMERA_CLIPPING_RANGE = (0.01, 1000000.0)
# Kit's viewport cameras, which Kit skipped when rendering a scene's own cameras.
KIT_VIEWPORT_CAMERAS = frozenset(f"OmniverseKit_{view}" for view in ("Persp", "Top", "Right", "Front"))

DEFAULT_MATERIAL_PATH = "/World/Looks/DefaultGrey"
# Albedo tuned under the regular dome and ground to match Kit's grey-clay exposure.
DEFAULT_MATERIAL_GREY = 0.2
# Kit's floor: a grey slab under the asset that catches its contact shadow and
# blocks the lower half of the dome, so the asset is lit from above.
GROUND_GREY = 0.22
GROUND_ROUGHNESS = 0.5
# Gap between the asset's lowest point and the floor, relative to the bbox diagonal.
GROUND_GAP_FRACTION = 1e-3

HORIZONTAL_APERTURE = 20.955
# Kit's ``object_min_size``: auto-framing sizes the largest mask-bbox side to this fraction of the view.
FRAMING_TARGET_FILL = 0.75
# Kit moved the camera back by this factor while the asset was clipped by the frame, at most N times.
FRAMING_BACKOFF = 1.2
FRAMING_MAX_BACKOFFS = 10
# Measure-and-solve rounds; the second corrects the perspective error of the first.
FRAMING_ITERATIONS = 2
# (azimuth, elevation) of the views Kit centred the asset in: straight down and side-on.
FRAMING_PROBE_VIEWS = ((0.0, 0.0), (0.0, 270.0))

GEOMETRY_PRIM_TYPES = (
    "Mesh",
    "Points",
    "BasisCurves",
    "PointInstancer",
    "Sphere",
    "Cube",
    "Cone",
    "Cylinder",
    "Capsule",
)


class Sensors(str, Enum):
    """Sensor output keys forming the renderer's downstream output contract."""

    rgb = "images"
    semantic_segmentation = "segmentation"
    distance_to_camera = "depth"
    distance_to_image_plane = "linear_depth"
    normals = "normal"
    camera_params = "camera_metadata"
    pointcloud = "pointcloud"
    bounding_box_2d_tight_fast = "bounding_box_2d_tight_fast"


DEFAULT_SENSOR_SET: Set[str] = {Sensors.rgb.value, Sensors.camera_params.value}

# ovrtx exposes the non-colour AOVs under their SyntheticData ("SD") names; the
# bare Kit names are accepted but render empty tensors.
SENSOR_RENDER_VAR_MAP = {
    Sensors.rgb.value: "LdrColor",
    Sensors.distance_to_camera.value: "DistanceToCameraSD",
    Sensors.distance_to_image_plane.value: "DistanceToImagePlaneSD",
    Sensors.normals.value: "NormalSD",
}

DEPTH_DERIVED_SENSORS: Set[str] = {
    Sensors.semantic_segmentation.value,
    Sensors.bounding_box_2d_tight_fast.value,
}

ANNOTATOR_ONLY_SENSORS: Set[str] = {
    Sensors.pointcloud.value,
}

SEMANTIC_LABEL = "object"


def build_scene_root_usda(
    domelight_intensity: float = 1500.0,
    fov: float = 60.0,
    fov_multiplier: float = 0.5,
    width: int = 448,
    height: int = 448,
    domelight_shade: int = 255,
    requested_sensors: Set[str] = DEFAULT_SENSOR_SET,
    asset_sublayer: Optional[str] = None,
    default_material_roots: Optional[List[str]] = None,
    ground_plane: bool = True,
    mask_product: bool = False,
    asset_reference: Optional[str] = None,
) -> str:
    """Generate the inline root layer hosting the environment and render product.

    ovrtx expects cameras and render products to be authored directly in the
    root layer rather than added as references, so the environment and render
    product scopes are composed inline here.  The asset is brought in either as
    a removable reference (added separately via ``add_usd_reference``) or, when
    ``asset_sublayer`` is provided, as a sublayer carrying the full asset stage.

    When ``default_material_roots`` is set, a neutral grey material is authored and
    bound (stronger than descendants) onto those prims, giving material-less assets
    Kit's grey-clay fallback instead of ovrtx's red missing-material placeholder.
    Binding a referenced asset (root ``/Asset``) needs ``asset_reference``: the
    reference is then authored inline on ``/Asset`` instead of via ``add_usd_reference``.

    ``ground_plane`` authors Kit's floor under ``/DeepSearch``; it is placed per asset
    with :func:`build_ground_transform` once the asset's bounds are known.

    ``mask_product`` adds the depth-only product used to measure the asset for auto-framing.
    """
    sublayer_line = f"\n    subLayers = [@{asset_sublayer}@]" if asset_sublayer else ""
    environment_block = build_environment_usda(
        domelight_intensity=domelight_intensity,
        fov=fov,
        fov_multiplier=fov_multiplier,
        width=width,
        height=height,
        domelight_shade=domelight_shade,
        ground_plane=ground_plane,
    )
    render_product_block = build_render_product_usda(
        camera_path=CAMERA_PATH,
        width=width,
        height=height,
        requested_sensors=requested_sensors,
        mask_product=mask_product,
    )
    roots = default_material_roots or []
    world_body = build_default_material_usda() if roots else ""
    binding_block = "".join(
        build_default_material_binding_usda(root, asset_reference=asset_reference if root == _ASSET_PRIM_PATH else None)
        for root in roots
    )
    return f"""#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Z"{sublayer_line}
)

def Xform "World" {{
{world_body}}}

{environment_block}

{render_product_block}
{binding_block}"""


def build_default_material_usda(grey: float = DEFAULT_MATERIAL_GREY) -> str:
    """Author a neutral grey ``UsdPreviewSurface`` material under ``/World/Looks``."""
    return f"""    def Scope "Looks"
    {{
        def Material "DefaultGrey"
        {{
            token outputs:surface.connect = <{DEFAULT_MATERIAL_PATH}/Shader.outputs:surface>
            def Shader "Shader"
            {{
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = ({grey}, {grey}, {grey})
                float inputs:roughness = 0.55
                float inputs:metallic = 0.0
                token outputs:surface
            }}
        }}
    }}
"""


def build_default_material_binding_usda(root_path: str, asset_reference: Optional[str] = None) -> str:
    """Bind the grey material onto ``root_path``, overriding any descendant bindings.

    With ``asset_reference`` the prim is defined here referencing the asset, since a
    root-layer ``over`` would block ``add_usd_reference`` at the same path.
    """
    specifier = "def" if asset_reference else "over"
    reference_line = f"\n    prepend references = @{asset_reference}@" if asset_reference else ""
    return f"""
{specifier} "{root_path.lstrip('/')}" (
    prepend apiSchemas = ["MaterialBindingAPI"]{reference_line}
)
{{
    rel material:binding = <{DEFAULT_MATERIAL_PATH}> (
        bindMaterialAs = "strongerThanDescendants"
    )
}}
"""


def compute_camera_distance(
    bbox_size: NDArray,
    distance_multiplier: float = 1.0,
) -> float:
    """Distance from the asset center placing it within the camera frustum.

    Mirrors the Kit framing exactly: the camera sits at twice the bounding
    sphere radius, scaled by the caller-supplied multiplier.  Framing is driven
    by the camera's focal length (see ``build_environment_usda``), so this
    distance is intentionally field-of-view independent.
    """
    bounding_radius = float(np.sqrt(np.sum((bbox_size / 2) ** 2)))
    distance = bounding_radius * 2.0 * distance_multiplier
    return max(distance, 0.1)


def _rotation_matrix_axis_angle(axis: NDArray, degrees: float) -> NDArray:
    """Build a 4x4 rotation matrix from an axis and angle in degrees (row-major, USD convention)."""
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    ax = axis / (np.linalg.norm(axis) + 1e-12)
    x, y, z = float(ax[0]), float(ax[1]), float(ax[2])
    t = 1.0 - c
    m = np.eye(4)
    m[0, 0] = t * x * x + c
    m[0, 1] = t * x * y + s * z
    m[0, 2] = t * x * z - s * y
    m[1, 0] = t * x * y - s * z
    m[1, 1] = t * y * y + c
    m[1, 2] = t * y * z + s * x
    m[2, 0] = t * x * z + s * y
    m[2, 1] = t * y * z - s * x
    m[2, 2] = t * z * z + c
    return m


def y_up_to_z_up_matrix() -> NDArray:
    """Row-major +90 about X, mapping a Y-up asset's up axis onto the Z-up world (Kit parity)."""
    return _rotation_matrix_axis_angle(np.array([1.0, 0.0, 0.0]), 90.0)


def top_level_roots(prim_paths: List[str]) -> List[str]:
    """Unique, order-preserving top-level ancestors (``/Root``) of the given prim paths."""
    roots: List[str] = []
    for path in prim_paths:
        segments = path.split("/")
        if len(segments) >= 2 and segments[1]:
            root = "/" + segments[1]
            if root not in roots:
                roots.append(root)
    return roots


def asset_prim_path(path: str, default_prim: Optional[str]) -> str:
    """``path`` in the asset's own namespace: a referenced asset's ``defaultPrim`` is composed at ``/Asset``."""
    if default_prim and (path == _ASSET_PRIM_PATH or path.startswith(f"{_ASSET_PRIM_PATH}/")):
        return f"/{default_prim.lstrip('/')}{path[len(_ASSET_PRIM_PATH):]}"
    return path


def _translate_matrix(tx: float, ty: float, tz: float) -> NDArray:
    """Build a 4x4 translation matrix (row-major, translation in last row)."""
    m = np.eye(4)
    m[3, 0] = tx
    m[3, 1] = ty
    m[3, 2] = tz
    return m


def _scale_matrix(sx: float, sy: float, sz: float) -> NDArray:
    return np.diag([sx, sy, sz, 1.0])


def build_camera_transform(
    elevation: float,
    azimuth: float,
    center: NDArray,
    distance: float,
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    offset: Tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> NDArray:
    """Build a 4x4 world transform for a camera orbiting around a center point.

    Replicates the Kit CameraRig1 -> CameraRig2 -> Camera hierarchy, where each rig
    authors these xformOps (in list order):
      CameraRig1: scale, translate(center)
      CameraRig2: translate(offset), RotateZ(az), RotateX(el)
      Camera: translate(0, 0, distance)

    USD evaluates an xformOpOrder in reverse for row-vector points, so each rig's
    local matrix is the reverse-order product of its ops. That makes elevation the
    inner rotation and azimuth orbit the object about world +Z (a turntable);
    composing them the other way (Rz @ Rx) leaves the on-axis camera azimuth-degenerate.

    Returns a row-major 4x4 numpy matrix matching USD/Gf conventions.
    """
    rig1 = _translate_matrix(float(center[0]), float(center[1]), float(center[2])) @ _scale_matrix(*scale)

    rig2 = _rotation_matrix_axis_angle(np.array([1.0, 0.0, 0.0]), elevation) @ _rotation_matrix_axis_angle(
        np.array([0.0, 0.0, 1.0]), azimuth
    )
    if offset != (0.0, 0.0, 0.0):
        rig2 = rig2 @ _translate_matrix(*offset)

    cam_local = _translate_matrix(0.0, 0.0, distance)

    return cam_local @ rig2 @ rig1


def build_ground_usda(grey: float = GROUND_GREY, roughness: float = GROUND_ROUGHNESS) -> str:
    """Author Kit's ground: a unit ``Cube`` with an explicit grey material.

    Without a bound material ovrtx would show its red missing-material placeholder.
    """
    return f"""
    def Scope "Looks" {{
        def Material "GroundGrey" {{
            token outputs:surface.connect = <{GROUND_MATERIAL_PATH}/Shader.outputs:surface>
            def Shader "Shader" {{
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = ({grey}, {grey}, {grey})
                float inputs:roughness = {roughness}
                float inputs:metallic = 0.0
                token outputs:surface
            }}
        }}
    }}

    def Cube "Ground" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    ) {{
        double size = 1
        rel material:binding = <{GROUND_MATERIAL_PATH}>
    }}
"""


def ground_top_z(bbox_size: NDArray, center: NDArray) -> float:
    """World Z of the ground's top face: just below the asset's lowest point (world is Z-up)."""
    gap = max(float(np.linalg.norm(bbox_size)) * GROUND_GAP_FRACTION, 1e-6)
    return float(center[2] - bbox_size[2] / 2.0) - gap


def build_ground_transform(bbox_size: NDArray, center: NDArray, distance: float) -> NDArray:
    """Row-major world transform placing the unit ground cube under the asset.

    Mirrors Kit's ground (a slab ``max(2 * distance, 1e6)`` wide centred under the
    asset), except that the gap and thickness scale with the asset instead of Kit's
    fixed 0.51 stage units, which left small metre-scale assets visibly floating.
    """
    width = max(2.0 * distance, 1_000_000.0)
    thickness = max(float(np.linalg.norm(bbox_size)) * 0.01, 1e-5)
    top = ground_top_z(bbox_size, center)
    return _scale_matrix(width, width, thickness) @ _translate_matrix(
        float(center[0]), float(center[1]), top - thickness / 2.0
    )


def build_environment_usda(
    domelight_intensity: float = 1500.0,
    fov: float = 60.0,
    fov_multiplier: float = 0.5,
    width: int = 448,
    height: int = 448,
    domelight_shade: int = 255,
    ground_plane: bool = True,
) -> str:
    """Generate the ``DeepSearch`` scope block (lights, camera rig and ground).

    Returned as a root-level prim block (no layer header) so it can be authored
    inline in the scene root layer.  ``fov_multiplier`` scales the focal length
    exactly as the Kit pipeline did (``camera_fov_multiplier * base_fov_multiplier``),
    which controls how tightly the asset is framed.
    """
    tex_dir = os.path.join(tempfile.gettempdir(), "deepsearch_textures")
    os.makedirs(tex_dir, exist_ok=True)
    tex_path = os.path.join(tex_dir, "grey.jpg")
    if not os.path.exists(tex_path):
        from PIL import Image

        img = Image.fromarray(np.ones((10, 10, 3), dtype=np.uint8) * domelight_shade)
        img.save(tex_path)

    focal_length, horizontal_aperture = camera_intrinsics(fov, fov_multiplier)
    vertical_aperture = horizontal_aperture * height / width

    return f"""def Scope "DeepSearch" {{
    def DomeLight "DomeLight" {{
        float inputs:intensity = {domelight_intensity}
        token inputs:texture:format = "latlong"
        asset inputs:texture:file = @{tex_path}@
    }}

    def Xform "CameraRig1" {{
        def Xform "CameraRig2" {{
            def Camera "Camera" {{
                float focalLength = {focal_length}
                float horizontalAperture = {horizontal_aperture}
                float verticalAperture = {vertical_aperture}
                float2 clippingRange = ({CAMERA_CLIPPING_RANGE[0]}, {CAMERA_CLIPPING_RANGE[1]})
            }}
        }}
    }}
{build_ground_usda() if ground_plane else ""}}}
"""


def camera_intrinsics(fov: float = 60.0, fov_multiplier: float = 0.5) -> Tuple[float, float]:
    """Focal length and horizontal aperture of the capture camera, both in millimetres."""
    focal_length = HORIZONTAL_APERTURE / math.tan(math.radians(fov / 2.0)) * fov_multiplier
    return focal_length, HORIZONTAL_APERTURE


def build_render_product_usda(
    camera_path: str = CAMERA_PATH,
    width: int = 448,
    height: int = 448,
    requested_sensors: Set[str] = DEFAULT_SENSOR_SET,
    mask_product: bool = False,
) -> str:
    """Generate the ``Render`` scope block with a RenderProduct and RenderVars.

    Only includes RenderVar prims for sensors that have a corresponding render
    variable in the RTX backend.  Returned as a root-level prim block (no layer
    header) so it can be authored inline in the scene root layer.

    ``mask_product`` adds a second product carrying only camera distance, so the
    auto-framing measurement can be stepped without the requested outputs.
    """
    render_var_defs = []
    ordered_var_refs = []

    for sensor_key, render_var_name in SENSOR_RENDER_VAR_MAP.items():
        if sensor_key in requested_sensors:
            render_var_defs.append(
                f'        def RenderVar "{render_var_name}" {{\n'
                f'            uniform string sourceName = "{render_var_name}"\n'
                f"        }}"
            )
            ordered_var_refs.append(f"<{RENDER_PRODUCT_PATH}/{render_var_name}>")

    ordered_vars_line = ""
    if ordered_var_refs:
        refs_str = ",\n            ".join(ordered_var_refs)
        ordered_vars_line = f"\n        rel orderedVars = [\n            {refs_str},\n        ]"

    render_var_block = "\n".join(render_var_defs)
    if render_var_block:
        render_var_block = "\n" + render_var_block

    mask_product_block = ""
    if mask_product:
        mask_product_block = f"""
    def RenderProduct "MaskProduct" {{
        rel camera = <{camera_path}>
        int2 resolution = ({width}, {height})
        rel orderedVars = [<{MASK_PRODUCT_PATH}/{MASK_RENDER_VAR}>]
        def RenderVar "{MASK_RENDER_VAR}" {{
            uniform string sourceName = "{MASK_RENDER_VAR}"
        }}
    }}"""

    return f"""def Scope "Render" {{
    def RenderProduct "RenderProduct" {{
        rel camera = <{camera_path}>
        int2 resolution = ({width}, {height}){ordered_vars_line}{render_var_block}
    }}{mask_product_block}
}}
"""


def segmentation_from_depth(depth: NDArray) -> NDArray:
    """Derive a binary segmentation mask from a depth buffer.

    Pixels with finite, positive depth are classified as foreground (asset).
    Background pixels (inf, nan, zero, or negative) are classified as empty.
    """
    return np.isfinite(depth) & (depth > 0)


def bbox_from_mask(mask: NDArray) -> Dict[str, Dict[str, float]]:
    """Compute a 2D tight bounding box from a binary segmentation mask.

    Returns a dict mapping the semantic label to bounding box coordinates,
    matching the Kit SyntheticData output contract.  Returns an empty dict
    when no foreground pixels are present.
    """
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not np.any(rows):
        return {}
    row_indices = np.where(rows)[0]
    col_indices = np.where(cols)[0]
    return {
        SEMANTIC_LABEL: {
            "xmin": float(col_indices[0]),
            "ymin": float(row_indices[0]),
            "xmax": float(col_indices[-1]),
            "ymax": float(row_indices[-1]),
        }
    }


def bbox_touches_border(bbox: Dict[str, float], width: int, height: int) -> bool:
    """True when a 2D bbox reaches the image edge, i.e. the asset may be clipped by the frame."""
    return bbox["xmin"] <= 0 or bbox["ymin"] <= 0 or bbox["xmax"] >= width - 1 or bbox["ymax"] >= height - 1


def solve_center_offset(
    bboxes: List[Optional[Dict[str, float]]],
    transforms: List[NDArray],
    distance: float,
    width: int,
    height: int,
    focal_length: float,
    horizontal_aperture: float = HORIZONTAL_APERTURE,
) -> NDArray:
    """World-space shift of the camera pivot that centres the mask bboxes, in one step.

    Kit stepped a single pivot offset until the mask was centred in a top and a side
    view.  Here a pixel offset ``(du, dv)`` at the pivot is a world shift of
    ``du * D * A / (f * W)`` along the camera's right axis (and ``-dv`` along its up
    axis), so each view gives two linear equations in the shift, solved in the
    least-squares sense.  ``transforms`` are the row-major camera world matrices
    (rows 0 and 1 are the camera's right and up axes); views with no mask (``None``)
    are ignored.
    """
    world_per_pixel = distance * horizontal_aperture / (focal_length * width)
    rows, rhs = [], []
    for bbox, transform in zip(bboxes, transforms):
        if not bbox:
            continue
        du = (bbox["xmin"] + bbox["xmax"]) / 2.0 - (width - 1) / 2.0
        dv = (bbox["ymin"] + bbox["ymax"]) / 2.0 - (height - 1) / 2.0
        right = np.asarray(transform[0, :3], dtype=np.float64)
        up = np.asarray(transform[1, :3], dtype=np.float64)
        rows.extend([right / np.linalg.norm(right), up / np.linalg.norm(up)])
        rhs.extend([du * world_per_pixel, -dv * world_per_pixel])
    if not rows:
        return np.zeros(3)
    return np.linalg.lstsq(np.asarray(rows), np.asarray(rhs), rcond=None)[0]


def solve_distance(
    bboxes: List[Optional[Dict[str, float]]],
    distance: float,
    width: int,
    height: int,
    target_fill: float = FRAMING_TARGET_FILL,
) -> float:
    """Camera distance at which the largest mask-bbox side is ``target_fill`` of the view.

    Kit binary-searched this; the projected size scales with ``1 / D``, so one rescale
    by the ratio between the largest side and the target gets there directly.
    """
    sides = [max(b["xmax"] - b["xmin"], b["ymax"] - b["ymin"]) for b in bboxes if b]
    if not sides:
        return distance
    return max(distance * max(sides) / (target_fill * min(width, height)), 1e-6)
