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

from typing import Annotated, List

# third party modules
from fastapi import APIRouter, Query, Request

# local / proprietary modules
from plugins import BasePlugin, Plugins

from .models import PluginDescription

router = APIRouter(prefix="/plugins")


@router.get(
    "",
    tags=["Plugins"],
    description="Get the list of plugins that are supported by the USD Search instance",
    summary="List of supported plugins",
)
async def list_plugins(
    request: Request,
    only_active: Annotated[bool, Query(description="show only active plugins")] = True,
) -> List[PluginDescription]:
    active_plugins: List[BasePlugin] = request.app.active_plugins
    active_plugins_names = set([plugin.plugin_name for plugin in active_plugins])

    response: List[PluginDescription] = []
    for plugin in sorted(Plugins.get_all_plugins(), key=lambda x: x.plugin_name):
        if only_active and plugin.plugin_name not in active_plugins_names:
            continue
        plugin_config = plugin._config.model_dump()
        plugin_config["active"] = plugin.plugin_name in active_plugins_names
        response.append(
            PluginDescription(
                name=plugin.plugin_name,
                description=plugin.__doc__,
                data_types=plugin.data_types,
                requires_rendering=plugin.render,
                active=plugin.plugin_name in active_plugins_names,
                config=plugin_config,
            )
        )

    return response
