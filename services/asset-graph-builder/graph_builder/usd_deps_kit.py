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

#
# This script loads USD stage specified in the env "USD_URL", traverses dependencies, and saves dependencies graph
# in a json format to the file specified in the env "OUTPUT_PATH"
#

import json
import logging
import os
import re
import time
import urllib
from collections import defaultdict
from enum import Enum
from functools import lru_cache
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

import omni.client
import omni.usd
from graph_builder import setup_logging
from pxr import Gf, Sdf, Usd, UsdGeom, UsdUtils

logger = logging.getLogger(__name__)


def timing_decorator(func):
    def wrapper(*args, **kwargs):
        logger.info("Running %s...", func.__name__)
        start_time = time.time()
        result = func(*args, **kwargs)
        duration_ms = (time.time() - start_time) * 1000
        logger.info("%s executed in %.2fms", func.__name__, duration_ms)
        return result

    return wrapper


def str2bool(s: Any) -> bool:
    """Convert input string to bool"""
    if isinstance(s, str):
        return s.lower() in ("true", "1")
    else:
        return s


USE_SEMANTICS_API = str2bool(os.getenv("USE_SEMANTICS_API", "True"))
USE_PHYSICS_API = str2bool(os.getenv("USE_PHYSICS_API", "True"))
INCLUDE_POLYGON_COUNT_IN_USD_PROPERTIES = str2bool(os.getenv("INCLUDE_POLYGON_COUNT_IN_USD_PROPERTIES", "True"))
COUNT_POINTS_AS_POLYGONS = str2bool(os.getenv("COUNT_POINTS_AS_POLYGONS", "True"))
COUNT_CURVE_SEGMENTS_AS_POLYGONS = str2bool(os.getenv("COUNT_CURVE_SEGMENTS_AS_POLYGONS", "True"))

# USD uses FLT_MAX (single precision float max) for empty range sentinel values
# This matches the value used internally by Gf.Range3d.SetEmpty()
GF_FLT_MAX = 3.4028234663852886e38


def compute_bbox(prim: Usd.Prim) -> Gf.Range3d:
    """
    Compute Bounding Box using UsdGeom.BBoxCache with extentsHint support.

    Uses BBoxCache with useExtentsHint=True to properly handle unloaded payloads
    and avoid 'childEntry->isComplete' errors that occur when traversing
    incomplete prim hierarchies.

    See https://openusd.org/dev/api/class_usd_geom_b_box_cache.html

    Args:
        prim: A prim to compute the bounding box.
    Returns:
        A range (i.e. bounding box), see more at: https://graphics.pixar.com/usd/release/api/class_gf_range3d.html
        Returns an empty range if the prim is invalid or bbox computation fails.
    """
    if not prim or not prim.IsValid():
        logger.warning("compute_bbox: Invalid prim provided")
        return Gf.Range3d()

    time_code = Usd.TimeCode.Default()
    purposes = [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]

    # Use BBoxCache with useExtentsHint=True to handle unloaded payloads
    # This allows the cache to use pre-computed extentsHint attributes
    # instead of traversing into incomplete/unloaded hierarchies
    try:
        bbox_cache = UsdGeom.BBoxCache(time_code, purposes, useExtentsHint=True)
        bound = bbox_cache.ComputeWorldBound(prim)
        bound_range = bound.ComputeAlignedBox()
        return bound_range
    except Exception as e:
        logger.warning("compute_bbox: Failed to compute bbox for %s: %s", prim.GetPath(), e)
        return Gf.Range3d()


