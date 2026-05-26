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

# standard modules
from typing import Optional, Type, Union

# local/proprietary modules
from deepsearch_utils.k8s_renderer.main import K8sRenderer
from deepsearch_utils.rendering_service.client import RenderingServiceClient

from ..models import DeepSearchRendererConfig, RendererType
from ._client import FarmClient as _FarmClient

# third party modules


def get_renderer(
    config: Optional[DeepSearchRendererConfig] = DeepSearchRendererConfig(),
) -> Union[Type[K8sRenderer], Type[_FarmClient]]:
    """Given the renderer type - return the correct class"""
    if config.renderer_type == RendererType.k8s:
        return K8sRenderer
    if config.renderer_type == RendererType.farm:
        return _FarmClient
    if config.renderer_type == RendererType.rendering_service:
        return RenderingServiceClient

    raise NotImplementedError(f"renderer_type {config.renderer_type} is currently not supported")


FarmClient: Union[Type[K8sRenderer], Type[_FarmClient], Type[RenderingServiceClient]] = get_renderer()
