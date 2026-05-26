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
import tempfile
import time
import traceback
from asyncio import Semaphore
from asyncio.subprocess import Process
from contextlib import contextmanager, nullcontext
from typing import Any, Dict, List, NamedTuple, Optional

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector
from aiohttp.client_exceptions import ServerDisconnectedError
from deepsearch_rendering_job.kit import start_kit_worker
from deepsearch_rendering_job.models import (
    Authentication,
    ConversionJobInfo,
    ConversionJobStatus,
    ConverterServiceSettings,
    KitSubprocessException,
    KitWorkerSettings,
    RenderingRequest,
    RenderingServiceSettings,
    ResponseType,
    StatusType,
)
from deepsearch_rendering_job.utils import find_free_port

from .exceptions import KitOutOfMemoryError, ProcessLimitReachedError, TimeoutError
from .transport import (
    ContentType,
    ResponsePayload,
    ResponseStatus,
    http_send,
    redis_send,
    ws_send,
)
from .utils import RenderingStatus, get_key, update_waiting_requests_gauge

logger = logging.getLogger(__name__)


class KitWorkerInfo(NamedTuple):
    worker_id: str
    pid: int
    process: Process


# Maps worker_id to KitWorkerInfo
kit_process_dict: Dict[str, KitWorkerInfo] = {}


def _prune_finished_workers() -> None:
    """Remove workers whose subprocess has already exited."""
    for worker_id, info in list(kit_process_dict.items()):
        if info.process is None or info.process.returncode is not None:
            kit_process_dict.pop(worker_id, None)


def allocate_worker_id(max_workers: int) -> Optional[str]:
    """
    Allocate an available worker ID from the pool worker_0 to worker_{max_workers-1}.

    Args:
        max_workers: Maximum number of workers

    Returns:
        Available worker_id (e.g., "worker_0") or None if all are taken
    """
    _prune_finished_workers()
    for i in range(max_workers):
        worker_id = f"worker_{i}"
        if worker_id not in kit_process_dict:
            return worker_id
    return None


def deallocate_worker_id(worker_id: str) -> None:
    """
    Deallocate a worker ID and remove it from the process dict.

    Args:
        worker_id: Worker ID to deallocate
    """
    if worker_id in kit_process_dict:
        kit_process_dict.pop(worker_id)
        logger.info("Deallocated worker ID: %s", worker_id)


async def wait_till_ready(
    rendering_service_settings: RenderingServiceSettings = RenderingServiceSettings(),
    kit_process: Optional[Process] = None,
    memory_watcher_task: Optional[asyncio.Task] = None,
    timeout_watcher_task: Optional[asyncio.Task] = None,
) -> None:
    service_endpoint = (
        f"{rendering_service_settings.host}:{rendering_service_settings.port}/{rendering_service_settings.suffix}"
    )
    while True:
        if memory_watcher_task is not None and memory_watcher_task.done():
            if memory_watcher_task.result() == RenderingStatus.out_of_memory:
                raise KitOutOfMemoryError("Kit process was killed due to out of memory during startup")
        if timeout_watcher_task is not None and timeout_watcher_task.done():
            if timeout_watcher_task.result() == RenderingStatus.timeout:
                raise TimeoutError("Kit process timed out during startup")
        try:
            async with ClientSession() as session:
                async with session.get(f"{service_endpoint}/healthy") as resp:
                    assert resp.status == 200
                    json_content = await resp.json()
            if json_content["status"] == "healthy":
                break
            logger.info("Unhealthy status: %s", json_content["status"])
            await asyncio.sleep(0.5)
        except ClientError as exc_info:

            # check whether memory or timeout tasks have been completed
            if memory_watcher_task is not None and memory_watcher_task.done():
                if memory_watcher_task.result() == RenderingStatus.out_of_memory:
                    raise KitOutOfMemoryError("Kit process was killed due to out of memory during startup")
            if timeout_watcher_task is not None and timeout_watcher_task.done():
                if timeout_watcher_task.result() == RenderingStatus.timeout:
                    raise TimeoutError("Kit process timed out during startup")

            logger.info("Waiting for Kit process to be ready")
            logger.debug("Service connection error: %s", str(exc_info))
            if kit_process is not None and kit_process.returncode is not None:
                if kit_process.returncode == -9:
                    message = "Kit process was killed with SIGKILL (possibly due to out of memory)"
                else:
                    message = f"Kit process failed with return code: {kit_process.returncode}"

                raise KitSubprocessException(message) from exc_info

            await asyncio.sleep(0.5)


