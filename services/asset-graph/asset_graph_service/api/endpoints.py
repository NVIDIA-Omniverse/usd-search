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
from collections import Counter
from typing import Annotated, Any, List, Optional

from asset_graph_service.api import dependencies
from asset_graph_service.api.auth import filter_objects
from asset_graph_service.api.exceptions import (
    AssetNotFoundError,
    PrimNotFoundError,
    SceneNotFoundError,
)
from asset_graph_service.api.models import (
    MatrixField,
    SceneSummaryResponse,
    SpatialQueryResponseItem,
    UpdateDependencyGraphRequest,
)
from asset_graph_service.db import Asset, BaseGraphDB, Prim, USDAsset
from asset_graph_service.db.models import AssetGraph
from asset_graph_service.vector_utils import get_transformed_vector
from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from ..db.models import PropertiesFilter, PropertiesFilterRelation

api_v1_router = APIRouter()

logger = logging.getLogger(__name__)


class QueryParamValueError(ValueError):
    pass


class CommonPrimFilter(BaseModel):
    prim_type: Optional[list[str]] = Field(
        Query(
            default=None,
            description="Retrieve prims of the specified types.",
            openapi_examples={
                "Any": {"summary": "Any prim type", "value": None},
                "Xform": {"summary": "Xform prim type", "value": ["Xform"]},
                "Xform and Mesh": {
                    "summary": "Xform and Mesh prim types",
                    "value": ["Xform", "Mesh"],
                },
            },
        )
    )
    usd_path_prefix: Optional[str] = Field(
        Query(
            default=None,
            description="Retrieve prims with USD paths that begin with this prefix (i.e., the children of the prim at the specified path).",
            openapi_examples={
                "Any": {"summary": "Any USD path", "value": None},
                "/Root": {"summary": "Root prim", "value": "/Root"},
                "/Root/Car": {"summary": "/Root/Car", "value": "/Root/Car"},
            },
        )
    )
    properties_filter: Optional[str] = Field(
        Query(
            default=None,
            description="Filter prims based on USD attributes (note: only a subset of attributes configured in the indexing service is available). Format: `attribute1=abc,attribute2=456`",
            openapi_examples={
                "Any": {"summary": "Any attribute", "value": None},
                "class=lamp": {
                    "summary": "Prims labeled class=lamp",
                    "value": "class=lamp",
                },
            },
        )
    )
    min_bbox_dimension_x: Optional[float] = Field(
        Query(default=None, description="Minimum bounding box X dimension", ge=0)
    )
    min_bbox_dimension_y: Optional[float] = Field(
        Query(default=None, description="Minimum bounding box Y dimension", ge=0)
    )
    min_bbox_dimension_z: Optional[float] = Field(
        Query(default=None, description="Minimum bounding box Z dimension", ge=0)
    )
    max_bbox_dimension_x: Optional[float] = Field(Query(default=None, description="Max bounding box X dimension", gt=0))
    max_bbox_dimension_y: Optional[float] = Field(Query(default=None, description="Max bounding box Y dimension", gt=0))
    max_bbox_dimension_z: Optional[float] = Field(Query(default=None, description="Max bounding box Z dimension", gt=0))
    # TODO: @rafal, do you think this is an Ok assumption to have here, as I think this filter will be mostly used in general searches
    use_scaled_bbox_dimensions: Optional[bool] = Field(
        Query(
            default=True,
            description="Search in the space of MPU aligned bbox dimensions",
        )
    )

    @field_validator("properties_filter")
    def validate_properties_filter(cls, v):
        if v is None:
            return v
        parts = v.split(",")
        for part in parts:
            # Check for any valid operator: =~, >=, <=, =, >, <
            has_operator = "=" in part or ">" in part or "<" in part
            if not has_operator:
                raise QueryParamValueError(
                    "Each attribute must be in the format 'key=value' or 'key>value' or 'key<value'."
                )
            # Parse operator and validate key/value
            for op in ["=~", ">=", "<=", "=", ">", "<"]:
                if op in part:
                    key, value = part.split(op, 1)
                    if not key or not value:
                        raise QueryParamValueError("Both key and value must be non-empty.")
                    break
        return v

    @staticmethod
    def _parse_filter_value(value: str) -> str | bool:
        """Parse filter value, converting boolean strings to actual booleans."""
        if value.lower() == "true":
            return True
        elif value.lower() == "false":
            return False
        return value

    @property
    def properties(self) -> Optional[List[PropertiesFilter]]:
        if self.properties_filter is None:
            return None
        properties_filters = self.properties_filter.split(",")

        # support for equal, almost equal, and numeric comparison functionality
        properties_filter_list: List[PropertiesFilter] = []
        for f in properties_filters:
            # Check operators in order of specificity (longer operators first)
            if ">=" in f:
                property_split = f.split(">=", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=property_split[1],
                        relation=PropertiesFilterRelation.greater_equal,
                    )
                )
            elif "<=" in f:
                property_split = f.split("<=", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=property_split[1],
                        relation=PropertiesFilterRelation.less_equal,
                    )
                )
            elif "=~" in f:
                property_split = f.split("=~", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=property_split[1],
                        relation=PropertiesFilterRelation.almost_equals,
                    )
                )
            elif ">" in f:
                property_split = f.split(">", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=property_split[1],
                        relation=PropertiesFilterRelation.greater_than,
                    )
                )
            elif "<" in f:
                property_split = f.split("<", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=property_split[1],
                        relation=PropertiesFilterRelation.less_than,
                    )
                )
            elif "=" in f:
                property_split = f.split("=", 1)
                properties_filter_list.append(
                    PropertiesFilter(
                        key=property_split[0],
                        value=self._parse_filter_value(property_split[1]),
                        relation=PropertiesFilterRelation.equals,
                    )
                )

        return properties_filter_list


