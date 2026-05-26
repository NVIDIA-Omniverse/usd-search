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

import asyncio

from fastapi import APIRouter, Request

from .models import HealthResponse, HealthStatus, ReadinessResponse, ReadinessStatus

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(status=HealthStatus.OK)


@router.get("/readyz")
async def readyz(
    fastapi_request: Request = None,
) -> ReadinessResponse:
    kit_semaphore: asyncio.Semaphore = fastapi_request.app.state.semaphore
    n_waiters = len(kit_semaphore._waiters) if kit_semaphore._waiters is not None else 0
    if (
        fastapi_request.app.state.kit_worker_settings.n_allowed_waiting_requests < 0
        or n_waiters <= fastapi_request.app.state.kit_worker_settings.n_allowed_waiting_requests
    ):
        return ReadinessResponse(status=ReadinessStatus.OK)
    else:
        return ReadinessResponse(
            status=ReadinessStatus.NOT_READY,
            reason=f"Too many waiting requests: {n_waiters} > {fastapi_request.app.state.kit_worker_settings.n_allowed_waiting_requests}",
        )
