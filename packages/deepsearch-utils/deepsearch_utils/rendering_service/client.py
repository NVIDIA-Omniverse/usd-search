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
import base64
import logging
import multiprocessing as mp
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

import httpx
import numpy as np
import orjson
from async_lru import alru_cache

try:
    mp.set_start_method("spawn")
except RuntimeError:
    pass

from typing import Optional, Union
from urllib.parse import urlparse

from deepsearch_utils.farm import FARM_RENDERING_TIMEOUT
from deepsearch_utils.farm.data import (
    EmptyScene,
    FarmTimeoutError,
    LoadError,
    RenderingError,
    ResponseStatus,
)
from prometheus_client import Gauge

from search_utils.misc_utils import image_from_base64
from search_utils.storage_client import RemoteFilePath, RemoteFileUri, StorageClient
from search_utils.storage_client.nucleus.client import NucleusStorageClient
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.s3.config import S3StorageClientConfig
from search_utils.storage_client.storage_api.client import StorageAPIStorageClient

from .config import RenderingResponse, RenderingServiceConfig

logger = logging.getLogger(__name__)


class NVCFError(Exception):
    pass


class RenderingServiceError(Exception):
    pass


class RenderingServiceClient:
    def __init__(
        self,
        plugin_name: str,
        worker_type: str = "background",
        use_prom_metrics: bool = False,
        prom_metrics_labels: dict = {},
        s3_config: Optional[S3StorageClientConfig] = None,
        storage_client: Optional[StorageClient] = None,
        ds_renderer_config: Optional[RenderingServiceConfig] = None,
        **kwargss,
    ):
        if ds_renderer_config is None:
            self.ds_renderer_config = RenderingServiceConfig()
        else:
            self.ds_renderer_config = ds_renderer_config
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

        self._s3_config = s3_config

        self.semaphore = asyncio.Semaphore(self.ds_renderer_config.maximum_parallel_requests)

    def __repr__(self) -> str:
        return f"RenderingServiceClient(plugin_name={self.plugin_name}, url={self.ds_renderer_config.rendering_service_url})"

    async def is_available(self) -> bool:
        try:
            return await self._is_available(
                rendering_service_url=self.ds_renderer_config.rendering_service_url,
                health_check_endpoint=self.ds_renderer_config.health_check_endpoint,
                **self.headers,
            )
        except Exception:
            return False

    # refresh the cache every 5 minutes; only True is cached — exceptions propagate uncached
    @staticmethod
    @alru_cache(ttl=300)
    async def _is_available(rendering_service_url: str, health_check_endpoint: str, **headers) -> bool:
        while True:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    rendering_service_url.rstrip("/") + health_check_endpoint,
                    headers=dict(headers),
                )
                response.raise_for_status()
                if response.status_code == 202:
                    logger.warning(
                        "Rendering service at %s is busy, waiting for it to be available",
                        rendering_service_url,
                    )
                    await asyncio.sleep(1)
                elif response.status_code == 200:
                    return True
                else:
                    raise ConnectionError(
                        f"Rendering service at {rendering_service_url} returned unexpected status {response.status_code}"
                    )

    async def is_ready(self) -> bool:
        try:
            while True:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.ds_renderer_config.rendering_service_url.rstrip("/")
                        + self.ds_renderer_config.readiness_endpoint,
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    if response.status_code == 202:
                        logger.warning(
                            "Rendering service at %s is busy, waiting for it to be available",
                            self.ds_renderer_config.rendering_service_url,
                        )
                        await asyncio.sleep(1)
                    elif response.status_code == 200:
                        json_response = response.json()
                        if json_response["status"] == "ok":
                            return True
                        else:
                            logger.warning(
                                "Rendering service at %s is not ready, status: %s, reason: %s",
                                self.ds_renderer_config.rendering_service_url,
                                json_response["status"],
                                json_response["reason"],
                            )
                            return False
                    else:
                        return False

        except httpx.HTTPError:
            return False

    async def get_pending_jobs(self) -> List[str]:
        return []

    @property
    def s3_config(self):
        if self._s3_config is None:
            self._s3_config = S3StorageClientConfig()
        return self._s3_config

    @s3_config.setter
    def s3_config(self, config: S3StorageClientConfig) -> None:
        self._s3_config = config

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

    @property
    def headers(self) -> Dict[str, str]:
        headers = {}
        if self.ds_renderer_config.api_key:
            headers["Authorization"] = f"Bearer {self.ds_renderer_config.api_key}"
        if self.ds_renderer_config.extra_headers:
            headers.update(self.ds_renderer_config.extra_headers)
        return headers

    async def poll_nvcf_request(self, client: httpx.AsyncClient, response: httpx.Response) -> Dict[str, Any]:
        reqid = response.headers.get("nvcf-reqid")
        if reqid is None:
            raise NVCFError("request ID is not found in the response headers")

        while True:
            response = await client.get(
                self.ds_renderer_config.nvcf_request_polling_endpoint.rstrip("/") + "/" + reqid,
                headers=self.headers,
            )
            response.raise_for_status()
            if response.status_code == 200:
                return orjson.loads(response.content)
            elif response.status_code == 202:
                return await self.poll_nvcf_request(client, response)
            elif response.status_code == 302:
                return await self.load_large_reponse_nvcf(client, response)
            else:
                raise NVCFError(f"Rendering request error: {response.status_code}, {response}")

    async def load_large_reponse_nvcf(self, client: httpx.AsyncClient, response: httpx.Response) -> Dict[str, Any]:
        location = response.headers.get("Location")
        if location is None:
            raise NVCFError("request ID is not found in the response headers")

        while True:
            response = await client.get(
                location,
                headers=self.headers,
            )
            response.raise_for_status()
            if response.status_code == 200:
                return orjson.loads(response.content)
            else:
                raise NVCFError(f"request {location} is not found in the response headers")

    async def render(
        self,
        uri: str,
        timeout: float = FARM_RENDERING_TIMEOUT,
        sanitize_input: bool = True,
        **kwargs,
    ) -> Optional[RenderingResponse]:

        # clean the input URI
        if sanitize_input:
            uri = self.sanitize_uri(uri)

        if uri.startswith("s3://"):
            uri = self.transform_s3_uri(uri)

        headers = self.headers
        if self._storage_client is not None:
            if (
                isinstance(self._storage_client, S3StorageClient)
                and self._storage_client.config.aws_access_key_id is not None
            ):
                headers["X-Basic-Auth"] = (
                    f'Basic {base64.b64encode((self._storage_client.config.aws_access_key_id+":"+self._storage_client.config.aws_secret_access_key).encode()).decode()}'
                )
            elif isinstance(self._storage_client, NucleusStorageClient):
                headers["X-Basic-Auth"] = (
                    f'Basic {base64.b64encode((self._storage_client.config.auth.user+":"+self._storage_client.config.auth.password).encode()).decode()}'
                )
            elif isinstance(self._storage_client, StorageAPIStorageClient):
                raise NotImplementedError("Storage API is not supported for rendering service")
        with self.rendering_jobs_count_metric_context():
            async with self.semaphore:
                if not await self.is_available():
                    raise ConnectionError("Rendering service is not available")
                else:
                    logger.debug("Rendering service is available")

                rendering_request_url = (
                    self.ds_renderer_config.rendering_service_url.rstrip("/") + self.ds_renderer_config.endpoint
                )
                logger.info("Rendering request to %s of %s", rendering_request_url, uri)
                rendering_response = None
                while True:
                    try:
                        bg = time.time()
                        async with httpx.AsyncClient(
                            timeout=httpx.Timeout(
                                timeout,
                                connect=self.ds_renderer_config.connection_timeout,
                                read=self.ds_renderer_config.read_timeout,
                            )
                        ) as client:
                            response = await client.post(
                                rendering_request_url,
                                json={
                                    "url": uri,
                                    "enable_caching": self.ds_renderer_config.enable_caching,
                                    "force_render": self.ds_renderer_config.force_render,
                                },
                                headers=headers,
                            )

                            if response.status_code == 429:
                                response_json = orjson.loads(response.content)
                                logger.debug(
                                    "Rendering service is busy, waiting for it to be available: %s: %s, sleeping for %d seconds",
                                    response_json["error"],
                                    response_json["details"],
                                    self.ds_renderer_config.retry_timeout_on_busy,
                                )
                                await asyncio.sleep(self.ds_renderer_config.retry_timeout_on_busy)
                                continue

                            response.raise_for_status()

                            logger.debug("Rendering response: %s", response.status_code)

                            if response.status_code == 200:
                                rendering_response: Dict[str, Any] = orjson.loads(response.content)
                            elif response.status_code == 202:
                                rendering_response = await self.poll_nvcf_request(client, response)
                            elif response.status_code == 302:
                                rendering_response = await self.load_large_reponse_nvcf(client, response)
                            else:
                                raise RenderingServiceError(
                                    f"Rendering request error: {response.status_code}, {response}"
                                )
                            break
                    except httpx.TimeoutException as e:
                        logger.exception("Timeout error after %.01fs: %s", time.time() - bg, e)
                        continue
                    except httpx.HTTPStatusError as e:
                        logger.exception("Rendering request error: %s", e)
                        if e.response.status_code == 504:
                            logger.info("Rendering request timed out: %s", e)
                            continue
                        elif e.response.status_code == 502:
                            logger.info("Bad Gateway: %s", e)
                            continue
                        else:
                            raise e from e

                if rendering_response is None:
                    raise ValueError("rendering response is None")

                if rendering_response.get("error") == ResponseStatus.empty_scene.value:
                    raise EmptyScene(rendering_response)

                elif rendering_response.get("error") == ResponseStatus.load_error.value:
                    raise LoadError(rendering_response)

                elif rendering_response.get("error") == ResponseStatus.timeout.value:
                    raise FarmTimeoutError(rendering_response)

                elif rendering_response.get("status") != ResponseStatus.success.value:
                    raise RenderingError(rendering_response)

                # decode the base64 encoded data
                response = RenderingResponse(images=[], camera_metadata=[], status=ResponseStatus.ok.value)
                for image in rendering_response.get("images"):
                    response["images"].append(np.array(image_from_base64(image)))

                for data in rendering_response.get("camera_metadata"):
                    response["camera_metadata"].append(orjson.loads(data))

                return response
