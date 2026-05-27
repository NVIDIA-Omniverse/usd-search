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

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class k8sRendererJobConfig(BaseSettings):
    docker_image: str = (
        "nvcr.io/omniverse/deeptag-internal/deepsearch-rendering-job:0.1.0_feature-update-timeout.dev.dirty.236e596e"
    )
    image_pull_secrets_path: Optional[str] = None
    volume_mounts_path: Optional[str] = None

    model_config = SettingsConfigDict(env_prefix="k8s_render_job_")


k8s_render_job_config = k8sRendererJobConfig()