def get_world_transform_xform(prim: Usd.Prim) -> Tuple[Gf.Vec3d, Gf.Rotation, Gf.Vec3d]:
    """
    Get the local transformation of a prim using Xformable.
    See https://openusd.org/release/api/class_usd_geom_xformable.html
    Args:
        prim: The prim to calculate the world transformation.
    Returns:
        A tuple of:
        - Translation vector.
        - Rotation quaternion, i.e. 3d vector plus angle.
        - Scale vector.
    """
    xform = UsdGeom.Xformable(prim)
    time = Usd.TimeCode.Default()  # The time at which we compute the bounding box
    world_transform: Gf.Matrix4d = xform.ComputeLocalToWorldTransform(time)
    translation: Gf.Vec3d = world_transform.ExtractTranslation()
    rotation: Gf.Rotation = world_transform.ExtractRotation()
    scale: Gf.Vec3d = Gf.Vec3d(*(v.GetLength() for v in world_transform.ExtractRotationMatrix()))
    return translation, rotation, scale


def get_material_references(prim):
    refs = set()
    for attribute in prim.GetAttributes():
        try:
            attr = attribute.Get()
            material_ref = attr.path  # Or .path
            refs.add(material_ref)
        except AttributeError:
            pass
    return refs


def get_material_references_recursive(prim):
    refs = set()
    refs.update(get_material_references(prim))
    for child in prim.GetChildren():
        refs.update(get_material_references_recursive(child))
    return refs


def get_mdl_refs(path):
    # TODO: Add proper MDL procesing
    if path.startswith("omniverse://"):
        status, _, content = omni.client.read_file(path)
        text = str(memoryview(content), "utf8")
    else:
        try:
            with open(path, "r") as f:
                text = f.read()
        except FileNotFoundError:
            logger.warning("%s not found", path)
            return []
    strings = re.findall(r'(?:")((?:[\w:/]+/)?[\w.-]+\.(?:jpg|png|tiff|hdr|mdl|hlsl|exe))(?:")', text)
    return strings


indexed_property_prefixes = os.getenv("INDEXED_PROPERTY_PREFIXES", "semantic:").split(",")
indexed_properties = os.getenv("INDEXED_PROPERTIES", "").split(",")


def get_semantic_label_through_api(prim) -> Dict[str, str]:
    import Semantics

    semantic_data: Dict[str, List[str]] = {}
    semantic_names = []
    for prop in prim.GetProperties():
        if Semantics.SemanticsAPI.IsSemanticsAPIPath(prop.GetPath()):
            s_name = prop.SplitName()[1]
            semantic_names.append(s_name)

    for sem_name in semantic_names:
        try:
            sem = Semantics.SemanticsAPI
            p_sem = sem.Get(prim, sem_name)
            # The semantic labels may not be present even if the API is declared
            type_attr = p_sem.GetSemanticTypeAttr()
            data_attr = p_sem.GetSemanticDataAttr()
            if type_attr.IsAuthored() and data_attr.IsAuthored():
                semantic_data[type_attr.Get()] = semantic_data.get(type_attr.Get(), []) + [data_attr.Get()]
        except Exception as e:
            logger.warning("Error processing semantic label %s: %s", sem_name, e)

    return {key: ",".join(list(set(value))) for key, value in semantic_data.items()}


def get_physics_properties_through_api(prim: Usd.Prim, prefix: str = "physics:") -> Dict[str, str]:
    from pxr import UsdPhysics

    physics_data: Dict[str, str] = {}
    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
        for attr in prim.GetAttributes():
            attr_name = attr.GetName()
            if attr_name.startswith(prefix):
                physics_data[attr_name[len(prefix) :]] = str(attr.Get())
    return physics_data


def get_defined_attribute(prim, attribute_name):
    if prim.GetAttribute(attribute_name).IsDefined():
        return prim.GetAttribute(attribute_name).Get()

    return None


def get_camera_properties(prim: Usd.Prim) -> Dict[str, str]:
    return {
        "focalLength": str(get_defined_attribute(prim, "focalLength")),
        "horizontalAperture": str(get_defined_attribute(prim, "horizontalAperture")),
        "verticalAperture": str(get_defined_attribute(prim, "verticalAperture")),
        "clippingRange": str(list(get_defined_attribute(prim, "clippingRange"))),
    }


