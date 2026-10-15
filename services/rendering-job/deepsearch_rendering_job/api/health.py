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

from fastapi import APIRouter, Request

from ..utils import TrackingSemaphore
from .models import HealthResponse, HealthStatus, ReadinessResponse, ReadinessStatus

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status=HealthStatus.OK)


@router.get("/readyz", response_model=ReadinessResponse)
async def readyz(
    fastapi_request: Request = None,
) -> ReadinessResponse:
    semaphore: TrackingSemaphore = fastapi_request.app.state.semaphore
    n_waiters = semaphore.waiters
    n_allowed = fastapi_request.app.state.worker_settings.n_allowed_waiting_requests
    if n_allowed < 0 or n_waiters <= n_allowed:
        return ReadinessResponse(status=ReadinessStatus.OK)
    return ReadinessResponse(
        status=ReadinessStatus.NOT_READY,
        reason=f"Too many waiting requests: {n_waiters} > {n_allowed}",
    )
