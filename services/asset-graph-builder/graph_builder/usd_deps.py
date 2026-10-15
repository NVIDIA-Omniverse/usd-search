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
# On failure it writes {"error": {"reason", "message"}} to that same path and
# exits with the matching graph_builder.failures.BuilderExitCode, so the supervising
# service can report *why* a build failed. See graph_builder/failures.py.
#

import json
import logging
import os
import re
import sys
import time
import urllib.parse  # `import urllib` alone does not bind the `parse` submodule
from collections import defaultdict
from enum import Enum
from functools import lru_cache
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Standalone Omniverse storage client (packman ``client_library`` — the module
# is ``omni.client``). Present in the container image; absent in unit tests,
# which exercise only the URL-string helpers against a stubbed pxr.
try:
    import omni.client as _omni_client
except ImportError:
    _omni_client = None  # type: ignore[assignment]

from graph_builder import setup_logging
from graph_builder.failures import BuilderExitCode, GraphBuildReason
from graph_builder.prim_properties import (
    drop_incomplete_prims,
    merge_prim_properties,
    sanitize_bbox,
)
from graph_builder.redaction import redact_url
from graph_builder.sidecar_metadata import (
    BoundedCache,
    collect_sidecar_metadata,
    load_sidecar_config,
)
from graph_builder.timings import TimingRecorder
from pxr import Ar, Gf, Sdf, Usd, UsdGeom, UsdUtils

#: ``omni.usd`` (a Kit extension) is unavailable in the kitless runtime, so the
#: two composition helpers it provided are reimplemented on top of ``pxr`` below.

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


def _read_asset_bytes(url: str) -> Optional[bytes]:
    """Read an asset's raw bytes, resolving remote URLs through the USD resolver.

    Local paths are read directly; ``omniverse://``/``s3://``/``http(s)://`` go
    through the registered Omniverse AR resolver (``OpenAsset``), with the standalone
    client as a fallback when present. Returns None when the asset cannot be
    opened, which callers read as "nothing here".
    """
    if "://" not in url:
        try:
            with open(url, "rb") as handle:
                return handle.read()
        except (FileNotFoundError, OSError):
            return None

    resolver = Ar.GetResolver()
    resolved = resolver.Resolve(url)
    if resolved:
        asset = resolver.OpenAsset(resolved)
        if asset is not None:
            buffer = asset.GetBuffer()
            if buffer is not None:
                return bytes(buffer)

    if _omni_client is not None:
        status, _, content = _omni_client.read_file(url)
        if status == _omni_client.Result.OK:
            return bytes(memoryview(content))
    return None


def get_mdl_refs(path):
    # TODO: Add proper MDL procesing
    content = _read_asset_bytes(path)
    if content is None:
        logger.warning("%s not found", path)
        return []
    text = content.decode("utf8", errors="replace")
    strings = re.findall(r'(?:")((?:[\w:/]+/)?[\w.-]+\.(?:jpg|png|tiff|hdr|mdl|hlsl|exe))(?:")', text)
    return strings


indexed_property_prefixes = os.getenv("INDEXED_PROPERTY_PREFIXES", "semantic:").split(",")
indexed_properties = os.getenv("INDEXED_PROPERTIES", "").split(",")


#: Attribute-name shape of the legacy core ``Semantics.SemanticsAPI`` multi-apply
#: schema: one ``semantic:<instance>:params:semanticType`` /
#: ``:params:semanticData`` pair per applied instance.
_SEMANTIC_TYPE_SUFFIX = ":params:semanticType"
_SEMANTIC_DATA_SUFFIX = ":params:semanticData"


def get_semantic_label_through_api(prim) -> Dict[str, str]:
    """Read legacy ``Semantics.SemanticsAPI`` labels using pure ``pxr``.

    Kit's ``Semantics`` module is unavailable in the kitless runtime, so read the
    authored ``semantic:<instance>:params:semanticType``/``semanticData`` attribute
    pairs directly instead of going through the schema wrapper.
    """
    instances = [
        name[len("semantic:") : -len(_SEMANTIC_TYPE_SUFFIX)]
        for name in (attr.GetName() for attr in prim.GetAttributes())
        if name.startswith("semantic:") and name.endswith(_SEMANTIC_TYPE_SUFFIX)
    ]

    semantic_data: Dict[str, List[str]] = {}
    for instance in instances:
        try:
            type_attr = prim.GetAttribute(f"semantic:{instance}{_SEMANTIC_TYPE_SUFFIX}")
            data_attr = prim.GetAttribute(f"semantic:{instance}{_SEMANTIC_DATA_SUFFIX}")
            # The semantic labels may not be present even if the API is declared.
            if type_attr.IsAuthored() and data_attr.IsAuthored():
                semantic_data.setdefault(type_attr.Get(), []).append(data_attr.Get())
        except Exception as e:
            logger.warning("Error processing semantic label %s: %s", instance, e)

    return {key: ",".join(set(value)) for key, value in semantic_data.items()}


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


def _composed_arcs_from_prim(prim: Usd.Prim, arc: str) -> List[Tuple[Any, Sdf.Layer]]:
    """Authored reference/payload arcs on a prim, paired with the layer they live in.

    Kitless replacement for ``omni.usd.get_composed_references_from_prim`` /
    ``get_composed_payloads_from_prim``: walk the prim stack and pair each authored
    ``Sdf.Reference``/``Sdf.Payload`` (which carries ``.assetPath``) with its
    ``prim_spec.layer`` (which carries ``.realPath`` for anchoring relative paths).
    """
    arcs: List[Tuple[Any, Sdf.Layer]] = []
    for prim_spec in prim.GetPrimStack():
        item_list = prim_spec.referenceList if arc == "reference" else prim_spec.payloadList
        for item in item_list.GetAddedOrExplicitItems():
            arcs.append((item, prim_spec.layer))
    return arcs


def process_prim_asset_reference_url(asset_path, layer: Sdf.Layer):
    if (
        asset_path.assetPath.startswith("omniverse://")
        or asset_path.assetPath.startswith("https://")
        or asset_path.assetPath.startswith("http://")
    ):
        return graph_url(str(asset_path.assetPath))
    # Decode the joined URL, not just the layer's realPath: the authored assetPath
    # may be encoded too, and half-decoding is what produced two spellings per key.
    return graph_url(normalize_url(get_base_path(str(layer.realPath)) + "/" + str(asset_path.assetPath)))


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

        # compute bbox once and reuse; sanitize_bbox handles empty ranges (incomplete
        # prims) and non-finite coordinates (e.g. unbounded Volumes) by substituting
        # +/- FLT_MAX sentinels so AGS never sees a JSON `null` bbox coordinate.
        bbox = compute_bbox(prim)
        bbox_max, bbox_min, bbox_midpoint = sanitize_bbox(
            list(bbox.GetMax()), list(bbox.GetMin()), list(bbox.GetMidpoint()), bbox.IsEmpty()
        )

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
            "bbox_max": bbox_max,
            "bbox_min": bbox_min,
            "bbox_midpoint": bbox_midpoint,
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
                    asset_path, layer = _composed_arcs_from_prim(prim, "reference")[0]
                    prims[prim_path]["source_asset_url"] = process_prim_asset_reference_url(asset_path, layer)

            if prim_spec.hasPayloads:
                payloads = prim_spec.payloadList.GetAddedOrExplicitItems()
                for r in payloads:
                    prim_references.extend(r.assetPath)
                    path_to_prim[str(r.assetPath)].append(prim)
                    # TODO: Handle cases with multiple references
                    asset_path, layer = _composed_arcs_from_prim(prim, "payload")[0]
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

    root_identifier = fname

    # `fname` is a resolver identifier — the string Sdf/omni.client opens. What
    # goes into `files`/`relationships` is a graph key, which must match the object
    # key the crawler indexed. They differ when an authored path was percent-encoded,
    # so keep them apart: nothing decoded is ever handed back to the resolver.
    def key_for(identifier):
        """Graph key for a layer; the root keeps the caller's exact spelling.

        The root is the crawler's primary key for this scene and is looked up again
        by the same string, so re-spelling it would hide the scene from its owner.
        """
        return identifier if identifier == root_identifier else graph_url(identifier)

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

        source_key = key_for(fname)

        def _record(node_url, relationship_type):
            files.add(node_url)
            relationships.append((source_key, node_url, relationship_type))

        for dep_list in UsdUtils.ExtractExternalReferences(fname):
            for dep in dep_list:
                if dep == fname:
                    continue
                if is_search_path_module(dep):
                    # Resolved from the MDL search path, not a file next to the
                    # layer: recorded, but never anchored or descended into.
                    _record(search_path_uri(dep), RelationshipType.MDL_REFERENCE)
                    continue
                if dep.startswith("omniverse://") or dep.startswith("https://") or dep.startswith("http://"):
                    dep_path = dep
                else:
                    dep_path = get_base_path(fname) + "/" + dep
                    dep_path = normalize_url(dep_path)
                dep_key = graph_url(dep_path)
                _record(dep_key, RelationshipType.USD_EXTERNAL_REFERENCE)

                # Recurse on the identifier, key the result by the graph spelling.
                deps[dep_key] = _traverse_recursive(dep_path)

        if fname.endswith(".mdl"):
            for ref in get_mdl_refs(fname):
                if is_search_path_module(ref):
                    ref_key = search_path_uri(ref)
                    if ref_key not in deps:
                        deps[ref_key] = {}
                        _record(ref_key, RelationshipType.MDL_REFERENCE)
                    continue
                dep_key = graph_url(normalize_url(get_base_path(fname) + "/" + ref))
                if dep_key not in deps:
                    deps[dep_key] = {}
                    _record(dep_key, RelationshipType.MDL_REFERENCE)

        if fname in path_to_prim:
            material_refs = set()
            for prim in path_to_prim[fname]:
                # material_refs.update(get_material_references_recursive(prim))
                material_refs.update(get_material_references(prim))
            for ref in material_refs:
                ref_key = search_path_uri(ref) if is_search_path_module(ref) else graph_url(normalize_url(ref))
                _record(ref_key, RelationshipType.MATERIAL_REFERENCE)
                if ref_key not in deps:
                    deps[ref_key] = {}

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


#: Scheme for a dependency resolved from a search path rather than storage. Kept
#: in sync by hand with ``search_utils.asset_uri.SEARCH_PATH_SCHEMES`` — this
#: script runs in its own subprocess interpreter and cannot import the workspace
#: packages.
MDL_SCHEME = "mdl"

#: A leading scheme (``omniverse://``) or an explicit relative/absolute path
#: (``./``, ``../``, ``/``, ``\``). Anything else is a bare name.
_ANCHORED_ASSET_PATH = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*:|\.{0,2}[/\\])")