def count_geometry(prim: Usd.Prim) -> Dict[str, int]:
    """
    Count the number of polygons, points, and curve segments in a geometry prim.

    Args:
        prim: USD Prim to analyze for geometry counts

    Returns:
        Dictionary with keys:
            - polygon_count: Number of mesh polygons/faces (plus points/curves if flags enabled)
            - point_count: Number of points (only for Points prims, 0 otherwise)
            - curve_segment_count: Number of curve segments (only for Curves prims, 0 otherwise)
    """
    mesh_polygon_count = 0
    point_count = 0
    curve_segment_count = 0

    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)

        # Get face vertex counts to determine polygon count
        face_vertex_counts_attr = mesh.GetFaceVertexCountsAttr()
        if face_vertex_counts_attr and face_vertex_counts_attr.HasValue():
            face_vertex_counts = face_vertex_counts_attr.Get()
            if face_vertex_counts:
                mesh_polygon_count = len(face_vertex_counts)

    elif prim.IsA(UsdGeom.Curves):
        curves = UsdGeom.Curves(prim)

        # For curves, count each curve segment
        curve_vertex_counts_attr = curves.GetCurveVertexCountsAttr()
        if curve_vertex_counts_attr and curve_vertex_counts_attr.HasValue():
            curve_vertex_counts = curve_vertex_counts_attr.Get()
            if curve_vertex_counts:
                curve_segment_count = len(curve_vertex_counts)

    elif prim.IsA(UsdGeom.Points):
        points = UsdGeom.Points(prim)

        # For points, count each point
        points_attr = points.GetPointsAttr()
        if points_attr and points_attr.HasValue():
            points_data = points_attr.Get()
            if points_data:
                point_count = len(points_data)

    # Calculate polygon_count based on flags
    polygon_count = mesh_polygon_count
    if COUNT_CURVE_SEGMENTS_AS_POLYGONS:
        polygon_count += curve_segment_count
    if COUNT_POINTS_AS_POLYGONS:
        polygon_count += point_count

    return {
        "polygon_count": polygon_count,
        "point_count": point_count,
        "curve_segment_count": curve_segment_count,
    }


def get_prim_properties(prim: Usd.Prim, stage: Usd.Stage) -> Dict[str, str]:
    properties: Dict[str, str] = {}
    for property_name in prim.GetPropertyNames():
        if property_name in indexed_properties or any(
            property_name.startswith(prefix) for prefix in indexed_property_prefixes
        ):
            prop = prim.GetProperty(property_name)
            if isinstance(prop, Usd.Attribute):
                property = get_defined_attribute(prim, property_name)
                if property:
                    properties[property_name] = str(property)
            elif isinstance(prop, Usd.Relationship):
                relationship_targets = prop.GetTargets()
                if len(relationship_targets) > 0:
                    properties[property_name] = ",".join([str(target) for target in relationship_targets])
            else:
                logger.warning(
                    "property type: '%s' for property name: '%s' is not supported", type(prop), property_name
                )

    if prim.GetTypeName() == "Camera":
        properties.update(get_camera_properties(prim))

    if USE_SEMANTICS_API:
        try:
            for key, value in get_semantic_label_through_api(prim=prim).items():
                if key in properties:
                    properties[key] = f"{properties[key]},{value}"
                else:
                    properties[key] = value
        except Exception as e:
            logger.warning("Error processing semantic labels: %s", e)

    if USE_PHYSICS_API:
        try:
            for key, value in get_physics_properties_through_api(prim=prim).items():
                if key in properties:
                    properties[key] = f"{properties[key]},{value}"
                else:
                    properties[key] = value
        except Exception as e:
            logger.warning("Error processing physics properties: %s", e)
    return properties


def process_prim_asset_reference_url(asset_path, layer: Sdf.Layer):
    if (
        asset_path.assetPath.startswith("omniverse://")
        or asset_path.assetPath.startswith("https://")
        or asset_path.assetPath.startswith("http://")
    ):
        return str(asset_path.assetPath)
    else:
        return normalize_url(get_base_path(unquote(str(layer.realPath))) + "/" + str(asset_path.assetPath))


