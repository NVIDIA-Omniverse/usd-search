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

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Tuple, Type

from envyaml import EnvYAML
from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings
from pydantic_settings.main import SettingsConfigDict
from pydantic_settings.sources import (
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


class CustomYamlConfigSettingsSource(YamlConfigSettingsSource):
    def _read_file(self, file_path: Path) -> dict[str, Any]:
        logger.info("Loading settings from %s", file_path)
        if file_path.exists():
            return EnvYAML(file_path).export()
        logger.warning("missing configuration file at path: %s", file_path)
        return {}


bin_path = os.path.abspath(os.path.dirname(__file__))


class SearchBackendType(str, Enum):
    es_index = "es_index"
    os_index = "os_index"


class SearchBackendConfig(BaseSettings):
    host: str = Field(default="localhost", description="Search backend host name", alias="es_host")
    port: int = Field(default=9200, description="Search backend port number", alias="es_port")
    name: str = Field(
        default="siglip2-embedding",
        description="Name used for generation of Search Backend indexes",
        alias="ES_NAME",
    )
    backend_type: SearchBackendType = Field(default=SearchBackendType.os_index, description="Search backend type")
    dim: int = Field(
        default=1536,
        description="Dimensionality of embedding vectors",
        alias="DS_EMBEDDING_DIM",
    )


class StorageAndSearchBackendConfig(TypedDict):
    search_backend_config: SearchBackendConfig


class NGSearchStorageSearchBackendConfigFile(BaseSettings):
    settings_file: str = "settings.yaml"
    model_config = SettingsConfigDict(env_prefix="ngsearch_storage_search_backend_")


class NGSearchStorageSearchBackendConfig(BaseSettings):
    backends: Dict[str, StorageAndSearchBackendConfig] = Field(
        default={"default_backend": StorageAndSearchBackendConfig(search_backend_config=SearchBackendConfig())},
        description="search backend configuration",
    )
    model_config = ConfigDict(extra="allow")

    @classmethod
    def settings_customise_sources(
        cls, settings_cls: Type[BaseSettings], init_settings: PydanticBaseSettingsSource, **kwargs
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            EnvSettingsSource(
                settings_cls,
                env_prefix="APP__",
                env_nested_delimiter="__",
                case_sensitive=False,
            ),
            CustomYamlConfigSettingsSource(
                settings_cls,
                yaml_file=NGSearchStorageSearchBackendConfigFile().settings_file,
            ),
        )