@contextmanager
def worker_context(worker_settings: KitWorkerSettings):
    worker_id = allocate_worker_id(worker_settings.n_workers)
    timeout = int(os.getenv("WORKER_ACQUIRE_TIMEOUT", "600"))
    start = time.time()
    while worker_id is None:
        if time.time() - start > timeout:
            raise RuntimeError(f"No available worker IDs (max_workers={worker_settings.n_workers})")
        time.sleep(0.2)
        worker_id = allocate_worker_id(worker_settings.n_workers)
    logger.info("Allocated worker ID: %s", worker_id)
    try:
        yield worker_id
    finally:
        deallocate_worker_id(worker_id)


async def render_asset(  # type: ignore[misc]
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    rendering_service_settings: RenderingServiceSettings = RenderingServiceSettings(),
    converter_settings: ConverterServiceSettings = ConverterServiceSettings(),
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
) -> StatusType:
    """Send a rendering request to the service

    Args:
        request (RenderingRequest): rendering request
        service_endpoint (str): service endpoint

    Returns:
        str: status of the rendering request
    """
    logger.info("Rendering assets: %s", request.url_list)
    logger.info("Rendering service settings: %s", rendering_service_settings)

    json_content: Dict[str, Any] = {}
    kit_process: Optional[Process] = None
    memory_watcher_task: Optional[asyncio.Task] = None
    timeout_watcher_task: Optional[asyncio.Task] = None
    memory_status: Optional[RenderingStatus] = None
    timeout_status: Optional[RenderingStatus] = None
    # create a temporary directory to keep all configurations per run
    with tempfile.TemporaryDirectory() as output_dir, worker_context(worker_settings) as worker_id:
        if rendering_service_settings.start_kit_worker:
            kit_process, memory_watcher_task, timeout_watcher_task = await start_kit_worker(
                request=auth,
                output_dir=output_dir,
                log_level=rendering_service_settings.kit_worker_log_level,
                port=rendering_service_settings.port,
                cache_location=rendering_service_settings.cache_location,
                extension_folder=rendering_service_settings.extension_folder,
                hssc_uri=rendering_service_settings.hssc_uri,
                enable_shader_cache_wrapper=rendering_service_settings.enable_shader_cache_wrapper,
                memory_limit=rendering_service_settings.kit_worker_memory_limit,
                worker_id=worker_id,
                rendering_timeout=rendering_service_settings.asset_rendering_timeout,
                kit_extra_args=worker_settings.kit_extra_args,
            )
            kit_process_dict[worker_id] = KitWorkerInfo(worker_id=worker_id, pid=kit_process.pid, process=kit_process)

        # wait for service to be ready before
        if rendering_service_settings.wait_till_ready:
            await wait_till_ready(
                rendering_service_settings=rendering_service_settings,
                kit_process=kit_process,
                memory_watcher_task=memory_watcher_task,
                timeout_watcher_task=timeout_watcher_task,
            )

        service_endpoint = (
            f"{rendering_service_settings.host}:{rendering_service_settings.port}/{rendering_service_settings.suffix}"
        )

        # convert assets to USD format
        converter_settings.port = rendering_service_settings.port
        conversion_job_list: List[ConversionJobInfo] = await convert_asset(
            request=request,
            converter_settings=converter_settings,
            output_dir=output_dir,
        )

        # prepare rendering request

        url_list: List[str] = []
        url_list_path_override: List[str] = []

        for conversion_job in conversion_job_list:
            if conversion_job.status in [
                ConversionJobStatus.ok,
                ConversionJobStatus.skipped,
            ]:
                url_list.append(conversion_job.output_path)
                url_list_path_override.append(conversion_job.source_path)
            else:
                content = ContentType(path=conversion_job.source_path, content="load_error")
                payload = ResponsePayload(
                    request="result",
                    url=conversion_job.source_path,
                    url_hash=get_key(conversion_job.source_path),
                    payload=content,
                )

                logger.warning(
                    "Conversion failed: '%s': %s",
                    conversion_job.source_path,
                    conversion_job.error,
                )

                response = None
                if request.ws is not None:
                    response = await ws_send(request.ws, payload)
                if request.http is not None:
                    response = await http_send(request.http, payload)
                if request.redis is not None:
                    response = await redis_send(request.redis, payload)
                if request.local_path is not None:
                    asset_path = os.path.join(request.local_path, get_key(conversion_job.source_path))
                    with open(asset_path, "w", encoding="utf-8") as f:
                        f.write(json.dumps(payload.dict()))

                if response is not None and response["status"] != ResponseStatus.ok:
                    raise ConnectionError(response["response"])

        rendering_request = request.dict(exclude_none=True)
        rendering_request["url_list"] = url_list
        rendering_request["url_list_path_override"] = url_list_path_override
        if request.render_settings is not None:
            rendering_request["render_settings"] = request.render_settings.dict(exclude_none=True)
        if request.width is not None:
            rendering_request["render_settings"] = rendering_request.get("render_settings", {})
            rendering_request["render_settings"]["width"] = request.width
        if request.height is not None:
            rendering_request["render_settings"] = rendering_request.get("render_settings", {})
            rendering_request["render_settings"]["height"] = request.height
        if request.mdl_template_url is not None:
            rendering_request["render_settings"] = rendering_request.get("render_settings", {})
            rendering_request["render_settings"]["mdl_template_url"] = request.mdl_template_url
        if request.mdl_stdin is not None:
            rendering_request["render_settings"] = rendering_request.get("render_settings", {})
            rendering_request["render_settings"]["mdl_stdin"] = request.mdl_stdin

        try:
            timeout = ClientTimeout(
                total=len(rendering_request["url_list"]) * rendering_service_settings.asset_rendering_timeout,
                # # NOTE: these are necessary, as Kit hangs on Shader compilation
                # sock_read=30,
                # sock_connect=30,
            )
            connector = TCPConnector(force_close=True)
            async with ClientSession(connector=connector, timeout=timeout) as session:
                # NOTE: here is an example for a single URL, but multiple can be passed
                #  as a list here. The important thing is that Renderer need to have access
                #  to all sources.
                async with session.post(
                    f"{service_endpoint}/batchrender",
                    json=rendering_request,
                ) as resp:
                    assert resp.status == 200
                    json_content: ResponseType = await resp.json()
        except ServerDisconnectedError as exc_info:
            logger.error("Server disconnected: %s", str(exc_info))
        finally:
            if kit_process is not None:
                pid = kit_process.pid
                try:
                    kit_process.terminate()
                except ProcessLookupError as exc_info:
                    logger.error("Process lookup error: %s", str(exc_info))
                try:
                    response = await asyncio.shield(kit_process.wait())
                except ProcessLookupError as exc_info:
                    logger.error("Process lookup error: %s", str(exc_info))
                logger.info(
                    "Kit process with pid: %s (worker_id: %s) terminated with code: %d",
                    pid,
                    worker_id,
                    response,
                )

            if rendering_service_settings.start_kit_worker:
                if memory_watcher_task is not None:
                    memory_status = await memory_watcher_task
                if timeout_watcher_task is not None:
                    timeout_status = await timeout_watcher_task

    if memory_status is not None:
        return memory_status
    if timeout_status is not None:
        return timeout_status

    return json_content.get("status")


