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
import warnings
from enum import Enum
from typing import Any, Dict, Optional, Type

# local/proprietary modules
from search_utils.misc_utils import load_yaml_file

from .asset_graph_generation import AGSPluginConfig, AssetGraphGeneration
from .base_plugin import BasePlugin, BasePluginConfig
from .config import VisionMetadataPluginConfig
from .image_to_embedding import ImageToEmbedding
from .image_to_vision_metadata import ImageToVisionMetadata
from .rendering_to_embedding import RenderingToEmbedding
from .rendering_to_vision_metadata import RenderingToVisionMetadata
from .thumbnail_generation import ThumbnailGeneration
from .thumbnail_to_embedding import ThumbnailToEmbedding
from .thumbnail_to_vision_metadata import ThumbnailToVisionMetadata

# third-party modules


class Plugins(str, Enum):
    image_to_embedding = "image_to_embedding"
    thumbnail_to_embedding = "thumbnail_to_embedding"
    image_to_vision_metadata = "image_to_vision_metadata"
    rendering_to_vision_metadata = "rendering_to_vision_metadata"
    thumbnail_to_vision_metadata = "thumbnail_to_vision_metadata"
    rendering_to_embedding = "rendering_to_embedding"
    thumbnail_generation = "thumbnail_generation"
    asset_graph_generation = "asset_graph_generation"

    @staticmethod
    def get_plugin(plugin_name: str, config: Optional[BasePluginConfig] = None) -> BasePlugin:

        if plugin_name not in Plugins.__members__:
            raise ValueError(f"Plugin {plugin_name} not found")

        if plugin_name == Plugins.image_to_embedding:
            return ImageToEmbedding(config)

        if plugin_name == Plugins.thumbnail_to_embedding:
            return ThumbnailToEmbedding(config)

        if plugin_name == Plugins.image_to_vision_metadata:
            return ImageToVisionMetadata(config)

        if plugin_name == Plugins.rendering_to_vision_metadata:
            return RenderingToVisionMetadata(config)

        if plugin_name == Plugins.rendering_to_embedding:
            return RenderingToEmbedding(config)

        if plugin_name == Plugins.thumbnail_generation:
            return ThumbnailGeneration(config)

        if plugin_name == Plugins.asset_graph_generation:
            return AssetGraphGeneration(config)

        if plugin_name == Plugins.thumbnail_to_vision_metadata:
            return ThumbnailToVisionMetadata(config=config)

        raise NotImplementedError(f"{plugin_name} is not implemented")

    @staticmethod
    def get_active_plugins(config_path: Optional[str] = None) -> list[BasePlugin]:
        if not config_path:
            return Plugins.get_all_plugins()

        active_dict: Dict[str, Dict[str, Any]] = load_yaml_file(path=config_path)
        plugins = []
        for plugin_name in Plugins.__members__:
            if plugin_name not in active_dict:
                warnings.warn(f"Plugin {plugin_name} not found in config")
                active_dict[plugin_name] = {}
            active = bool(active_dict[plugin_name].get("active", False))
            if active:
                config = get_config_class(plugin_name=plugin_name)(active=active)
                plugin: BasePlugin = Plugins.get_plugin(plugin_name, config)
                plugins.append(plugin)
        return plugins

    @staticmethod
    def get_all_plugins() -> list[BasePlugin]:
        return [Plugins.get_plugin(plugin_name) for plugin_name in Plugins.__members__]

    @staticmethod
    def get_plugin_names() -> list[str]:
        return [plugin_name for plugin_name in Plugins.__members__]


def get_config_class(plugin_name: str) -> Type[BasePluginConfig]:
    """Get configuration class for different plugins.

    Args:
        plugin_name (str): name of the plugin for which configuration class needs to be retrieved.

    Returns:
        Type[BasePluginConfig]: plugin configuration class
    """
    if plugin_name == Plugins.asset_graph_generation:
        return AGSPluginConfig
    if plugin_name in [
        Plugins.image_to_vision_metadata,
        Plugins.thumbnail_to_vision_metadata,
        Plugins.rendering_to_vision_metadata,
    ]:
        return VisionMetadataPluginConfig
    return BasePluginConfig


__all__ = [
    "BasePlugin",
    "BasePluginConfig",
    "Plugins",
    "ImageToEmbedding",
    "ThumbnailToEmbedding",
    "ImageToVisionMetadata",
    "RenderingToVisionMetadata",
    "RenderingToEmbedding",
    "ThumbnailGeneration",
    "ThumbnailToVisionMetadata",
]