class CommonPrimFilterBoundedBbox(CommonPrimFilter):
    # For spatial queries we use a default bbox size limit to filter out prims with infinite size, like materials etc.
    max_bbox_dimension_x: Optional[float] = Field(Query(default=4e38, description="Max bounding box X dimension", ge=0))
    max_bbox_dimension_y: Optional[float] = Field(Query(default=4e38, description="Max bounding box Y dimension", ge=0))
    max_bbox_dimension_z: Optional[float] = Field(Query(default=4e38, description="Max bounding box Z dimension", ge=0))
    # as bounding box query is typically used for in-scene search - change the default setting here to False to search using the scene units
    use_scaled_bbox_dimensions: Optional[bool] = Field(
        Query(
            default=False,
            description="Search in the space of aligned bbox dimensions",
        )
    )


@api_v1_router.delete("/asset_graph/", tags=["Internal"], include_in_schema=False)
async def mark_asset_as_deleted(
    url: str,
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
) -> None:
    """
    Mark asset as deleted. If asset has no dependencies, it is removed from the graph. Otherwise, it is marked as deleted.
    """
    rev_dependencies = await database.get_inverse_asset_dependencies_flat(url, limit=1)
    if rev_dependencies:
        logger.info(
            "Delete request for %s. Asset is still referenced in other scenes, will only be marked as deleted.",
            url,
        )
        await database.mark_assets_as_deleted([url])
    else:
        logger.info(
            "Delete request for %s. Asset is not used in other scenes; deleting permanently.",
            url,
        )
        await database.delete_assets([url])
    # TODO: Delete prims


@api_v1_router.post("/asset_graph/", tags=["Internal"], include_in_schema=False)
async def update_asset_graph(
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    body: UpdateDependencyGraphRequest,
) -> None:
    """
    Update asset graph. Assumes input graph is a result of a single scene traversal.
    """
    logger.info(
        "Update graph for %s, %s assets, %s asset relationships, %s prims",
        body.scene_url,
        len(body.assets),
        len(body.asset_relationships),
        len(body.prims),
    )
    for prim in body.prims.values():
        prim.clean_up_semantic_labels()
    scene_asset = next((a for a in body.assets if a.url == body.scene_url), None)
    if scene_asset:
        usd_scene_asset = USDAsset(
            **scene_asset.model_dump(),
            scene_mpu=body.scene_mpu,
            scene_up_axis=body.scene_up_axis,
        )
        body.assets.remove(scene_asset)
        body.assets.append(usd_scene_asset)
    await database.update_graph(
        body.assets,
        body.asset_relationships,
        list(body.prims.values()),
        body.scene_url or body.assets[0].url,
        body.default_prim_path,
    )