async def convert_asset(
    request: RenderingRequest,
    converter_settings: ConverterServiceSettings,
    output_dir: str,
) -> List[ConversionJobInfo]:
    service_endpoint = f"{converter_settings.host}:{converter_settings.port}/{converter_settings.suffix}"

    timeout = ClientTimeout(
        total=len(request.url_list) * converter_settings.asset_conversion_timeout,
    )

    conversion_job_list: List[ConversionJobInfo] = []
    for url in request.url_list:
        # skipping USD and MDL files
        if os.path.splitext(url)[1][1:].startswith("usd") or url.endswith(".mdl"):
            conversion_job_list.append(
                ConversionJobInfo(source_path=url, output_path=url, status=ConversionJobStatus.skipped)
            )
            continue

        output_path = f"{output_dir}/{os.path.basename(url)}.usd"

        try:
            async with ClientSession(timeout=timeout) as session:
                # NOTE: here is an example for a single URL, but multiple can be passed
                #  as a list here. The important thing is that Renderer need to have access
                #  to all sources.
                async with session.post(
                    service_endpoint,
                    json={
                        "import_path": url,
                        "output_path": output_path,
                        "converter_settings": converter_settings.converter_settings.dict(
                            exclude_none=True, exclude_defaults=True
                        ),
                    },
                ) as resp:
                    json_content: ResponseType = await resp.json()
                    if resp.status != 200:
                        logger.warning(json.dumps(json_content))
                        conversion_job_list.append(
                            ConversionJobInfo(
                                source_path=url,
                                status=ConversionJobStatus.conversion_error,
                                error=json.dumps(json_content),
                            )
                        )
                    elif json_content["status"] in ["finished", 200]:
                        conversion_job_list.append(
                            ConversionJobInfo(
                                source_path=url,
                                output_path=output_path,
                                status=ConversionJobStatus.ok,
                            )
                        )
                    else:
                        logger.warning(json.dumps(json_content))
                        conversion_job_list.append(
                            ConversionJobInfo(
                                source_path=url,
                                status=ConversionJobStatus.conversion_error,
                                error=json.dumps(json_content),
                            )
                        )
        except Exception as exc_info:
            logger.exception(exc_info)
            conversion_job_list.append(
                ConversionJobInfo(
                    source_path=url,
                    status=ConversionJobStatus.error,
                    error=str(exc_info),
                )
            )

    return conversion_job_list


