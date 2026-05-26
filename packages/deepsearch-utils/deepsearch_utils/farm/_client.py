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
import collections
import multiprocessing as mp
from contextlib import contextmanager
from typing import Iterator

try:
    mp.set_start_method("spawn")
except RuntimeError:
    pass

import os
import secrets
import time
from queue import Empty
from typing import Dict, List, Optional, Union
from urllib.parse import urlparse

import aiohttp
from aiohttp.client_exceptions import ClientPayloadError
from deepsearch_utils.farm import (
    FARM_RENDERING_TIMEOUT,
    FARM_STATUS_CHECK_TIMEOUT,
    FARM_TASK_FUNCTION,
    FARM_TASK_TYPE,
    farm_base_settings,
    farm_utils_logger,
)
from deepsearch_utils.farm.data import (
    EmptyScene,
    FarmTimeoutError,
    FarmUnavailable,
    LoadError,
    ProcessedItemContent,
    RenderingError,
    RenderingJob,
    ResponseStatus,
    ServerConfig,
    ServerResponses,
    TaskSubmissionError,
)
from deepsearch_utils.farm.ws_server import FarmWebsocketServer, run_farm_websocket
from prometheus_client import Gauge

from search_utils.cache_utils.base import SharedDictCounter
from search_utils.cache_utils.redis_async import AsyncCacheRedis
from search_utils.datetime_utils import date_from_timestamp
from search_utils.log_utils import prepare_message
from search_utils.misc_utils import str2bool
from search_utils.storage_client import RemoteFilePath, RemoteFileUri, StorageClient
from search_utils.storage_client.nucleus.client import NucleusStorageClient
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.s3.config import S3StorageClientConfig
from search_utils.streams.redis import RedisStreamConfig, RedisStreamWorker

from ..models import DeepSearchRendererConfig
from .config import RenderingJobSettings