@api_v1_router.get(
    "/asset_graph/usd/prims/spatial",
    tags=["AGS Spatial Graph"],
    response_model_exclude_none=True,
)
async def get_prims_within_radius(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    prims_filter: Annotated[CommonPrimFilterBoundedBbox, Depends(CommonPrimFilterBoundedBbox)],
    scene_url: Annotated[str, Query(description="URL of the scene to search.")],
    radius: Annotated[float, Query(description="Radius of the proximity query", gt=0, allow_inf_nan=False)],
    center_prim_usd_path: Annotated[
        str,
        Query(description="USD path of the reference Prim. (Returned in results unless excluded by filters)"),
    ] = None,
    center_x: Annotated[float, Query(description="X coordinate of the query center.", allow_inf_nan=False)] = None,
    center_y: Annotated[float, Query(description="Y coordinate of the query center.", allow_inf_nan=False)] = None,
    center_z: Annotated[float, Query(description="Z coordinate of the query center.", allow_inf_nan=False)] = None,
    transformation_matrix: Annotated[
        str,
        Query(description="Transformation matrix for the vector space. By default does not apply any transformation."),
    ] = "1,0,0;0,1,0;0,0,1",
    limit: Annotated[int, Query(description="Page size", gt=0)] = 1000,
) -> list[SpatialQueryResponseItem]:
    """Find all objects near a point or another object within a USD scene.

    Use this endpoint when you need to answer spatial questions like "find all objects within 5 meters
    of the table" or "what's near coordinates (10, 0, 5) in this scene". Returns prims sorted by distance
    from the query center, including their bounding boxes, properties, and the direction vector to each result.

    Perform a spatial search within a scene to retrieve prims from a USD scene based on their proximity to a reference
    prim `center_prim_usd_path` or specific coordinates `[center_x, center_y, center_z]` within a specified `radius`.

    **Note:** You must specify either `center_prim_usd_path` or the coordinates `[center_x, center_y, center_z]`.

    Returns prim objects including: attributes, dimensions, and min, max, midpoint coordinates of the bounding box,
    distance from the query center, vector from the query center to the prim midpoint.

    If searching using `center_prim_usd_path` the center prim at `center_prim_usd_path` is included in the results
    (unless excluded by filters used).
    """
    verified_scene_url = await verify_access([scene_url])
    if not verified_scene_url:
        raise HTTPException(status_code=403, detail=f"Access denied to scene at {scene_url}")
    if not await database.get_prims(scene_url, limit=1):
        raise SceneNotFoundError(target=scene_url)
    if center_prim_usd_path:
        if not await database.get_prims(scene_url, usd_paths=[center_prim_usd_path], limit=1):
            raise PrimNotFoundError(target=center_prim_usd_path)
    MatrixField.model_validate(dict(transformation_matrix=transformation_matrix))
    reference_vector = [0, 0, 0]
    if center_prim_usd_path is not None and (center_z is None and center_y is None and center_x is None):
        results = await database.get_prims_within_radius_of_another_prim(
            scene_url=scene_url,
            center_prim_usd_path=center_prim_usd_path,
            radius=radius,
            usd_path_prefix=prims_filter.usd_path_prefix,
            properties=prims_filter.properties,
            limit=limit,
            min_bbox_dimension_x=prims_filter.min_bbox_dimension_x,
            min_bbox_dimension_y=prims_filter.min_bbox_dimension_y,
            min_bbox_dimension_z=prims_filter.min_bbox_dimension_z,
            max_bbox_dimension_x=prims_filter.max_bbox_dimension_x,
            max_bbox_dimension_y=prims_filter.max_bbox_dimension_y,
            max_bbox_dimension_z=prims_filter.max_bbox_dimension_z,
            prim_types=prims_filter.prim_type,
        )
        if results:
            reference_vector = results[0][0].bbox_midpoint
    elif center_z is not None and center_y is not None and center_x is not None:
        results = await database.get_prims_within_radius_of_a_point(
            scene_url=scene_url,
            center_x=center_x,
            center_y=center_y,
            center_z=center_z,
            radius=radius,
            usd_path_prefix=prims_filter.usd_path_prefix,
            properties=prims_filter.properties,
            limit=limit,
            min_bbox_dimension_x=prims_filter.min_bbox_dimension_x,
            min_bbox_dimension_y=prims_filter.min_bbox_dimension_y,
            min_bbox_dimension_z=prims_filter.min_bbox_dimension_z,
            max_bbox_dimension_x=prims_filter.max_bbox_dimension_x,
            max_bbox_dimension_y=prims_filter.max_bbox_dimension_y,
            max_bbox_dimension_z=prims_filter.max_bbox_dimension_z,
            prim_types=prims_filter.prim_type,
        )
        reference_vector = [center_x, center_y, center_z]
    else:
        return JSONResponse(
            status_code=422,
            content={
                "error": "Must specify either the reference prim `center_prim_usd_path` or the coordinates `[center_x, center_y, center_z]`"
            },
        )

    return [
        SpatialQueryResponseItem(
            prim=res[0],
            distance=res[1],
            vector=get_transformed_vector(
                reference_vector,
                [
                    res[0].bbox_midpoint[0],
                    res[0].bbox_midpoint[1],
                    res[0].bbox_midpoint[2],
                ],
                transformation_matrix=[
                    [float(num) for num in row.split(",")] for row in transformation_matrix.split(";")
                ],
            ),
        )
        for res in results
    ]