def is_search_path_module(asset_path: str) -> bool:
    """Whether an authored path names an MDL module resolved from a search path.

    MDL resolves through ``MDL_SYSTEM_PATH`` / ``MDL_USER_PATH``, not relative to
    the referencing layer, so anchoring a bare ``OmniPBR.mdl`` to the layer's
    directory invents a URL that never existed. The test is anchoring, not the
    absence of separators — ``nvidia/core_definitions.mdl`` is a search-path
    module, ``./x.mdl`` is a sibling file.

    MDL-only: a bare ``foo.usd`` *is* layer-relative, so the same rule applied to
    USD would drop real dependencies.
    """
    return asset_path.lower().endswith(".mdl") and not _ANCHORED_ASSET_PATH.match(asset_path)


def search_path_uri(asset_path: str) -> str:
    """The graph node URL for a search-path-resolved module."""
    return f"{MDL_SCHEME}:{asset_path}"


def graph_url(url: str) -> str:
    """The spelling the asset graph stores for a *derived* dependency URL.

    USD authors asset paths percent-encoded or not for the same file, so anchoring
    the authored text verbatim yields graph keys in two spellings, only one of
    which matches the object key the crawler indexed. Decode, so the graph agrees
    with the index. Root URLs are echoed verbatim — they are the caller's key.
    """
    if "%" not in url:
        return url
    split_url = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (split_url[0], split_url[1], urllib.parse.unquote(split_url[2]), split_url[3], split_url[4])
    )


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