class FarmClient:
    def __init__(
        self,
        plugin_name: str,
        worker_type: str = "background",
        queue_host: Optional[str] = os.getenv("FARM_QUEUE_HOST"),
        queue_port: Optional[str] = os.getenv("FARM_QUEUE_PORT"),
        queue_protocol: str = os.getenv("FARM_QUEUE_PROTOCOL", "http"),
        user: str = os.getenv("FARM_USER", "deepsearch_service"),
        ws_host: str = os.getenv("FARM_CLIENT_WS_HOST", "localhost"),
        ws_port: str = os.getenv("FARM_CLIENT_WS_PORT", "8765"),
        ws_path: str = os.getenv("FARM_CLIENT_WS_PATH", "/"),
        internal_ws_host: str = os.getenv("FARM_CLIENT_INTERNAL_WS_HOST", "0.0.0.0"),
        internal_ws_port: str = os.getenv("FARM_CLIENT_INTERNAL_WS_PORT", "8765"),
        ws_protocol: str = os.getenv("FARM_CLIENT_WS_PROTOCOL", "ws"),
        clean_farm_cache: bool = str2bool(os.getenv("CLEAN_FARM_CACHE_ON_STARTUP", "True")),
        rendering_batch_size: int = int(os.getenv("FARM_CLIENT_RENDERING_BATCH_SIZE", "8")),
        rendering_batch_timeout: float = float(os.getenv("FARM_CLIENT_RENDERING_BATCH_TIMEOUT", "5")),
        cache_dir: Optional[str] = farm_base_settings.cache_dir,
        use_cache_server: bool = str2bool(os.getenv("FARM_CLIENT_USE_CACHE_SERVER", "False")),
        server_config: Optional[ServerConfig] = None,
        separate_ws_process: bool = str2bool(os.getenv("FARM_CLIENT_SEPARATE_WS_PROCESS", "False")),
        use_prom_metrics: bool = False,
        redis_url: Optional[str] = os.getenv("REDIS_URL"),
        prom_metrics_labels: dict = {},
        s3_config: Optional[S3StorageClientConfig] = None,
        storage_client: Optional[StorageClient] = None,
        ds_renderer_config: Optional[DeepSearchRendererConfig] = None,
    ):
        if ds_renderer_config is None:
            self.ds_renderer_config = DeepSearchRendererConfig()
        else:
            self.ds_renderer_config = ds_renderer_config
        self.queue_host = queue_host
        self.queue_port = queue_port
        self.queue_protocol = queue_protocol
        self.user = user
        self.ws_host = ws_host
        self.ws_port = ws_port
        self.ws_path = ws_path
        self.use_prom_metrics = use_prom_metrics
        self.prom_metrics_labels = prom_metrics_labels
        self._storage_client = storage_client
        self.plugin_name = plugin_name
        if self.use_prom_metrics:
            self.running_rendering_jobs_gauge = Gauge(
                "omnideepsearch_running_farm_rendering_jobs",
                "Count of running farm rendering jobs",
                labelnames=list(prom_metrics_labels.keys()) + ["plugin_name"],
            )
            self.rendering_stream_length = Gauge(
                "omnideepsearch_rendering_stream_length",
                "Length of rendering stream",
                labelnames=list(prom_metrics_labels.keys()) + ["plugin_name"],
            )

        # self.internal_ws_host = internal_ws_host
        # self.internal_ws_port = internal_ws_port
        self.ws_protocol = ws_protocol
        self.rendering_batch_size = rendering_batch_size
        self.rendering_batch_timeout = rendering_batch_timeout

        # cache server setting
        self.use_cache_server: bool = use_cache_server
        self.server_config: Optional[ServerConfig] = server_config
        self.farm_settings: RenderingJobSettings = RenderingJobSettings()

        self._s3_config = s3_config

        farm_utils_logger.info("Additional Farm settings %s", self.farm_settings)

        # create some cache dictionaries
        # > output dictionary to hold results from FARM
        output_dict_redis_url = redis_url
        output_dict_redis_db = 23
        output_dict_ttl_seconds = int(os.getenv("FARM_CACHE_DICT_TTL_SECONDS", 60 * 60 * 3))
        self.output_dict = AsyncCacheRedis(
            redis_url=output_dict_redis_url,
            database=output_dict_redis_db,
            ttl_seconds=output_dict_ttl_seconds,
        )
        # > dictionary to keep rendering jobs
        self.rendering_stream_config = RedisStreamConfig(
            name=f"{self.plugin_name}-rendering-queue-{worker_type}",
            consumer_group="worker",
            consumer_name="worker",
        )
        self.rendering_stream = RedisStreamWorker(config=self.rendering_stream_config)
        self._rendering_stream_is_cleared = asyncio.Event()

        # > dictionary to map tasks to jobs
        self.uri_to_task_mapping = SharedDictCounter()
        self.batch_id_counter: collections.Counter = collections.Counter()

        # # clean cache on start-up to not interfere with previous runs
        if clean_farm_cache:
            asyncio.ensure_future(self.output_dict.clean_cache())
            # asyncio.get_event_loop().run_until_complete(self.output_dict.clean_cache())

        # make sure input is provided
        if queue_host is None or queue_port is None:
            farm_utils_logger.warning("Farm Queue host and/or Port are incorrectly set: Farm Unavailable")
            raise FarmUnavailable()

        if self.use_cache_server:
            assert self.server_config is not None, "Cache server config is not defined"
            prepare_message(
                msg="Using Cache server:",
                item_list=[
                    f"Internal URL: {self.server_config.url}",
                    f"External URL: {self.server_config.external_url}",
                ],
                logger=farm_utils_logger.info,
            )
        else:
            if separate_ws_process:
                self.p = mp.Process(
                    target=run_farm_websocket,
                    args=(
                        output_dict_redis_url,
                        output_dict_redis_db,
                        output_dict_ttl_seconds,
                        internal_ws_host,
                        internal_ws_port,
                    ),
                )
                # self.p.daemon = True
                self.p.start()
            else:
                self.ws = FarmWebsocketServer(
                    redis_url=output_dict_redis_url,
                    redis_db=output_dict_redis_db,
                    redis_ttl_seconds=output_dict_ttl_seconds,
                    internal_ws_host=internal_ws_host,
                    internal_ws_port=internal_ws_port,
                )

        # # batch rendering task
        # loop = asyncio.get_event_loop()
        # create a task for rendering batches
        self.batch_rendering_task_instance = asyncio.ensure_future(
            self.batch_rendering_task(self.rendering_stream, self.rendering_batch_size, task_type="Batch")
        )

    def __repr__(self) -> str:
        return f"FarmClient(plugin_name={self.plugin_name},queue_host={self.queue_host})"

    async def is_available(self) -> bool:
        return True

    async def init_rendering_stream(self) -> None:
        """Initialize rendering stream. If needed it could be cleared on startup."""
        # make sure stream is available
        await self.rendering_stream.connect_consumer()

        # if needed - clean stream before processing starts
        if self.ds_renderer_config.clear_rendering_stream_on_startup:
            await self.rendering_stream.reset_stream()
            # make sure stream is available again
            await self.rendering_stream.connect_consumer()
        self._rendering_stream_is_cleared.set()

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        self.close_cache()

    @property
    def s3_config(self):
        if self._s3_config is None:
            self._s3_config = S3StorageClientConfig()
        return self._s3_config

    @s3_config.setter
    def s3_config(self, config: S3StorageClientConfig) -> None:
        self._s3_config = config

    async def _wait_for_caches(self) -> None:
        # make sure rendering queue is cleared on startup
        await self._rendering_stream_is_cleared.wait()
        # check if stream is available
        while True:
            if await self.output_dict.is_ready() and await self.rendering_stream.stream_available():
                break
            else:
                await asyncio.sleep(1)

    def close_cache(self) -> None:
        self.batch_rendering_task_instance.cancel()

    @property
    def farm_queue_endpoint(self) -> str:
        return f"{self.queue_protocol}://{self.queue_host}:{self.queue_port}"

    @property
    def farm_submit_url(self) -> str:
        return f"{self.farm_queue_endpoint}{farm_base_settings.queue_suffix}"

    @property
    def farm_info_url(self) -> str:
        return f"{self.farm_queue_endpoint}{farm_base_settings.queue_task_info}"

    @property
    def farm_archive_url(self) -> str:
        return f"{self.farm_queue_endpoint}{farm_base_settings.queue_task_archive}"

    @property
    def farm_cancel_url(self) -> str:
        return f"{self.farm_queue_endpoint}{farm_base_settings.queue_task_cancel}"

    @staticmethod
    def filter_dict(item: dict, fields: List[str]):
        return {k: v for k, v in item.items() if len(fields) == 0 or k in fields}

    async def get_data(self, uri: str):
        if self.use_cache_server:
            try:
                return await self.server_config.get_item(uri)
            except (RuntimeError, ClientPayloadError) as e:
                farm_utils_logger.warning(f"Connection error: {str(e)}")
                raise ConnectionError(f"Connection error: {str(e)}")
        else:
            return await self.output_dict.get(uri)

    async def del_data(self, uri: str):
        if self.use_cache_server:
            await self.server_config.del_item(uri)
        else:
            await self.output_dict.delete(uri)

    def _process_item_content(
        self, item_content, task_id: Optional[str], uri: str, fields: List[str] = []
    ) -> ProcessedItemContent:
        if item_content == ServerResponses.load_error.value:
            return ProcessedItemContent(
                status=ResponseStatus.load_error,
                response={"task_id": task_id, "uri": uri},
            )
        elif item_content == ServerResponses.rendering_error.value:
            return ProcessedItemContent(status=ResponseStatus.error, response={"task_id": task_id, "uri": uri})
        elif item_content == "" or (
            isinstance(item_content, dict) and all([len(v) == 0 for v in item_content.values()])
        ):
            return ProcessedItemContent(
                status=ResponseStatus.empty_scene,
                response={"task_id": task_id, "uri": uri},
            )

        try:
            return ProcessedItemContent(
                status=ResponseStatus.ok,
                content=self.filter_dict(item_content, fields=fields),
            )
        except Exception as e:
            return ProcessedItemContent(
                status=ResponseStatus.error,
                response={"task_id": task_id, "exception": str(e)},
            )

    async def get(
        self,
        uri: str,
        fields: List[str] = [],
        task_id: Optional[str] = None,
        timeout: float = 60,
        status_check_timeout: float = 120,
    ) -> ProcessedItemContent:
        start_time = None
        status_check_start = time.time()
        while True:
            # if await self.check_data(uri):
            try:
                item_content = await self.get_data(uri)
                # process item content
                return self._process_item_content(item_content=item_content, task_id=task_id, uri=uri, fields=fields)
            except KeyError:
                pass

            await asyncio.sleep(10)

            if task_id is not None and (time.time() - status_check_start) > status_check_timeout:
                status_check_start = time.time()
                # TODO: Maybe check k8s job status here

                if timeout is not None and timeout > 0:
                    if start_time is None:
                        start_time = time.time()

                    if start_time is not None and time.time() - start_time > timeout:
                        await self.cancel_task(task_id)
                        return {"status": ResponseStatus.timeout, "response": ""}

    async def get_task_status(self, task_id: str):
        received = False
        while not received:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self.farm_info_url}/{task_id}") as resp:
                        jresp = await resp.json()

                        if resp.status == 200:
                            return True, jresp
                        else:
                            return False, jresp
            except aiohttp.ContentTypeError as e:
                farm_utils_logger.warning("Farm Queue unavailable: %s", str(e))
                await asyncio.sleep(60)

    def prepare_task_comment(self, url_list: List[str], task_type: str = "batch") -> str:
        res: Dict[str, int] = {}
        for uri in url_list:
            server = self.get_server_name(uri)
            res[server] = res.get(server, 0) + 1
        return (
            " ".join([f"{task_type.lower()}: {s}({c})" for s, c in res.items()])
            + f" @ {date_from_timestamp(time.time())}"
        )

    async def post(
        self,
        url_list: list[str],
        base_uri: Optional[str] = None,
        task_type: str = "batch",
    ) -> dict:
        # TODO: Use k8s

        # await self.ws_initialized.wait()

        if not isinstance(url_list, list):
            url_list = [url_list]

        # cache server config
        if self.use_cache_server:
            if self.server_config.url.startswith("ws"):
                server_config = {"ws": self.server_config.external_url}
            elif self.server_config.url.startswith("http"):
                server_config = {"http": self.server_config.external_url}
            else:
                raise NotImplementedError(f"Unrecognizable URL {self.server_config.url}")
        else:
            server_config = {
                "ws": f"{self.ws_protocol}://{self.ws_host}:{self.ws_port}{self.ws_path}",
            }

        # add additional Farm settings
        server_config.update(**self.farm_settings.model_dump())

        # prepare body of request
        request_body = {
            "user": self.user,
            "task_type": FARM_TASK_TYPE,
            "task_args": {},
            "task_function": FARM_TASK_FUNCTION,
            "task_function_args": {"url_list": url_list, **server_config},
            "task_comment": self.prepare_task_comment(url_list, task_type),
        }

        prepare_message(
            msg="Farm rendering request",
            item_list=[f"{k}: {v}" for k, v in request_body.items()],
            logger=farm_utils_logger.debug,
        )

        # run processing
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.farm_submit_url, json=request_body) as resp:
                    jresp = await resp.json()
                    if resp.status == 200:
                        return {
                            "status": ResponseStatus.ok,
                            "task_id": jresp["task_id"],
                        }
                    else:
                        return {"status": ResponseStatus.error, "response": jresp}
        except Exception as e:
            return {"status": ResponseStatus.connection_error, "response": str(e)}

    async def archive_tasks(self, task_ids: list = []):
        # fast exit on empty list
        if len(task_ids) == 0:
            return {"status": ResponseStatus.ok}

        # run processing
        async with aiohttp.ClientSession() as session:
            async with session.post(self.farm_archive_url, json={"task_ids": task_ids}) as resp:
                jresp = await resp.json()
                if resp.status != 200:
                    return {"status": ResponseStatus.error, "response": resp}
                elif jresp["error_count"] > 0:
                    return {"status": ResponseStatus.archival_error, "response": jresp}
                else:
                    return {"status": ResponseStatus.ok}

    async def cancel_task(self, task_id: str):
        # get task status
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.farm_info_url}/{task_id}") as resp:
                jresp = await resp.json()
                if resp.status != 200:
                    return {"status": ResponseStatus.error, "response": resp}

        # run processing
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.farm_cancel_url,
                json={
                    "task_id": task_id,
                    "task_type": FARM_TASK_TYPE,
                    "task_function": FARM_TASK_FUNCTION,
                    "status": jresp["status"],
                    "userid": self.user,
                },
            ) as resp:
                jresp = await resp.json()
                if resp.status != 200:
                    return {
                        "status": ResponseStatus.cancellation_error,
                        "response": jresp,
                    }
                else:
                    return {"status": ResponseStatus.ok}

    async def archive_and_log(self, task_id: str, n_archival_attempts: int = 10):
        # try archiving task
        r = await self.archive_tasks(task_ids=[task_id])
        # exit as soon as archival is completed
        if r["status"] == ResponseStatus.ok:
            return {"status": ResponseStatus.ok}
        else:
            # on error - try cancelling the task
            await self.cancel_task(task_id)
            await asyncio.sleep(1)

        # archive task to keep farm queue clean
        for _ in range(n_archival_attempts):
            r = await self.archive_tasks(task_ids=[task_id])
            # exit as soon as archival is completed
            if r["status"] == ResponseStatus.ok:
                break
            else:
                # sleep for a bit to git farm time to switch task status
                await asyncio.sleep(6)

        if r["status"] != ResponseStatus.ok:
            prepare_message(
                msg="Farm task archival error",
                item_list=[f"status:   {r['status']}", f"response: {r['response']}"],
                logger=farm_utils_logger.warning,
            )
            return {"status": ResponseStatus.error}
        else:
            return {"status": ResponseStatus.ok}

    @staticmethod
    def get_server_name(uri: str) -> str:
        # remove schema
        uri_split_no_schema = uri.split("://")
        if len(uri_split_no_schema) > 1:
            uri_no_schema = uri_split_no_schema[1]
        else:
            uri_no_schema = uri
        # remove path
        uri_split_no_path = uri_no_schema.split("/")
        uri_no_path = uri_split_no_path[0]
        # remove port number
        uri_split_no_port = uri_no_path.split(":")
        return uri_split_no_port[0]

    @staticmethod
    def get_asset_path(uri: str):
        if uri.startswith("omniverse://"):
            uri = uri[12:]

        return uri[uri.find("/") :]

    def sanitize_uri(self, uri: Union[RemoteFilePath, RemoteFileUri]) -> RemoteFileUri:
        # if URI has s3 schema - return directly
        if uri.startswith("s3://"):
            return uri
        # if a different schema is used - try sanitizing the URI
        if isinstance(self._storage_client, NucleusStorageClient):
            # get server name
            server = self.get_server_name(uri)
            path = self.get_asset_path(uri)
            return f"omniverse://{server}{path}"
        # otherwise just return URL
        return uri

    @staticmethod
    def get_base_url(url: str) -> str:
        parsed = urlparse(url=url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def get_pending_jobs(self) -> List[str]:
        """Retrieve the list of jobs that are pending, not to submit jobs too often, when the rendering queue is full.

        Returns:
            List[str]: List of pending rendering job IDs
        """
        # This is a placeholder that it re-implemented on the k8s rendering client side.
        return []

    async def batch_rendering_task(self, stream: RedisStreamWorker, batch_size: int, task_type: str = "Batch"):
        # make sure rendering queue is cleared on startup
        await self.init_rendering_stream()
        await self._rendering_stream_is_cleared.wait()

        while True:
            server_to_url_mapping: Dict[str, List[str]] = {}
            bg = time.time()
            while await stream.get_unprocessed_items_length() < batch_size and (
                (time.time() - bg) < self.rendering_batch_timeout
            ):
                if self.use_prom_metrics:
                    self.rendering_stream_length.labels(**self.prom_metrics_labels, plugin_name=self.plugin_name).set(
                        await stream.get_unprocessed_items_length()
                    )
                await asyncio.sleep(10)

            if self.ds_renderer_config.pending_job_limit >= 0:
                pending_jobs = await self.get_pending_jobs()
                while len(pending_jobs) > self.ds_renderer_config.pending_job_limit:
                    farm_utils_logger.warning(
                        "Too many pending jobs: %d [allowed: %d]",
                        len(pending_jobs),
                        self.ds_renderer_config.pending_job_limit,
                    )
                    if self.use_prom_metrics:
                        self.rendering_stream_length.labels(
                            **self.prom_metrics_labels, plugin_name=self.plugin_name
                        ).set(await stream.get_unprocessed_items_length())
                    await asyncio.sleep(10)
                    pending_jobs = await self.get_pending_jobs()

            try:
                item: RenderingJob
                # get items from the queue and group them by server
                # for item in min(await queue.get_unprocessed_items_length(), batch_size):
                for _ in range(batch_size):
                    async with stream.consume(count=1) as items:
                        if len(items) == 0:
                            break
                        item_dict = items[0]
                    item = RenderingJob(**item_dict)
                    base_uri = self.get_base_url(item.uri)
                    server_to_url_mapping[base_uri] = server_to_url_mapping.get(base_uri, []) + [item.uri]
                if self.use_prom_metrics:
                    self.rendering_stream_length.labels(**self.prom_metrics_labels, plugin_name=self.plugin_name).set(
                        await stream.get_unprocessed_items_length()
                    )
            except Empty:
                prepare_message(
                    msg="Exit on timeout",
                    item_list=[
                        f"total of {len(server_to_url_mapping)} server(s)",
                        f"total of {sum([len(v) for _, v in server_to_url_mapping.items()])} URL(s)",
                    ],
                    logger=farm_utils_logger.debug,
                )
            except Exception as exc_info:
                farm_utils_logger.exception("Processing exception", exc_info=exc_info)

            if len(server_to_url_mapping) > 0:
                for base_uri, raw_url_list in server_to_url_mapping.items():
                    # remove repetitions from the list
                    url_list = list(set(raw_url_list))
                    submitted = False
                    # generated random hash ID
                    batch_hash = secrets.randbits(64)
                    while not submitted:
                        try:
                            r = await self.post(
                                url_list=url_list,
                                base_uri=base_uri,
                                task_type=task_type,
                            )
                            r["batch_size"] = len(url_list)
                            r["batch_hash"] = batch_hash
                            submitted = True

                            prepare_message(
                                msg=f"{task_type} task submitted",
                                item_list=[f"{k}: {v}" for k, v in r.items()],
                                logger=farm_utils_logger.info,
                            )

                        except Exception as e:
                            farm_utils_logger.exception(f"{task_type} task submission exception: {str(e)}")
                            await asyncio.sleep(10)

                    for it, url in enumerate(url_list):
                        self.uri_to_task_mapping[url] = {**r, "url_index": it}

                    self.batch_id_counter[batch_hash] = len(url_list)

            # wait a bit before submitting a new task
            await asyncio.sleep(10)

    def transform_s3_uri(self, uri: str) -> str:
        """Farm accepts only http/https S3 URIs"""
        if isinstance(self._storage_client, S3StorageClient):
            config: S3StorageClientConfig = self._storage_client.config
        elif self._storage_client is None:
            config = self._s3_config
        else:
            raise ValueError(f"Invalid backend: {type(self._storage_client)}")
        url_prefix = f"s3://{config.bucket_name}/"
        if uri.startswith(url_prefix):
            if config.aws_endpoint_url:
                return f"{config.aws_endpoint_url}/{config.bucket_name}/{uri[len(url_prefix):]}"
            else:
                return f"https://{config.bucket_name}.s3.{config.region_name}.amazonaws.com/{uri[len(url_prefix):]}"
        return uri

    @contextmanager
    def rendering_jobs_count_metric_context(self) -> Iterator[None]:
        if self.use_prom_metrics:
            self.running_rendering_jobs_gauge.labels(**self.prom_metrics_labels, plugin_name=self.plugin_name).inc(1)
        try:
            yield
        finally:
            if self.use_prom_metrics:
                self.running_rendering_jobs_gauge.labels(**self.prom_metrics_labels, plugin_name=self.plugin_name).dec(
                    1
                )

    async def render(
        self,
        uri: str,
        fields: list = [],
        force: bool = False,
        timeout: float = FARM_RENDERING_TIMEOUT,
        sanitize_input: bool = True,
        token: Optional[str] = None,
        status_check_timeout: float = FARM_STATUS_CHECK_TIMEOUT,
    ) -> Optional[dict]:
        await self._wait_for_caches()

        req = None

        # clean the input URI
        if sanitize_input:
            uri = self.sanitize_uri(uri)

        if uri.startswith("s3://"):
            uri = self.transform_s3_uri(uri)

        with self.rendering_jobs_count_metric_context():

            try:
                # if item was already processed - skip rendering part
                if force:
                    try:
                        await self.del_data(uri)
                    except KeyError:
                        pass
                # if force and await self.check_data(uri):
                # await self.del_data(uri)

                # if await self.check_data(uri):
                try:
                    item_content = await self.get_data(uri)
                    if item_content == "":
                        raise EmptyScene({"uri": uri})
                    elif item_content == "load_error":
                        raise LoadError({"uri": uri})
                    else:
                        return self.filter_dict(item_content, fields)
                except KeyError:
                    pass

                # send rendering request
                if uri not in self.uri_to_task_mapping.keys():
                    await self.rendering_stream.put(RenderingJob(uri=uri, token=token).model_dump())
                    farm_utils_logger.debug("Enqueuing: '%s'", uri)

                # notify the mapping dictionary that results from a URI are requested
                self.uri_to_task_mapping.inc(uri)
                # retrieve data
                while uri not in self.uri_to_task_mapping.keys():
                    await asyncio.sleep(10)
                # get task id from mapping
                req = self.uri_to_task_mapping[uri]

                if req["status"] != ResponseStatus.ok:
                    prepare_message(
                        msg="Task Submission Error",
                        item_list=[f"{k}: {v}" for k, v in req.items()],
                        logger=farm_utils_logger.warning,
                    )
                    raise TaskSubmissionError(req["response"])

                r = await self.get(
                    uri,
                    fields=fields,
                    task_id=req["task_id"],
                    timeout=timeout * req["batch_size"],
                    status_check_timeout=status_check_timeout,
                )
                if r["status"] == ResponseStatus.empty_scene:
                    raise EmptyScene(r["response"])

                elif r["status"] == ResponseStatus.load_error:
                    raise LoadError(r["response"])

                elif r["status"] == ResponseStatus.timeout:
                    raise FarmTimeoutError(r["response"])

                elif r["status"] != ResponseStatus.ok:
                    raise RenderingError(r["response"])

                # return content
                content = r["content"]
                return content

            finally:
                # update batch counter
                if req is not None:
                    self.batch_id_counter[req["batch_hash"]] = min(
                        self.batch_id_counter[req["batch_hash"]],
                        req["batch_size"] - req["url_index"] - 1,
                    )
                    self.batch_id_counter += collections.Counter()

            return None