@timing_decorator
def traverse(stage: Usd.Stage, scene_url: str):
    all_references = set()
    material_references = set()
    path_to_prim = defaultdict(list)
    prims: dict[str, dict] = defaultdict(dict)

    for prim in stage.Traverse():
        prim_references = []
        prim_path = str(prim.GetPath())
        prim_type = str(prim.GetTypeName())
        prim_parent = str(prim.GetParent().GetPath())

        # get translate and scale transformed to world coordinates
        translate, _, scale = get_world_transform_xform(prim)

        # get rotation (order can be different for each prim)
        rotation_order_permutations = ["".join(p) for p in list(permutations(["X", "Y", "Z"]))]
        for rotation_order in rotation_order_permutations:
            rotate = get_defined_attribute(prim, f"xformOp:rotate{rotation_order}")
            if rotate is not None:
                break

        # count geometry (polygons, points, curve segments) for geometry prims
        geometry_counts = count_geometry(prim)

        # compute bbox once and reuse (handles empty ranges from incomplete prims)
        bbox = compute_bbox(prim)
        bbox_is_valid = not bbox.IsEmpty()

        # For invalid/empty bboxes, use +/- FLT_MAX as infinity sentinel values
        bbox_infinity_min = [-GF_FLT_MAX, -GF_FLT_MAX, -GF_FLT_MAX]
        bbox_infinity_max = [GF_FLT_MAX, GF_FLT_MAX, GF_FLT_MAX]

        prim_data = {
            "scene_url": scene_url,
            "usd_path": prim_path,
            "parent": prim_parent,
            "prim_type": prim_type,
            "properties": get_prim_properties(prim, stage),
            "translate": list(translate) if translate else None,
            "scale_x": scale[0] if scale else None,
            "scale_y": scale[1] if scale else None,
            "scale_z": scale[2] if scale else None,
            "rotate_x": rotate[0] if rotate else None,
            "rotate_y": rotate[1] if rotate else None,
            "rotate_z": rotate[2] if rotate else None,
            "bbox_max": list(bbox.GetMax()) if bbox_is_valid else bbox_infinity_max,
            "bbox_min": list(bbox.GetMin()) if bbox_is_valid else bbox_infinity_min,
            "bbox_midpoint": list(bbox.GetMidpoint()) if bbox_is_valid else [0, 0, 0],
            "polygon_count": geometry_counts["polygon_count"],
        }
        # Only add point_count and curve_segment_count if they are > 0
        if geometry_counts["point_count"] > 0:
            prim_data["point_count"] = geometry_counts["point_count"]
        if geometry_counts["curve_segment_count"] > 0:
            prim_data["curve_segment_count"] = geometry_counts["curve_segment_count"]

        prims[prim_path].update(prim_data)

        for prim_spec in prim.GetPrimStack():
            if prim_spec.hasReferences:
                references = prim_spec.referenceList.GetAddedOrExplicitItems()
                for r in references:
                    prim_references.extend(r.assetPath)
                    path_to_prim[str(r.assetPath)].append(prim)
                    # TODO: Handle cases with multiple references
                    asset_path, layer = omni.usd.get_composed_references_from_prim(prim)[0]
                    prims[prim_path]["source_asset_url"] = process_prim_asset_reference_url(asset_path, layer)

            if prim_spec.hasPayloads:
                payloads = prim_spec.payloadList.GetAddedOrExplicitItems()
                for r in payloads:
                    prim_references.extend(r.assetPath)
                    path_to_prim[str(r.assetPath)].append(prim)
                    # TODO: Handle cases with multiple references
                    asset_path, layer = omni.usd.get_composed_payloads_from_prim(prim)[0]
                    prims[prim_path]["source_asset_url"] = process_prim_asset_reference_url(asset_path, layer)

        all_references.update([p for p in prim_references])
        all_references.update(get_material_references(prim))
        material_references.update(get_material_references(prim))

    return all_references, path_to_prim, prims


