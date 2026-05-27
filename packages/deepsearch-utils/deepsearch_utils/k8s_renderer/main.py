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
import logging
import os
import uuid
from copy import deepcopy
from functools import cached_property
from typing import Any, Dict, List, Optional, Tuple, TypedDict, Union

import yaml
from aiohttp.client_exceptions import ClientConnectorError
from async_lru import alru_cache
from deepsearch_utils.farm._client import FarmClient
from deepsearch_utils.farm.data import (
    ProcessedItemContent,
    ResponseStatus,
    ServerConfig,
)
from kubernetes_asyncio import client
from kubernetes_asyncio.client import BatchV1Api, V1Job, V1JobList
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.config import load_incluster_config
from typing_extensions import NotRequired

from search_utils.misc_utils import str2bool
from search_utils.storage_client import StorageClient
from search_utils.storage_client.nucleus.client import NucleusStorageClient
from search_utils.storage_client.s3.client import S3StorageClient
from search_utils.storage_client.s3.config import S3StorageClientConfig
from search_utils.storage_client.storage_api.client import StorageAPIStorageClient

from ..models import DeepSearchRendererConfig
from . import k8s_renderer_logger
from .exceptions import K8SJobException
from .models import k8s_render_job_config
from .utils import (
    JobStatus,
    get_image_pull_secrets,
    get_job_id_mapping,
    get_job_status,
    get_pod_state_from_job,
)

logger = logging.getLogger(__name__)


class RenderingJobSubmissionResponse(TypedDict):
    status: ResponseStatus
    task_id: NotRequired[str]


