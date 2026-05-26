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

from cache.src.client.redis import CacheClientRedis
from fastapi import APIRouter, Request

from search_utils.storage_client import StorageClient

from .models import HealthResponse, HealthStatus

router = APIRouter(
    prefix="/health",
)


@router.get("/healthz", tags=["Health"], include_in_schema=False)
async def healthz(request: Request) -> HealthResponse:
    cache_client: CacheClientRedis = request.app.cache_client
    storage_client: StorageClient = request.app.storage_client

    await cache_client._connection.ping()

    if not await storage_client.check_connection():
        raise ConnectionError("Storage client is unavailable")

    return HealthResponse(status=HealthStatus.healthy)