class RelationshipType(str, Enum):
    USD_EXTERNAL_REFERENCE = "USD_EXTERNAL_REFERENCE"
    MDL_REFERENCE = "MDL_REFERENCE"
    MATERIAL_REFERENCE = "MATERIAL_REFERENCE"
    PARENT_PRIM = "PARENT_PRIM"


@timing_decorator
def traverse_recursive(fname, path_to_prim):
    files = set()
    relationships = []

    files.add(fname)

    files_visited = set()

    @lru_cache(maxsize=None)
    def _traverse_recursive(fname):
        if fname in files_visited:
            # Circular dependency
            logger.warning("Circular dependency: %s", fname)
            return {}
        files_visited.add(fname)
        deps = {}

        # check if the layer exists and if not - return directly
        try:
            layer = Sdf.Layer.FindOrOpen(fname)
            if layer is None:
                return deps
        except Exception as e:
            logger.warning("Error opening layer: %s", e)
            return deps

        for dep_list in UsdUtils.ExtractExternalReferences(fname):
            for dep in dep_list:
                if dep == fname:
                    continue
                if dep.startswith("omniverse://") or dep.startswith("https://") or dep.startswith("http://"):
                    dep_path = dep
                else:
                    dep_path = get_base_path(fname) + "/" + dep
                    dep_path = normalize_url(dep_path)
                files.add(dep_path)
                relationships.append((fname, dep_path, RelationshipType.USD_EXTERNAL_REFERENCE))

                deps[dep_path] = _traverse_recursive(dep_path)

        if fname.endswith(".mdl"):
            for ref in get_mdl_refs(fname):
                if ref not in deps:
                    dep_path = get_base_path(fname) + "/" + ref
                    dep_path = normalize_url(dep_path)
                    deps[dep_path] = {}
                    files.add(dep_path)
                    relationships.append((fname, dep_path, RelationshipType.MDL_REFERENCE))

        if fname in path_to_prim:
            material_refs = set()
            for prim in path_to_prim[fname]:
                # material_refs.update(get_material_references_recursive(prim))
                material_refs.update(get_material_references(prim))
            for ref in material_refs:
                ref = normalize_url(ref)
                files.add(ref)
                relationships.append((fname, ref, RelationshipType.MATERIAL_REFERENCE))
                if ref not in deps:
                    deps[ref] = {}

        return deps

    return {fname: _traverse_recursive(fname)}, files, relationships


def get_unique_refs(refs):
    unique_refs = set()

    def _flatten(d):
        unique_refs.update(d.keys())
        for k in d:
            _flatten(d[k])

    _flatten(refs)

    return unique_refs


def get_base_path(path):
    return path[: path.rfind("/")]


def normalize_url(url: str) -> str:
    url = url.replace("\\", "/")
    split_url = urllib.parse.urlsplit(url)
    path = str(Path(split_url[2]).resolve())
    return urllib.parse.urlunsplit((split_url[0], split_url[1], path, split_url[3], split_url[4]))


def get_simready_custom_layer_metadata(asset_path) -> dict:
    layer = Sdf.Layer.OpenAsAnonymous(asset_path, metadataOnly=True)
    sim_metadata = layer.customLayerData.get("SimReady_Metadata", {})
    return sim_metadata