class K8sRenderer(FarmClient):
    default_job_labels = {"deepsearch.job-type": "rendering"}
    default_job_template = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "", "labels": {}},
        "spec": {
            "ttlSecondsAfterFinished": 3600,
            "template": {
                "spec": {
                    "securityContext": {"runAsUser": 1000, "runAsGroup": 1000},
                    "imagePullSecrets": get_image_pull_secrets().get("imagePullSecrets", []),
                    "volumes": [{"name": "cache-volume", "emptyDir": {"sizeLimit": "5Gi"}}],
                    "containers": [
                        {
                            "name": "deepsearch-renderer",
                            "image": k8s_render_job_config.docker_image,
                            # TODO: Remove default
                            "command": ["python", "-m", "deepsearch_rendering_job"],
                            "resources": {
                                "requests": {
                                    "memory": "2Gi",
                                    "cpu": "2",
                                    "nvidia.com/gpu": "1",
                                },
                                "limits": {
                                    "memory": "50Gi",
                                    "cpu": "11",
                                    "nvidia.com/gpu": "1",
                                },
                            },
                            "env": [],
                            "volumeMounts": [
                                {
                                    "mountPath": "/cache/cache/nv_shadercache",
                                    "name": "cache-volume",
                                }
                            ],
                        }
                    ],
                    "restartPolicy": "Never",
                }
            },
            "backoffLimit": 4,
        },
    }

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
        cache_dir: Optional[str] = None,  # deprecated
        use_cache_server: bool = str2bool(os.getenv("FARM_CLIENT_USE_CACHE_SERVER", "False")),  # deprecated
        server_config: Optional[ServerConfig] = None,
        separate_ws_process: bool = str2bool(os.getenv("FARM_CLIENT_SEPARATE_WS_PROCESS", "False")),
        use_prom_metrics: bool = False,
        redis_url: Optional[str] = os.getenv("REDIS_URL"),
        prom_metrics_labels: Optional[Dict[str, Union[str, int]]] = None,
        s3_config: Optional[S3StorageClientConfig] = None,
        k8s_jobs_namespace: Optional[str] = None,
        storage_client: Optional[StorageClient] = None,
        ds_renderer_config: Optional[DeepSearchRendererConfig] = None,
    ):
        if use_cache_server:
            raise ValueError("use_cache_server is deprecated")
        if prom_metrics_labels is None:
            prom_metrics_labels = {}
        super().__init__(
            plugin_name,
            worker_type,
            queue_host,
            queue_port,
            queue_protocol,
            user,
            ws_host,
            ws_port,
            ws_path,
            internal_ws_host,
            internal_ws_port,
            ws_protocol,
            clean_farm_cache,
            rendering_batch_size,
            rendering_batch_timeout,
            cache_dir,
            use_cache_server,
            server_config,
            separate_ws_process,
            use_prom_metrics,
            redis_url,
            prom_metrics_labels,
            s3_config,
            storage_client=storage_client,
            ds_renderer_config=ds_renderer_config,
        )

        load_incluster_config()
        # NOTE: disable SSL verification for accessing k8s cluster functionality only
        #       this was a change required after the following was introduced in python3.13:
        #       https://docs.python.org/3/library/ssl.html#ssl.VERIFY_X509_PARTIAL_CHAIN
        self.k8s_api_configuration = client.Configuration.get_default_copy()
        self.k8s_api_configuration.verify_ssl = str2bool(os.getenv("K8S_RENDER_VERIFY_K8S_SSL_CERT", "true"))
        if not self.k8s_api_configuration.verify_ssl:
            logger.warning(
                "K8S certificate validation is disabled. Make sure certificate validation is enabled when running service in production environments."
            )
        # load job template
        job_template = os.getenv("K8S_RENDER_JOB_TEMPLATE", None)
        if job_template:
            self.job_template = yaml.load(job_template, Loader=yaml.FullLoader)
        else:
            self.job_template = K8sRenderer.default_job_template

        # load rendering job labels
        job_labels = os.getenv("K8S_RENDER_JOB_LABELS", None)

        if job_labels:
            self._job_labels = yaml.load(job_labels, Loader=yaml.FullLoader)
        else:
            self._job_labels = K8sRenderer.default_job_labels

        self.jobs_namespace = k8s_jobs_namespace or self._default_namespace
        self.jobs_name_prefix = "deepsearch-renderer-job"

    def __repr__(self) -> str:
        return f"K8sRenderer(plugin_name={self.plugin_name}, jobs_namespace={self.jobs_namespace})"

    async def is_available(
        self,
    ) -> bool:
        return True

    @cached_property
    def job_labels(self) -> str:
        return ",".join([f"{k}={v}" for k, v in self._job_labels.items()])

    @alru_cache(maxsize=1, ttl=5)
    async def get_k8s_jobs(self) -> Dict[str, V1Job]:
        k8s_renderer_logger.debug("Listing k8s rendering jobs")
        async with ApiClient(configuration=self.k8s_api_configuration) as k8s_api:
            v1_batch = BatchV1Api(k8s_api)
            res: V1JobList = await v1_batch.list_namespaced_job(
                namespace=self.jobs_namespace, label_selector=self.job_labels
            )
            return get_job_id_mapping(res)

    @property
    def _default_namespace(self) -> str:
        ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        if os.path.exists(ns_path):
            with open(ns_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        else:
            return "default"

    def _render_k8s_job_yaml(
        self,
        job_id: str,
        url_list: list[str],
        aws_bucket: Optional[str] = None,
        aws_region: Optional[str] = None,
        aws_access_key: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        storage_api_url: Optional[str] = None,
        storage_api_token: Optional[str] = None,
        storage_api_openid_client_id: Optional[str] = None,
        storage_api_openid_client_secret: Optional[str] = None,
        storage_api_openid_token_url: Optional[str] = None,
        storage_api_openid_scope: Optional[str] = None,
        storage_api_openid_grant_type: Optional[str] = None,
        aws_endpoint: Optional[str] = None,
        omni_user: Optional[str] = None,
        omni_pass: Optional[str] = None,
    ) -> Dict[str, Any]:
        job = deepcopy(self.job_template)
        job["spec"]["template"]["spec"]["containers"][0]["args"] = url_list
        job["metadata"]["name"] = self.jobs_name_prefix + "-" + job_id
        job["metadata"]["labels"]["job-id"] = job_id

        job["spec"]["template"]["spec"]["containers"][0]["env"].append(
            {
                "name": "RENDERING_REQUEST_WS",
                "value": f"{self.ws_protocol}://{self.ws_host}:{self.ws_port}{self.ws_path}",
            }
        )

        # set auth env variables
        if aws_bucket:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "AWS_BUCKET", "value": aws_bucket})
        if aws_region:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "AWS_REGION", "value": aws_region})
        if aws_access_key:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "AWS_ACCESS_KEY", "value": aws_access_key}
            )
        if aws_access_key_id:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "AWS_ACCESS_KEY_ID", "value": aws_access_key_id}
            )
        if aws_endpoint:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "AWS_ENDPOINT", "value": aws_endpoint}
            )
        if omni_user:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "OMNI_USER", "value": omni_user})
        if omni_pass:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "OMNI_PASS", "value": omni_pass})
        if storage_api_url:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "STORAGE_API_URL", "value": storage_api_url}
            )
        if storage_api_token:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "STORAGE_API_TOKEN", "value": storage_api_token}
            )
        if storage_api_openid_client_id:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {
                    "name": "STORAGE_API_OPENID_CLIENT_ID",
                    "value": storage_api_openid_client_id,
                }
            )
        if storage_api_openid_client_secret:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {
                    "name": "STORAGE_API_OPENID_CLIENT_SECRET",
                    "value": storage_api_openid_client_secret,
                }
            )
        if storage_api_openid_token_url:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {
                    "name": "STORAGE_API_OPENID_TOKEN_URL",
                    "value": storage_api_openid_token_url,
                }
            )
        if storage_api_openid_scope:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {"name": "STORAGE_API_OPENID_SCOPE", "value": storage_api_openid_scope}
            )
        if storage_api_openid_grant_type:
            job["spec"]["template"]["spec"]["containers"][0]["env"].append(
                {
                    "name": "STORAGE_API_OPENID_GRANT_TYPE",
                    "value": storage_api_openid_grant_type,
                }
            )
        return job

    def get_auth_kwargs(self, storage_client: StorageClient, base_uri: Optional[str] = None) -> Dict[str, str]:
        """Get authentication arguments for the task

        Args:
            storage_client (StorageClient): storage client that holds all the authentication information.
            base_uri (Optional[str], optional): of the storage backend. Defaults to None.

        Raises:
            ValueError: if storage backend type is multi and base_uri is not provided

        Returns:
            Dict[str, str]: authentication dictionary
        """
        if isinstance(storage_client, NucleusStorageClient):
            return dict(
                omni_user=storage_client.config.auth.user,
                omni_pass=storage_client.config.auth.password,
            )
        elif isinstance(storage_client, S3StorageClient):
            return dict(
                aws_bucket=storage_client.config.bucket_name,
                aws_region=storage_client.config.region_name,
                aws_access_key=storage_client.config.aws_secret_access_key,
                aws_access_key_id=storage_client.config.aws_access_key_id,
                **{"aws_endpoint": storage_client.config.aws_endpoint_url},
            )
        elif isinstance(storage_client, StorageAPIStorageClient):
            return dict(
                storage_api_url=storage_client.config.grpc_endpoint,
                storage_api_token=storage_client.config.token,
                storage_api_openid_client_id=storage_client.config.openid_client_id,
                storage_api_openid_client_secret=storage_client.config.openid_client_secret,
                storage_api_openid_token_url=storage_client.config.openid_token_url,
                storage_api_openid_scope=storage_client.config.openid_scope,
                storage_api_openid_grant_type=storage_client.config.openid_grant_type,
            )
        raise NotImplementedError(f"storage of type: '{type(storage_client)}' is not supported")

    async def get_task_status(self, task_id: str) -> Tuple[bool, Dict[str, str]]:
        return True, {"status": "processing"}

    async def get_pending_jobs(self) -> List[str]:
        """Get list of k8s jobs that are in pending status.

        Returns:
            List[str]: List of Jobs in pending status
        """
        pending_jobs: List[str] = []
        job_id_mapping: Dict[str, V1Job] = await self.get_k8s_jobs()
        for job_id, job in job_id_mapping.items():
            status: JobStatus = get_job_status(job)
            if status == JobStatus.waiting:
                pending_jobs.append(job_id)

        return pending_jobs

    async def get(
        self, uri: str, fields: List[str] = [], task_id: Optional[str] = None, **kwargs
    ) -> ProcessedItemContent:
        while True:
            try:
                item_content = await self.get_data(uri)
                # process item content
                return self._process_item_content(item_content=item_content, task_id=task_id, uri=uri, fields=fields)
            except KeyError:
                pass

            await asyncio.sleep(10)

            if task_id is not None:
                try:
                    job_id_mapping: Dict[str, V1Job] = await self.get_k8s_jobs()
                except ClientConnectorError as e:
                    k8s_renderer_logger.warning("Error fetching k8s rendering jobs", exc_info=e)
                # get job status
                if task_id not in job_id_mapping.keys():
                    raise ValueError(f"K8S Job ID: '{task_id}' not found in {job_id_mapping.keys()}")

                status: JobStatus = get_job_status(job_id_mapping[task_id])

                if status == JobStatus.failed:
                    try:
                        pod_state = await get_pod_state_from_job(job_id_mapping[task_id], namespace=self.jobs_namespace)
                    except Exception as exc_info:
                        logger.warning("Error retrieving pod state %s", str(exc_info))
                        pod_state = None

                    k8s_renderer_logger.warning("K8S job with id: %s failed, state: %s", task_id, str(pod_state))

                    raise K8SJobException(f"K8S job with id: {task_id} failed")
                else:
                    k8s_renderer_logger.debug("Status of the '%s' job: %s", task_id, status.value)

    async def post(
        self,
        url_list: List[str],
        base_uri: Optional[str] = None,
        task_type: str = "batch",
    ) -> RenderingJobSubmissionResponse:
        job_id = uuid.uuid4().hex[:8]

        # prepare authentication parameters

        auth_kwargs: Dict[str, str] = self.get_auth_kwargs(self._storage_client, base_uri=base_uri)
        job = self._render_k8s_job_yaml(job_id=job_id, url_list=url_list, **auth_kwargs)
        logger.debug("Creating k8s job %s body:\n%s", job_id, yaml.dump(job))

        async with ApiClient(configuration=self.k8s_api_configuration) as k8s_api:
            v1_batch = BatchV1Api(k8s_api)
            result = await v1_batch.create_namespaced_job(
                namespace=self.jobs_namespace,
                body=job,
            )
            logger.debug("K8s job %s created:\n%s", job_id, result)

        # TODO: Handle failed jobs
        return RenderingJobSubmissionResponse(status=ResponseStatus.ok, task_id=job_id)