#: Points at a sidecar_metadata.yaml catalog (see graph_builder/sidecar_metadata.py
#: and docs/plans/sidecar-package-metadata.md). Unset by default — the whole
#: mechanism is then a no-op, same as an unset USDSEARCH_LLM_PARSING_FIELDS_FILEPATH
#: falling back to "no extra field catalog". Loaded once per builder subprocess
#: invocation (this module is imported fresh for each subprocess run).
SIDECAR_METADATA_CONFIG_PATH = os.getenv("SIDECAR_METADATA_CONFIG_PATH")
_sidecar_metadata_config = load_sidecar_config(SIDECAR_METADATA_CONFIG_PATH)
# Avoids re-walking the same package directory tree, and re-reading/re-parsing
# the same package-level file, per asset (see the walk-semantics section of
# docs/plans/sidecar-package-metadata.md §2.2). Bounded so a process that sees
# many distinct packages over its lifetime does not grow these unboundedly.
_sidecar_package_root_cache: "BoundedCache[Tuple[str, str], Optional[str]]" = BoundedCache()
_sidecar_content_cache: "BoundedCache[str, Any]" = BoundedCache()


def _sidecar_read_bytes(url: str) -> Optional[bytes]:
    """Best-effort sidecar-file read: bytes on success, ``None`` on any failure.

    Mirrors ``get_mdl_refs``'s omniverse-vs-local dispatch above. Never raises —
    a missing or unreadable sidecar file is the expected common case (most
    assets are not part of a package), not a build error.
    """
    try:
        return _read_asset_bytes(url)
    except Exception:  # noqa: BLE001 — any backend-specific failure just means "not available"
        logger.debug("Could not read sidecar file %s", redact_url(url), exc_info=True)
        return None


