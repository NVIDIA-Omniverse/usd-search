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
import logging
import os
import traceback
from contextlib import nullcontext
from typing import Any, Dict, List, Optional

from deepsearch_rendering_job.models import (
    Authentication,
    KitWorkerSettings,
    RenderingRequest,
    RenderingServiceSettings,
    StatusType,
)

from .auth import get_openid_token
from .exceptions import OutOfMemoryError, ProcessLimitReachedError, TimeoutError
from .transport import (
    ContentType,
    ResponsePayload,
    ResponseStatus,
    http_send,
    redis_send,
    ws_send,
)
from .utils import TrackingSemaphore, get_key, redact_url, update_waiting_requests_gauge

logger = logging.getLogger(__name__)


async def render_asset(
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    rendering_service_settings: RenderingServiceSettings = RenderingServiceSettings(),
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
) -> StatusType:  # pylint: disable=unused-argument
    """Render assets in an isolated worker process and forward each result over the transport."""
    if (
        (auth.storage_api_url or auth.storage_api_discovery_url)
        and not auth.storage_api_token
        and auth.storage_api_openid_client_id
    ):
        auth.storage_api_token = await get_openid_token(auth)

    logger.info("Rendering assets: %s", [redact_url(url) for url in request.url_list])

    render_settings = None
    if request.render_settings is not None:
        render_settings = request.render_settings.model_dump(exclude_none=True)
    if request.width is not None:
        render_settings = render_settings or {}
        render_settings["width"] = request.width
    if request.height is not None:
        render_settings = render_settings or {}
        render_settings["height"] = request.height

    url_overrides: List[str] = []
    url_hashes: List[str] = []
    path_overrides = getattr(request, "url_list_path_override", None)
    for it, url in enumerate(request.url_list):
        url_override = path_overrides[it] if path_overrides and it < len(path_overrides) else url
        url_overrides.append(url_override)
        url_hashes.append(get_key(url_override))

    per_asset_timeout = rendering_service_settings.asset_rendering_timeout
    # One child process per asset: ovrtx reuses a compiled remote MDL material (and its
    # texture URLs) for later assets in the same process, whatever the cache directory.
    for url, url_override, url_hash in zip(request.url_list, url_overrides, url_hashes):
        spec: Dict[str, Any] = {
            "urls": [url],
            "url_overrides": [url_override],
            "url_hashes": [url_hash],
            "render_settings": render_settings,
            "auth": auth,
            "per_asset_timeout": per_asset_timeout,
            "compress_payload": rendering_service_settings.payload_compression,
        }
        await _render_isolated(request, spec, rendering_service_settings)

    return StatusType.FINISHED


async def _send_result(request: RenderingRequest, payload: ResponsePayload, write_local: bool = True) -> None:
    """Forward one result over every transport configured on ``request``, failing if any of them fails."""
    failures: List[str] = []
    for name, endpoint, send in (
        ("ws", request.ws, ws_send),
        ("http", request.http, http_send),
        ("redis", request.redis, redis_send),
    ):
        if endpoint is None:
            continue
        response = await send(endpoint, payload)
        if response["status"] != ResponseStatus.ok:
            failures.append(f"{name}: {response.get('response')}")
    if write_local and request.local_path is not None:
        asset_path = os.path.join(request.local_path, payload.url_hash)
        with open(asset_path, "w", encoding="utf-8") as f:
            json.dump(payload.model_dump(), f)

    if failures:
        raise ConnectionError("; ".join(failures))


async def _render_isolated(
    request: RenderingRequest, spec: Dict[str, Any], rendering_service_settings: RenderingServiceSettings
) -> None:
    """Render ``spec`` in one isolated worker and forward each result over the request's transport."""
    from deepsearch_rendering_job.render_worker import run_isolated_render

    sent: set = set()
    try:
        async for url_override, url_hash, content in run_isolated_render(
            spec,
            memory_limit_mb=rendering_service_settings.kit_worker_memory_limit or 0,
            batch_timeout=len(spec["urls"]) * spec["per_asset_timeout"],
        ):
            payload = ResponsePayload(request="result", url=url_override, url_hash=url_hash, payload=content)
            await _send_result(request, payload)
            sent.add(url_hash)
    except ConnectionError:
        raise
    except Exception as exc:
        # A batch-level failure (timeout, OOM, crashed worker) yields no per-asset result, so report
        # one for every asset still pending: otherwise the consumer waits on a job that exits 0.
        # local_path (the REST API) is skipped; it maps the re-raised exception to a response itself.
        content = "timeout" if isinstance(exc, TimeoutError) else f"Error rendering: {exc}"
        for url_override, url_hash in zip(spec["url_overrides"], spec["url_hashes"]):
            if url_hash in sent:
                continue
            payload = ResponsePayload(
                request="result",
                url=url_override,
                url_hash=url_hash,
                payload=ContentType(
                    path=url_override, content=content, exception=str(exc), traceback=traceback.format_exc()
                ),
            )
            try:
                await _send_result(request, payload, write_local=False)
            except ConnectionError:
                logger.warning("Could not report failure for %s", redact_url(url_override))
        raise