async def _render_request(
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    semaphore: Optional[Semaphore] = None,
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
    asset_rendering_timeout: Optional[float] = None,
    kit_worker_memory_limit: Optional[int] = None,
) -> StatusType:
    try:
        if semaphore is None:
            semaphore = nullcontext()
        else:
            n_waiters = len(semaphore._waiters) if semaphore._waiters is not None else 0
            if (
                semaphore._value == 0
                and worker_settings.n_allowed_waiting_requests >= 0
                and n_waiters >= worker_settings.n_allowed_waiting_requests
            ):
                raise ProcessLimitReachedError(
                    f"Too many waiting requests: {n_waiters} > {worker_settings.n_allowed_waiting_requests}"
                )

            logger.info("Waiting requests: %s", n_waiters)

        await update_waiting_requests_gauge(semaphore)
        async with semaphore:
            rendering_service_settings = RenderingServiceSettings(port=find_free_port())
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
    except KitOutOfMemoryError as exc_info:
        logger.error("Kit process out of memory: %s", str(exc_info))
        raise exc_info
    except TimeoutError as exc_info:
        logger.error("Kit process timeout: %s", str(exc_info))
        raise exc_info
    except Exception as exc_info:  # pylint: disable=W0703
        logger.exception("Rendering exception: %s", str(exc_info))
        status = StatusType.EXCEPTION

    logger.info("Rendering of the following URLs is completed with status: '%s'", status)
    logger.info(request.url_list)

    if status == RenderingStatus.timeout:
        url = request.url_list[0] if len(request.url_list) == 1 else None
        raise TimeoutError(
            f"Rendering timeout: {rendering_service_settings.asset_rendering_timeout} seconds for URL: {url}",
            traceback=None,
            url=url,
        )

    return status


async def batch_rendering(
    request: RenderingRequest,
    auth: Authentication = Authentication(),
    worker_settings: KitWorkerSettings = KitWorkerSettings(),
) -> List[str]:
    # if the batch size if lower that 0 - process the whole batch at once
    if worker_settings.batch_size < 0:
        url_lists = [request.url_list]
    else:
        url_lists = [
            request.url_list[i : i + worker_settings.batch_size]
            for i in range(0, len(request.url_list), worker_settings.batch_size)
        ]

    semaphore: Optional[Semaphore] = None
    if worker_settings.n_workers > 0:
        semaphore = Semaphore(worker_settings.n_workers)

    # get asset data
    statuses: List[str] = await asyncio.gather(
        *[
            _render_request(
                request=RenderingRequest(url_list=url_list, ws=request.ws, http=request.http),
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
            str(url_list),
            status,
        )
    logger.info("------------------------")

    return statuses
