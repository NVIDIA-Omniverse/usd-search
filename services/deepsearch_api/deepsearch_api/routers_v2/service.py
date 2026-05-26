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
from typing import Any, List

from asset_graph_service_client.api.ags_scene_graph_api import AGSSceneGraphApi
from asset_graph_service_client.api_client import ApiClient
from asset_graph_service_client.models.prim import Prim as AGSClientPrim
from deepsearch_api.models import Prim
from deepsearch_api.routers_v2.ags_models import AssetGraph
from deepsearch_api.routers_v2.models import SearchResult
from deepsearch_api.tracing import trace
from deepsearch_api.utils import AsyncPoolExecutor
from fastapi import HTTPException
from httpx import HTTPStatusError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from search_utils.storage_client import (
    RemoteFileUri,
    StorageClient,
    VerifyBatchAccessResponse,
)
from search_utils.telemetry_utils import AsyncIteratorWrapper

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


async def check_acl(urls: list[RemoteFileUri], storage_client: StorageClient) -> list[str]:
    max_requests = 500

    results = []

    logger.debug("Checking ACLs for: %s", urls)
    res: list[VerifyBatchAccessResponse]
    async for res in AsyncIteratorWrapper(
        storage_client.batch_verify_access(
            uri_list=urls,
            max_nucleus_requests=max_requests,
        ),
        "batch_verify_access",
    ):
        logger.debug("ACL batch check raw results: %s", res)
        # TODO: r.exists id broken in nucleus - returns true for items that do not exist
        # TODO: verify that r.exists is =False when acl check fails
        results.extend([r.uri for r in res if r.exists])
        if logger.getEffectiveLevel() <= logging.DEBUG:
            for r in res:
                acl_ok = []
                acl_denied = []
                if not r.exists:
                    acl_denied.append(r.uri)
                else:
                    acl_ok.append(r.uri)
                logger.debug(
                    "ACL batch check results: \nallowed: %s \ndenied: %s",
                    acl_ok,
                    acl_denied,
                )

    logger.debug("ACL check results: %s", results)

    return results


@tracer.start_as_current_span("ags_verify_access_for_asset_graph")
async def verify_access_for_asset_graph(
    dependency_graph: AssetGraph, root_node_url: str, storage_client: StorageClient
) -> dict[str, Any]:
    all_urls = (
        set(asset.url for asset in dependency_graph.nodes)
        | set(edge.node_1_url for edge in dependency_graph.edges)
        | set(edge.node_2_url for edge in dependency_graph.edges)
        | {root_node_url}
    )
    verified_urls = set(await check_acl(list(all_urls), storage_client))
    logger.debug("Verified URLs: %s", verified_urls)
    if root_node_url not in verified_urls:
        raise HTTPException(status_code=404, detail=f"Asset {root_node_url} not found or access denied")
    dependency_graph_filtered = {"nodes": [], "edges": []}
    for node in dependency_graph.nodes:
        if node.url in verified_urls:
            dependency_graph_filtered["nodes"].append(node.to_dict())
    for edge in dependency_graph.edges:
        if edge.node_1_url in verified_urls and edge.node_2_url in verified_urls:
            dependency_graph_filtered["edges"].append(edge.to_dict())
    return dependency_graph_filtered


@tracer.start_as_current_span("ags_get_instance_prims_from_search_results")
async def get_instance_prims_from_search_results(
    search_results: list[SearchResult],
    scene_url: str,
    ags_client: ApiClient,
    asset_graph_service_n_retries: int,
    asset_graph_service_n_parallel_requests: int,
    **kwargs,
) -> list[SearchResult]:

    logger.debug(
        "Getting instance prims for search results: scene: %s; results: %s",
        scene_url,
        search_results,
    )
    prims: List[List[AGSClientPrim]] = await AsyncPoolExecutor(
        num_workers=asset_graph_service_n_parallel_requests
    ).run_tasks(
        [
            retry(
                retry=retry_if_exception_type(HTTPStatusError),
                stop=stop_after_attempt(asset_graph_service_n_retries),
                wait=wait_exponential_jitter(),
            )(AGSSceneGraphApi(api_client=ags_client).get_prims_asset_graph_usd_prims_get)(
                scene_url=scene_url, source_asset_url=result.url, **kwargs
            )
            for result in search_results
        ]
    )
    # TODO: As a potential performance optimization, we could consider using a single call to get_prims_asset_graph_usd_prims_get
    # and then parsing the data in memory.
    for result, instance_prims in zip(search_results, prims):
        result.in_scene_instance_prims = [Prim(**prim.model_dump()) for prim in instance_prims]

    return search_results