def _sidecar_list_names(url: str) -> Optional[List[str]]:
    """Best-effort directory listing for glob-style sidecar filenames.

    Only used to resolve a `filename` pattern containing ``*`` (e.g. the
    SimReady conformance file's per-profile glob) — every other source reads
    a single, fully-resolved path via ``_sidecar_read_bytes`` alone.
    """
    try:
        if "://" in url:
            if _omni_client is None:
                return None
            status, entries = _omni_client.list(url)
            if status != _omni_client.Result.OK:
                return None
            return [entry.relative_path for entry in entries]
        return os.listdir(url)
    except (FileNotFoundError, OSError):
        return None
    except Exception:  # noqa: BLE001
        logger.debug("Could not list sidecar directory %s", redact_url(url), exc_info=True)
        return None


class ClassifiedFailure(Exception):
    """A failure this script could attribute to a specific cause.

    Carries both the ``reason`` written to the output file and the exit code the
    supervising service reads, so the two can never drift apart.
    """

    def __init__(self, message: str, reason: GraphBuildReason, exit_code: BuilderExitCode) -> None:
        super().__init__(message)
        self.reason = reason
        self.exit_code = exit_code


def _asset_not_found(fname: str) -> ClassifiedFailure:
    return ClassifiedFailure(
        f"Asset not found on the storage backend: {fname}",
        GraphBuildReason.asset_not_found,
        BuilderExitCode.asset_not_found,
    )


def _open_layer_failed(message: str) -> ClassifiedFailure:
    return ClassifiedFailure(message, GraphBuildReason.open_layer_failed, BuilderExitCode.open_layer_failed)