def flatten_dict(d: dict, parent_key="", sep="__") -> dict:
    """
    Flatten a nested dictionary so that nested keys are concatenated
    using the specified separator.

    Example:
        Input: {"a": {"b": 1, "c": 2}, "d": 3}
        Output (with sep='__'): {"a__b": 1, "a__c": 2, "d": 3}
    """
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def storage_api_registration() -> Optional[Any]:
    """Register with the Storage API using omni.client direct registration.

    OMNI_STORAGE_AUTHORIZATION header injection via env var is broken since
    omni.client 2.68.0; register_storage_direct_with_callback is the fix.
    The returned request object must be kept alive for the duration of the
    script — dropping it tears down the connection.
    """
    if os.getenv("STORAGE_API_URL", "") == "":
        return None

    def on_registered(result, addresses):
        if result == omni.client.Result.OK:
            logger.info("Storage API registered successfully with addresses: %s", addresses)
        else:
            logger.error("Storage API registration failed: %s", result)

    url = os.getenv("STORAGE_API_URL")

    headers = {"Authorization": os.getenv("OMNI_STORAGE_AUTHORIZATION", "")}
    request = omni.client.register_storage_direct_with_callback(url, headers, on_registered)
    request.wait()
    return request


if __name__ == "__main__":
    # Apply the shared logging.yml config (honors LOGGING_CONFIG) so this Kit
    # --exec script logs consistently with the rest of the service.
    setup_logging()

    # Must be assigned (not discarded) — dropping the object closes the connection.
    _storage_api_request = storage_api_registration()

    fname = os.getenv("USD_URL")
    start_time = time.time()

    logger.info("Loading stage %s...", fname)
    stage = Usd.Stage.Open(fname)
    duration_ms = (time.time() - start_time) * 1000
    logger.info("Stage opened in %.2fms", duration_ms)

    _, path_to_prim, prims = traverse(stage, fname)
    refs, files, relationships = traverse_recursive(fname, path_to_prim)

    default_prim = stage.GetDefaultPrim()
    if default_prim:
        default_prim_path = str(default_prim.GetPath())
    else:
        default_prim_path = None

    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    scene_up_axis = UsdGeom.GetStageUpAxis(stage)

    simready_custom_layer_data = {
        f"simready_metadata_{k}": v for k, v in flatten_dict(get_simready_custom_layer_metadata(fname)).items()
    }

    if default_prim_path:
        prims[default_prim_path]["properties"].update(simready_custom_layer_data)

    dependency_relationships = [
        {"node_1_url": rel[0], "node_2_url": rel[1], "type": "depends_on"} for rel in relationships
    ]

    # Calculate total counts across all prims
    total_polygon_count = sum(prim_data.get("polygon_count", 0) for prim_data in prims.values())
    total_point_count = sum(prim_data.get("point_count", 0) for prim_data in prims.values())
    total_curve_segment_count = sum(prim_data.get("curve_segment_count", 0) for prim_data in prims.values())

    # Add polygon count to root prim properties if enabled
    if INCLUDE_POLYGON_COUNT_IN_USD_PROPERTIES and default_prim_path:
        if "properties" not in prims[default_prim_path]:
            prims[default_prim_path]["properties"] = {}
        prims[default_prim_path]["properties"]["__polygon_count"] = str(total_polygon_count)

    output = {
        "scene_url": fname,
        "default_prim_path": default_prim_path,
        "scene_mpu": scene_mpu,
        "scene_up_axis": scene_up_axis,
        "total_polygon_count": total_polygon_count,
        "total_point_count": total_point_count,
        "total_curve_segment_count": total_curve_segment_count,
        "assets": [{"url": url} for url in files],
        "asset_relationships": dependency_relationships,
        "prims": prims,
    }

    # Guard the dump: json.dumps(indent=4) over the whole graph is expensive and
    # would otherwise run on every build regardless of the configured log level.
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Graph output:\n%s", json.dumps(output, indent=4))

    unique_refs = get_unique_refs(refs)
    logger.info("Unique references count: %d", len(unique_refs))
    logger.info("Prims count: %d", len(prims))
    logger.info("Total polygon count: %d", total_polygon_count)
    logger.info("Total point count: %d", total_point_count)
    logger.info("Total curve segment count: %d", total_curve_segment_count)

    output_path = os.getenv("OUTPUT_PATH", "./output.json")
    logger.info("Output saved to %s", output_path)

    with open(output_path, "w+") as file:
        json.dump(
            output,
            file,
        )