@api_v1_router.get(
    "/asset_graph/usd/prims/spatial_bbox",
    tags=["AGS Spatial Graph"],
    response_model_exclude_none=True,
)
async def get_prims_within_bounding_box(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    prims_filter: Annotated[CommonPrimFilterBoundedBbox, Depends(CommonPrimFilterBoundedBbox)],
    scene_url: Annotated[
        str,
        Query(
            description="Retrieve prims from the scene at specified URL.",
        ),
    ],
    min_bbox_x: Annotated[
        float,
        Query(description="Query bounding box minimum X", allow_inf_nan=False),
    ],
    min_bbox_y: Annotated[
        float,
        Query(description="Query bounding box minimum Y", allow_inf_nan=False),
    ],
    min_bbox_z: Annotated[
        float,
        Query(description="Query bounding box minimum Z", allow_inf_nan=False),
    ],
    max_bbox_x: Annotated[
        float,
        Query(description="Query bounding box maximum X", allow_inf_nan=False),
    ],
    max_bbox_y: Annotated[
        float,
        Query(description="Query bounding box maximum Y", allow_inf_nan=False),
    ],
    max_bbox_z: Annotated[
        float,
        Query(description="Query bounding box maximum Z", allow_inf_nan=False),
    ],
    limit: Annotated[
        int,
        Query(description="Page size", gt=0),
    ] = 1000,
) -> list[Prim]:
    """Find all objects within a rectangular region of a USD scene.

    Use this endpoint when you need to find objects in a specific area, e.g., "find all objects in
    the kitchen area" or "what's in the region between coordinates (0,0,0) and (10,5,10)".
    A prim is included if its bounding box midpoint falls within the query bounding box.

    The bounding box is defined by two corner points:
    [min_bbox_x, min_bbox_y, min_bbox_z] and [max_bbox_x, max_bbox_y, max_bbox_z].
    """
    verified_scene_url = await verify_access([scene_url])
    if not verified_scene_url:
        raise HTTPException(status_code=403, detail=f"Access denied to scene at {scene_url}")
    if not await database.get_prims(scene_url, limit=1):
        raise SceneNotFoundError(target=scene_url)
    results = await database.get_prims_within_bounding_box(
        scene_url=scene_url,
        usd_path_prefix=prims_filter.usd_path_prefix,
        properties=prims_filter.properties,
        limit=limit,
        min_bbox_dimension_x=prims_filter.min_bbox_dimension_x,
        min_bbox_dimension_y=prims_filter.min_bbox_dimension_y,
        min_bbox_dimension_z=prims_filter.min_bbox_dimension_z,
        max_bbox_dimension_x=prims_filter.max_bbox_dimension_x,
        max_bbox_dimension_y=prims_filter.max_bbox_dimension_y,
        max_bbox_dimension_z=prims_filter.max_bbox_dimension_z,
        prim_types=prims_filter.prim_type,
        min_bbox_x=min_bbox_x,
        min_bbox_y=min_bbox_y,
        min_bbox_z=min_bbox_z,
        max_bbox_x=max_bbox_x,
        max_bbox_y=max_bbox_y,
        max_bbox_z=max_bbox_z,
    )

    return results