def classify_open_failure(fname: str, exc: Optional[BaseException] = None) -> ClassifiedFailure:
    """Work out *why* a stage would not open, by re-probing the URL.

    ``Usd.Stage.Open`` reports the same failure for an asset that is not there,
    one we are not allowed to read, and one whose layer is malformed — three
    problems with three completely different fixes. The standalone client's
    ``stat`` tells all three apart when it is present (matched on the result's
    *name*, since ``Result`` members move across client-library versions);
    otherwise the AR resolver only reveals whether the asset resolves at all.
    """
    detail = f": {exc}" if exc is not None else ""

    if _omni_client is not None:
        try:
            result, _ = _omni_client.stat(fname)
            result_name = str(result).upper()
        except Exception as stat_exc:  # noqa: BLE001 — diagnosis must never mask the real failure
            logger.warning("Could not stat %s while classifying an open failure: %s", fname, stat_exc)
            result_name = ""
        if "NOT_FOUND" in result_name:
            return _asset_not_found(fname)
        if any(token in result_name for token in ("ACCESS", "AUTH", "CONNECTION")):
            return ClassifiedFailure(
                f"Storage backend rejected the request for {fname} ({result_name})",
                GraphBuildReason.access_denied,
                BuilderExitCode.access_denied,
            )
        if result_name:
            return _open_layer_failed(f"Failed to open stage {fname} (stat: {result_name}){detail}")

    try:
        resolves = bool(Ar.GetResolver().Resolve(fname))
    except Exception:  # noqa: BLE001 — resolver failure is itself inconclusive
        resolves = True
    if not resolves:
        return _asset_not_found(fname)
    return _open_layer_failed(f"Failed to open stage {fname}{detail}")


def open_stage(fname: str) -> Usd.Stage:
    """Open a stage, or raise a :class:`ClassifiedFailure` explaining why not."""
    try:
        stage = Usd.Stage.Open(fname)
    except Exception as exc:  # noqa: BLE001 — pxr raises Tf.ErrorException; classify, do not swallow
        raise classify_open_failure(fname, exc) from exc
    if not stage:
        raise classify_open_failure(fname)
    return stage


def write_error(output_path: str, reason: GraphBuildReason, message: str) -> None:
    """Record a classified failure where the supervising service will find it."""
    with open(output_path, "w+", encoding="utf-8") as file:
        json.dump({"error": {"reason": reason.value, "message": message}}, file)


def register_usd_resolver() -> None:
    """Register the standalone Omniverse AR resolver so pxr resolves remote URLs.

    The image points ``OMNI_USD_RESOLVER_PLUGIN_PATH`` at the packman
    ``omni_usd_resolver`` plugin's ``resources`` directory (the one holding
    ``plugInfo.json``). Without it, ``pxr`` only resolves local paths. A no-op
    when unset, so local-file builds and unit tests need nothing.
    """
    plugin_path = os.getenv("OMNI_USD_RESOLVER_PLUGIN_PATH")
    if not plugin_path:
        return
    from pxr import Plug

    Plug.Registry().RegisterPlugins(plugin_path)
    logger.info("Registered Omniverse USD resolver from %s", plugin_path)


