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

import carb

# local/proprietary modules
import omni.ext
from omni.services.core import main
from omni.services.deepsearch.rendering.helpers import cache_utils as cu
from omni.services.deepsearch.rendering.helpers import utils as omni_utils
from omni.services.deepsearch.rendering.helpers.view_renderer import ViewRenderer

# from omni.kit.thumbnails.mdl import ThumbnailManager
from omni.services.deepsearch.rendering.services import rendering
from omni.services.deepsearch.rendering.services.utils import storage_api_registration


class ServiceDeepSearchRendererExtension(omni.ext.IExt):
    def __init__(self) -> None:
        super().__init__()
        self.config = omni_utils.get_config(logger=carb.log_verbose)
        self._storage_api_request = storage_api_registration()

    def on_startup(self):
        _view_renderer = ViewRenderer(config=self.config, asset_loading_tracker="editor")
        rendering.router.register_facility("view_renderer", _view_renderer)

        # _mdl_thumbnail_manager = ThumbnailManager(max_retry_count=5)
        # rendering.router.register_facility("mdl_thumbnail_manager", _mdl_thumbnail_manager)

        _cache = cu.InMemoryCache(limit=1024)  # create a cache with 1024 limit

        rendering.router.register_facility("cache", _cache)

        main.register_router(rendering.router, prefix="/deepsearch/rendering", tags=["deepsearch"])

    def on_shutdown(self):
        main.deregister_router(rendering.router, prefix="/deepsearch/rendering")
        self._storage_api_request = None