async def _render_request(
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    semaphore: Optional[TrackingSemaphore] = None,
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
    asset_rendering_timeout: Optional[float] = None,
    kit_worker_memory_limit: Optional[int] = None,
) -> StatusType:
    try:
        if semaphore is None:
            semaphore = nullcontext()
        else:
            n_waiters = semaphore.waiters
            if (
                semaphore.value == 0
                and worker_settings.n_allowed_waiting_requests >= 0
                and n_waiters >= worker_settings.n_allowed_waiting_requests
            ):
                raise ProcessLimitReachedError(
                    f"Too many waiting requests: {n_waiters} > {worker_settings.n_allowed_waiting_requests}"
                )

            logger.info("Waiting requests: %s", n_waiters)

        await update_waiting_requests_gauge(semaphore)
        async with semaphore:
            rendering_service_settings = RenderingServiceSettings()
            if asset_rendering_timeout is not None:
                rendering_service_settings.asset_rendering_timeout = asset_rendering_timeout
            if kit_worker_memory_limit is not None:
                rendering_service_settings.kit_worker_memory_limit = kit_worker_memory_limit

            batch_timeout = len(request.url_list) * rendering_service_settings.asset_rendering_timeout
            status: StatusType = await asyncio.wait_for(
                render_asset(
                    request=request,
                    auth=auth,
                    rendering_service_settings=rendering_service_settings,
                    worker_settings=worker_settings,
                ),
                timeout=batch_timeout,
            )
    except asyncio.TimeoutError as exc_info:
        logger.error("Rendering timeout: %s", str(exc_info))
        url = request.url_list[0] if len(request.url_list) == 1 else None
        raise TimeoutError(
            f"Rendering timeout: {rendering_service_settings.asset_rendering_timeout} seconds for URL: {url}",
            traceback=traceback.format_exc(),
            url=url,
        ) from exc_info
    except ProcessLimitReachedError as exc_info:
        logger.info("Process limit reached: %s", str(exc_info))
        raise exc_info
    except OutOfMemoryError as exc_info:
        logger.error("Rendering out of memory: %s", str(exc_info))
        raise exc_info
    except TimeoutError as exc_info:
        logger.error("Rendering timeout: %s", str(exc_info))
        url = request.url_list[0] if len(request.url_list) == 1 else None
        raise TimeoutError(
            f"Rendering timeout: {rendering_service_settings.asset_rendering_timeout} seconds for URL: {url}",
            traceback=traceback.format_exc(),
            url=url,
        ) from exc_info
    except Exception as exc_info:
        logger.exception("Rendering exception: %s", str(exc_info))
        status = StatusType.EXCEPTION

    logger.info("Rendering of the following URLs is completed with status: '%s'", status)
    logger.info([redact_url(url) for url in request.url_list])

    return status


async def batch_rendering(
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
) -> List[str]:
    if worker_settings.batch_size < 0:
        url_lists = [request.url_list]
    else:
        url_lists = [
            request.url_list[i : i + worker_settings.batch_size]
            for i in range(0, len(request.url_list), worker_settings.batch_size)
        ]

    semaphore: Optional[TrackingSemaphore] = None
    if worker_settings.n_workers > 0:
        semaphore = TrackingSemaphore(worker_settings.n_workers)

    statuses: List[str] = await asyncio.gather(
        *[
            _render_request(
                # A copy, not a fresh request: the batch keeps render_settings, size and transports.
                request=request.model_copy(update={"url_list": url_list}),
                auth=auth,
                semaphore=semaphore,
                worker_settings=worker_settings,
            )
            for url_list in url_lists
        ],
        return_exceptions=True,
    )

    logger.info("------------------------")
    logger.info("Processing stats:")
    for batch_id, url_list, status in zip(range(len(url_lists)), url_lists, statuses):
        logger.info(
            "[%d / %d] Rendering of %s completed with status: '%s'",
            batch_id,
            len(url_lists),
            [redact_url(url) for url in url_list],
            status,
        )
    logger.info("------------------------")

    return statuses