@api_v1_router.get("/asset_graph/usd/prims", tags=["AGS Scene Graph"], response_model_exclude_none=True)
async def get_prims(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    prims_filter: Annotated[CommonPrimFilter, Depends(CommonPrimFilter)],
    scene_url: Annotated[
        str,
        Query(
            description="Retrieve prims from the scene at specified URL.",
        ),
    ] = None,
    usd_path: Annotated[
        list[str] | str,
        Query(
            description="Retrieve prims from the specified USD paths. Can provide either a single path or a list of paths.",
            openapi_examples={
                "Any": {"summary": "Any USD path", "value": None},
                "Root": {"summary": "Root prim", "value": ["/Root"]},
                "Multiple": {
                    "summary": "Multiple USD paths",
                    "value": ["Path1", "Path2", "Path3"],
                },
            },
        ),
    ] = None,
    root_prim: Annotated[
        bool,
        Query(
            description="Retrieve root prims. Note: combined with default_prim returns both root and default prims. Works as inclusive filter only; setting to false has no effect."
        ),
    ] = None,
    default_prim: Annotated[
        bool,
        Query(
            description="Retrieve default prims. Note: combined with root_prim returns both root and default prims. Works as inclusive filter only; setting to false has no effect."
        ),
    ] = None,
    source_asset_url: Annotated[
        str,
        Query(
            description="Filter prims based on their source asset URL, i.e. the asset they have a reference to",
        ),
    ] = None,
    limit: Annotated[int, Query(description="Page size", gt=0)] = 1000,
) -> list[Prim]:
    """Retrieve and filter prims from a USD scene — use for scene understanding and object enumeration.

    Use this endpoint when you need to understand what objects are in a scene, filter by type or properties,
    or retrieve specific prims by their USD path. Returns all matching prims with their locations, dimensions,
    and properties. Ideal for answering "what objects are in this scene?" or "find all Mesh prims with class=vehicle".

    NOTE: Calling without any parameters will return ALL prims. `scene_url` must be provided to fetch prims from the specified scene.

    A globally unique prim id consists of (`scene_url`, `usd_path`) tuple. `usd_path` is unique only within a single scene.
    To retrieve prims from a specified scene, `scene_url` must be set.
    To retrieve a single prim from a specified scene, provide both `scene_url` and `usd_path`.
    """
    if not await verify_access([scene_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to scene at {scene_url}")
    if not await database.get_prims(scene_url, limit=1):
        raise SceneNotFoundError(target=scene_url)
    results = await database.get_prims(
        scene_url=scene_url,
        usd_paths=usd_path,
        usd_path_prefix=prims_filter.usd_path_prefix,
        properties=prims_filter.properties,
        limit=limit,
        min_bbox_dimension_x=prims_filter.min_bbox_dimension_x,
        min_bbox_dimension_y=prims_filter.min_bbox_dimension_y,
        min_bbox_dimension_z=prims_filter.min_bbox_dimension_z,
        max_bbox_dimension_x=prims_filter.max_bbox_dimension_x,
        max_bbox_dimension_y=prims_filter.max_bbox_dimension_y,
        max_bbox_dimension_z=prims_filter.max_bbox_dimension_z,
        prim_types=prims_filter.prim_type,
        root_prim=root_prim,
        default_prim=default_prim,
        source_asset_url=source_asset_url,
        use_scaled_bbox_dimensions=prims_filter.use_scaled_bbox_dimensions,
    )

    return await filter_objects(verify_access, results, "scene_url")


@api_v1_router.get(
    "/asset_graph/usd/scene_summary/",
    tags=["AGS Scene Graph"],
    response_model_exclude_none=True,
)
async def scene_summary(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    scene_url: Annotated[
        str,
        Query(
            description="Scene summary.",
        ),
    ],
) -> SceneSummaryResponse:
    """Get a quick overview of scene contents — use before detailed spatial or prim queries.

    Use this endpoint to understand a scene's composition: how many prims, what types (Mesh, Xform, etc.),
    what properties are used, what assets are referenced, total polygon count, and scene metadata (MPU, up axis).
    Ideal first call when exploring an unfamiliar scene.
    """
    if not await verify_access([scene_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to scene at {scene_url}")
    if not await database.get_asset(scene_url):
        raise SceneNotFoundError(target=scene_url)
    prims = await database.get_prims(
        scene_url=scene_url,
        limit=10_000_000,
    )
    root_asset = await database.get_asset(scene_url)
    unique_property_keys = Counter()
    unique_properties = Counter()
    referenced_assets = Counter()
    prim_types = Counter()
    total_polygon_count = 0
    total_point_count = 0
    total_curve_segment_count = 0

    for prim in prims:
        prim_types[prim.prim_type] += 1
        total_polygon_count += prim.polygon_count
        total_point_count += prim.point_count or 0
        total_curve_segment_count += prim.curve_segment_count or 0
        if prim.properties:
            for key in prim.properties:
                unique_property_keys[key] += 1
                unique_properties[(key, prim.properties[key])] += 1
        if prim.source_asset_url:
            referenced_assets[prim.source_asset_url] += 1

    return SceneSummaryResponse(
        scene_url=scene_url,
        unique_property_keys=unique_property_keys,
        unique_properties=unique_properties,
        scene_mpu=getattr(root_asset, "scene_mpu", None) if root_asset else None,
        scene_up_axis=(getattr(root_asset, "scene_up_axis", None) if root_asset else None),
        prim_types=prim_types,
        n_prims=len(prims),
        total_polygon_count=total_polygon_count,
        total_point_count=total_point_count,
        total_curve_segment_count=total_curve_segment_count,
        referenced_assets=referenced_assets,
        default_prim=next((prim for prim in prims if prim.default_prim), None),
    )


@api_v1_router.get(
    "/dependency_graph/graph",
    tags=["AGS Asset Graph"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_graph(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    root_node_url: Annotated[
        str,
        Query(description="URL of the asset"),
    ],
    max_level: Annotated[
        int,
        Query(
            description="Max level of dependency tree traversal (by default unlimited)",
            gt=0,
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size", gt=0),
    ] = 1000,
) -> AssetGraph:
    """Get the full dependency tree of an asset as a graph — use to discover sub-assemblies, textures, and materials.

    Use this endpoint when you need to understand what files an asset references (e.g., "what textures does
    this car model use?" or "what sub-assets make up this scene?"). Returns nodes (assets) and directed edges
    (dependency relationships). Traverses references recursively up to max_level depth.
    """
    if not await verify_access([root_node_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to asset at {root_node_url}")
    if not await database.get_asset(root_node_url):
        raise AssetNotFoundError(target=root_node_url)
    dependency_graph = await database.get_asset_dependencies_graph(root_node_url, max_level=max_level, limit=limit)
    dependency_graph.nodes = await filter_objects(verify_access, dependency_graph.nodes, "url")
    dependency_graph.edges = await filter_objects(verify_access, dependency_graph.edges, ["node_1_url", "node_2_url"])
    return dependency_graph


@api_v1_router.get(
    "/dependency_graph/flat",
    tags=["AGS Asset Graph"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_flat(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    root_node_url: Annotated[
        str,
        Query(description="URL of the asset"),
    ],
    max_level: Annotated[
        int,
        Query(
            description="Max level of dependency tree traversal (by default unlimited)",
            gt=0,
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size", gt=0),
    ] = 1000,
) -> list[Asset]:
    """Get a flat list of all files an asset depends on — simpler alternative to the graph endpoint.

    Use this endpoint when you just need the list of referenced files without graph structure
    (e.g., "list all textures used by this model"). Returns Asset objects with URLs.
    For graph structure with edges, use GET /dependency_graph/graph instead.
    """
    if not await verify_access([root_node_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to asset at {root_node_url}")
    if not await database.get_asset(root_node_url):
        raise AssetNotFoundError(target=root_node_url)
    asset_dependencies = await database.get_asset_dependencies_flat(root_node_url, max_level=max_level, limit=limit)
    return await filter_objects(verify_access, asset_dependencies, "url")


@api_v1_router.get(
    "/dependency_graph/inverse/flat",
    tags=["AGS Asset Graph"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_inverse(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    root_node_url: Annotated[
        str,
        Query(description="URL of the asset"),
    ],
    max_level: Annotated[
        int,
        Query(
            description="Max level of dependency tree traversal (by default unlimited)",
            gt=0,
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size", gt=0),
    ] = 1000,
) -> list[Asset]:
    """Find which scenes or assets reference a given asset — use for impact analysis.

    Use this endpoint to answer "where is this asset used?" or "which scenes reference this texture?".
    Returns a flat list of all assets that depend on (reference) the specified asset.
    Useful for impact analysis before modifying or deleting an asset.
    """
    if not await verify_access([root_node_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to asset at {root_node_url}")
    if not await database.get_asset(root_node_url):
        raise AssetNotFoundError(target=root_node_url)
    asset_dependencies = await database.get_inverse_asset_dependencies_flat(
        root_node_url, max_level=max_level, limit=limit
    )
    return await filter_objects(verify_access, asset_dependencies, "url")


@api_v1_router.get(
    "/dependency_graph/inverse/graph",
    tags=["AGS Asset Graph"],
    response_model_exclude_defaults=True,
)
async def get_inverse_dependencies_graph(
    verify_access: Annotated[Any, Depends(dependencies.verify_access)],
    database: Annotated[BaseGraphDB, Depends(dependencies.database)],
    root_node_url: Annotated[
        str,
        Query(description="URL of the asset"),
    ],
    max_level: Annotated[
        int,
        Query(
            description="Max level of dependency tree traversal (by default unlimited)",
            gt=0,
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(description="Page size", gt=0),
    ] = 1000,
) -> AssetGraph:
    """Get the full reverse dependency graph — all assets that directly or transitively reference the specified asset.

    Use this endpoint for impact analysis with full graph structure (nodes + edges),
    e.g., "show me the full dependency chain of everything that uses this material".
    For a simpler flat list, use GET /dependency_graph/inverse/flat instead.
    """
    if not await verify_access([root_node_url]):
        raise HTTPException(status_code=403, detail=f"Access denied to asset at {root_node_url}")
    if not await database.get_asset(root_node_url):
        raise AssetNotFoundError(target=root_node_url)
    dependency_graph = await database.get_inverse_asset_dependencies_graph(
        root_node_url, max_level=max_level, limit=limit
    )
    dependency_graph.nodes = await filter_objects(verify_access, dependency_graph.nodes, "url")
    dependency_graph.edges = await filter_objects(verify_access, dependency_graph.edges, ["node_1_url", "node_2_url"])
    return dependency_graph
