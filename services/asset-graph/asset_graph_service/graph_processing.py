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

from asset_graph_service.db import BaseGraphDB, Prim
from asset_graph_service.db.models import Asset, AssetRelationship, EdgeType


async def upsert_graph(
    db: BaseGraphDB,
    nodes: list[Asset],
    relationships: list[AssetRelationship],
    prims: list[Prim],
):
    await db.upsert_asset_nodes(nodes)
    await db.upsert_asset_edges(relationships)
    await db.upsert_prims(prims)
