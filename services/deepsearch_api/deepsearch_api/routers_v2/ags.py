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
from typing import Annotated, Optional

from asset_graph_service_client.api.ags_asset_graph_api import AGSAssetGraphApi
from asset_graph_service_client.api_client import ApiClient
from deepsearch_api.routers_v2 import dependencies, service
from deepsearch_api.routers_v2.ags_models import Asset, AssetGraph
from deepsearch_api.routers_v2.service import verify_access_for_asset_graph
from fastapi import APIRouter, Depends, Query

from search_utils.storage_client import StorageClient

router = APIRouter(
    prefix="/ags",
    tags=["v2_asset_graph_search"],
)

logger = logging.getLogger(__name__)

ENABLE_ACCESS_VERIFICATION = os.getenv("ENABLE_ACCESS_VERIFICATION", "true").lower() in ("true", "1")
logger.info(
    "Access verification for AGS APIs is %s",
    "enabled" if ENABLE_ACCESS_VERIFICATION else "disabled",
)


@router.get(
    "/dependency_graph/graph",
    tags=["v2_asset_graph_search"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_graph(
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    root_node_url: str = Query(description="URL of the asset"),
    max_level: Optional[int] = Query(
        default=None,
        description="Max level of dependency tree traversal (by default unlimited)",
        gt=0,
    ),
    limit: Optional[int] = Query(default=1000, description="Page size", gt=0),
) -> AssetGraph:
    """
    Get a graph of dependencies (unique files) for the specified asset.
    """
    dependency_graph = await AGSAssetGraphApi(
        api_client=async_ags_client
    ).get_dependencies_graph_dependency_graph_graph_get(root_node_url=root_node_url, max_level=max_level, limit=limit)
    if ENABLE_ACCESS_VERIFICATION:
        return await verify_access_for_asset_graph(dependency_graph, root_node_url, storage_client)
    else:
        return dependency_graph.to_dict()


@router.get(
    "/dependency_graph/flat",
    tags=["v2_asset_graph_search"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_flat(
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    root_node_url: str = Query(description="URL of the asset"),
    max_level: Optional[int] = Query(
        default=None,
        description="Max level of dependency tree traversal (by default unlimited)",
        gt=0,
    ),
    limit: Optional[int] = Query(default=1000, description="Page size", gt=0),
) -> list[Asset]:
    """
    Get a graph of dependencies (unique files) for the specified asset.
    """
    logger.debug(
        "Fetching from ags - get_dependencies_flat: root_node_url=%s, max_level=%s, limit=%s",
        root_node_url,
        max_level,
        limit,
    )
    asset_dependencies = await AGSAssetGraphApi(
        api_client=async_ags_client
    ).get_dependencies_flat_dependency_graph_flat_get(root_node_url=root_node_url, max_level=max_level, limit=limit)
    verified_urls = set(await service.check_acl([asset.url for asset in asset_dependencies], storage_client))
    return [
        Asset(**asset.to_dict())
        for asset in asset_dependencies
        if asset.url in verified_urls or not ENABLE_ACCESS_VERIFICATION
    ]


@router.get(
    "/dependency_graph/inverse/flat",
    tags=["v2_asset_graph_search"],
    response_model_exclude_defaults=True,
)
async def get_dependencies_inverse(
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    root_node_url: str = Query(description="URL of the asset"),
    max_level: Optional[int] = Query(
        default=None,
        description="Max level of dependency tree traversal (by default unlimited)",
        gt=0,
    ),
    limit: Optional[int] = Query(default=1000, description="Page size", gt=0),
) -> list[Asset]:
    """
    Get a graph of dependencies (unique files) for the specified asset.
    """
    logger.debug(
        "Fetching from ags - get_dependencies_inverse: root_node_url=%s, max_level=%s, limit=%s",
        root_node_url,
        max_level,
        limit,
    )
    asset_dependencies = await AGSAssetGraphApi(
        api_client=async_ags_client
    ).get_dependencies_inverse_dependency_graph_inverse_flat_get(
        root_node_url=root_node_url, max_level=max_level, limit=limit
    )
    verified_urls = set(await service.check_acl([asset.url for asset in asset_dependencies], storage_client))
    return [
        Asset(**asset.to_dict())
        for asset in asset_dependencies
        if asset.url in verified_urls or not ENABLE_ACCESS_VERIFICATION
    ]


@router.get(
    "/dependency_graph/inverse/graph",
    tags=["v2_asset_graph_search"],
    response_model_exclude_defaults=True,
)
async def get_inverse_dependencies_graph(
    async_ags_client: Annotated[ApiClient, Depends(dependencies.async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    root_node_url: str = Query(description="URL of the asset"),
    max_level: Optional[int] = Query(
        default=None,
        description="Max level of dependency tree traversal (by default unlimited)",
        gt=0,
    ),
    limit: Optional[int] = Query(default=1000, description="Page size", gt=0),
) -> AssetGraph:
    """
    Get a graph of all assets (unique files) that depend on the specified asset.
    """
    dependency_graph = await AGSAssetGraphApi(
        api_client=async_ags_client
    ).get_inverse_dependencies_graph_dependency_graph_inverse_graph_get(
        root_node_url=root_node_url, max_level=max_level, limit=limit
    )
    if ENABLE_ACCESS_VERIFICATION:
        return await verify_access_for_asset_graph(dependency_graph, root_node_url, storage_client)
    else:
        return dependency_graph.to_dict()
