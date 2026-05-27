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

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from kubernetes_asyncio.client import (
    ApiClient,
    CoreV1Api,
    V1ContainerState,
    V1Job,
    V1JobList,
    V1JobStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodList,
)

from search_utils.misc_utils import load_yaml_file

from .models import k8s_render_job_config


class JobStatus(str, Enum):
    waiting = "waiting"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


def get_image_pull_secrets(
    image_pull_secrets_path: Optional[str] = None,
) -> Dict[str, Any]:
    if image_pull_secrets_path is None:
        if k8s_render_job_config.image_pull_secrets_path is None:
            image_pull_secrets_path = f"{Path(__file__).parent.absolute().as_posix()}/image_pull_secrets.yaml"
        else:
            image_pull_secrets_path = k8s_render_job_config.image_pull_secrets_path

    loaded_yaml: Dict[str, Any] = load_yaml_file(image_pull_secrets_path)
    return loaded_yaml


def get_job_id(job: V1Job) -> str:
    job_meta: V1ObjectMeta = job.metadata
    return job_meta.labels["job-id"]


def get_job_id_mapping(res: V1JobList) -> Dict[str, V1Job]:
    job_id_mapping: Dict[str, V1Job] = {}
    job: V1Job
    for job in res.items:
        job_id_mapping[get_job_id(job)] = job

    return job_id_mapping


def get_job_status(job: V1Job) -> JobStatus:
    status: V1JobStatus = job.status
    if status.succeeded == 1:
        return JobStatus.succeeded
    if status.failed is not None and status.failed > 0:
        return JobStatus.failed
    if status.ready == 0:
        return JobStatus.waiting
    return JobStatus.running


async def get_pod_from_job(v1_core: CoreV1Api, job: V1Job, namespace: str) -> V1Pod:
    metadata: V1ObjectMeta = job.metadata
    pod_list: V1PodList = await v1_core.list_namespaced_pod(
        namespace=namespace, label_selector=f"job-name={metadata.name}"
    )
    return pod_list.items[0]


def get_pod_state(pod: V1Pod) -> V1ContainerState:
    return pod.status.container_statuses[0].state


async def get_pod_state_from_job(job: V1Job, namespace: str) -> V1ContainerState:
    async with ApiClient() as k8s_api:
        core_api = CoreV1Api(k8s_api)
        pod = await get_pod_from_job(core_api, job=job, namespace=namespace)
        return get_pod_state(pod=pod)
