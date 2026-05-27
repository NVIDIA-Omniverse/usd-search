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
import json

import psutil
from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..models import RenderingServiceSettings
from ..render import kit_process_dict
from ..utils import update_waiting_requests_gauge
from .config import get_package_version
from .models import GeneralInfo, KitProcessInfo, WorkerInfo

router = APIRouter(tags=["info"])

rendering_service_settings = RenderingServiceSettings()


@router.get("/", response_model=GeneralInfo)
@router.get("/info", response_model=GeneralInfo)
async def general_info(fastapi_request: Request = None, pretty: bool = False):
    """
    Get information about the service. If `pretty` is True, the response will be formatted as a pretty JSON.

    includes the following information:
        - version: the version of the service
        - name: the name of the service
        - worker_info: information about the worker (see `WorkerInfo` model)
    """
    kit_semaphore: asyncio.Semaphore = fastapi_request.app.state.semaphore

    await update_waiting_requests_gauge(fastapi_request.app.state.semaphore)

    info = GeneralInfo(
        version=get_package_version(),
        name="USD Search Rendering Service",
        worker_info=WorkerInfo(
            active_requests=fastapi_request.app.state.kit_worker_settings.n_workers - kit_semaphore._value,
            max_requests=fastapi_request.app.state.kit_worker_settings.n_workers,
            waiting_requests=(len(kit_semaphore._waiters) if kit_semaphore._waiters is not None else 0),
            kit_processes=[
                KitProcessInfo(
                    worker_id=worker_info.worker_id,
                    pid=worker_info.pid,
                    memory_usage=psutil.Process(worker_info.pid).memory_info().rss / 1024 / 1024,
                    memory_limit=(
                        None
                        if rendering_service_settings.kit_worker_memory_limit <= 0
                        else rendering_service_settings.kit_worker_memory_limit
                    ),
                    memory_usage_percentage=(
                        int(
                            (
                                psutil.Process(worker_info.pid).memory_info().rss
                                / 1024
                                / 1024
                                / rendering_service_settings.kit_worker_memory_limit
                            )
                            * 1000
                        )
                        / 10
                        if rendering_service_settings.kit_worker_memory_limit > 0
                        else None
                    ),
                )
                for worker_info in kit_process_dict.values()
            ],
        ),
    )

    if pretty:
        content = json.dumps(info.dict(exclude_none=True), indent=2, ensure_ascii=False)
        return Response(content=content, media_type="application/json")

    return info