def build_graph_document(fname: str, timings: Optional[TimingRecorder] = None) -> Dict[str, Any]:
    """Build the asset-graph document for a single USD stage."""
    timings = timings or TimingRecorder(None)

    start_time = time.time()

    with timings.phase("resolver_registration"):
        register_usd_resolver()

    logger.info("Loading stage %s...", fname)
    with timings.phase("stage_open"):
        stage = open_stage(fname)
    duration_ms = (time.time() - start_time) * 1000
    logger.info("Stage opened in %.2fms", duration_ms)

    with timings.phase("traverse"):
        _, path_to_prim, prims = traverse(stage, fname)
    with timings.phase("traverse_recursive"):
        refs, files, relationships = traverse_recursive(fname, path_to_prim)

    default_prim = stage.GetDefaultPrim()
    if default_prim:
        default_prim_path = str(default_prim.GetPath())
    else:
        default_prim_path = None

    scene_mpu = UsdGeom.GetStageMetersPerUnit(stage)
    scene_up_axis = UsdGeom.GetStageUpAxis(stage)

    # SimReady custom-layer metadata can hold non-string leaves (bool/int/float/...).
    # Stringify so the merged prim "properties" stay Dict[str, str], matching every
    # other property path and the OpenSearch keyword fields downstream.
    simready_custom_layer_data = {
        f"simready_metadata_{k}": str(v) for k, v in flatten_dict(get_simready_custom_layer_metadata(fname)).items()
    }

    if default_prim_path:
        merge_prim_properties(prims, default_prim_path, simready_custom_layer_data)

    # Sidecar/package metadata (per-asset <stem>.json, package-level .metadata/*.json,
    # ...) — opt-in and config-driven (SIDECAR_METADATA_CONFIG_PATH), see
    # graph_builder/sidecar_metadata.py and docs/plans/sidecar-package-metadata.md.
    # A no-op when unconfigured, or when this asset simply isn't part of a package.
    sidecar_metadata = {
        k: str(v)
        for k, v in collect_sidecar_metadata(
            fname,
            config=_sidecar_metadata_config,
            read_fn=_sidecar_read_bytes,
            list_fn=_sidecar_list_names,
            package_root_cache=_sidecar_package_root_cache,
            content_cache=_sidecar_content_cache,
        ).items()
    }
    if default_prim_path and sidecar_metadata:
        merge_prim_properties(prims, default_prim_path, sidecar_metadata)

    dependency_relationships = [
        {"node_1_url": rel[0], "node_2_url": rel[1], "type": "depends_on"} for rel in relationships
    ]

    # Calculate total counts across all prims
    total_polygon_count = sum(prim_data.get("polygon_count", 0) for prim_data in prims.values())
    total_point_count = sum(prim_data.get("point_count", 0) for prim_data in prims.values())
    total_curve_segment_count = sum(prim_data.get("curve_segment_count", 0) for prim_data in prims.values())

    # Add polygon count to root prim properties if enabled
    if INCLUDE_POLYGON_COUNT_IN_USD_PROPERTIES and default_prim_path:
        merge_prim_properties(prims, default_prim_path, {"__polygon_count": str(total_polygon_count)})

    # Drop any prim that was never traversed (e.g. an `over` default prim that
    # merge_prim_properties auto-vivified) — it lacks the fields AGS requires and
    # would otherwise fail the whole graph write with a 422.
    for dropped_path in drop_incomplete_prims(prims):
        logger.warning("Dropping incomplete prim '%s' (not traversed, e.g. an `over`) for %s", dropped_path, fname)

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

    return output


if __name__ == "__main__":
    # Apply the shared logging.yml config (honors LOGGING_CONFIG) so this
    # subprocess script logs consistently with the rest of the service.
    setup_logging()

    usd_url = os.getenv("USD_URL")
    output_file_path = os.getenv("OUTPUT_PATH", "./output.json")

    # Timings go to their own file, flushed per phase, so a build that is killed
    # mid-traversal (OOM watchdog, timeout) still reports how far it got. The
    # graph document below is written only on success and cannot serve this.
    build_timings = TimingRecorder.from_env()
    build_timings.script_started()

    # Every exit from here on is classified: the reason goes to the output file
    # and the matching BuilderExitCode to the process status, so the supervising
    # service can report *why* a build failed rather than just that it did.
    try:
        graph_document = build_graph_document(usd_url, timings=build_timings)
    except ClassifiedFailure as failure:
        logger.error("Graph construction failed (%s): %s", failure.reason.value, failure)
        write_error(output_file_path, failure.reason, str(failure))
        sys.exit(failure.exit_code)
    except Exception as unexpected:  # noqa: BLE001 — the top-level boundary; nothing above it to catch
        logger.exception("Graph construction failed unexpectedly for %s", redact_url(usd_url))
        write_error(output_file_path, GraphBuildReason.internal_error, str(unexpected))
        sys.exit(BuilderExitCode.internal_error)

    logger.info("Output saved to %s", output_file_path)
    with open(output_file_path, "w+", encoding="utf-8") as file:
        json.dump(graph_document, file)
