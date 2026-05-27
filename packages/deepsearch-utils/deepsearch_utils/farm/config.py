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
import os
from pathlib import Path
from typing import Any, Tuple, Type

# third party modules
import pydantic
import yaml
from pydantic_settings import BaseSettings
from pydantic_settings.sources import (
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    YamlConfigSettingsSource,
)

# local / proprietary modules
from .data import CameraPlacingStrategy, RenderSettings


class CustomYamlConfigSettingsSource(YamlConfigSettingsSource):
    def _read_file(self, file_path: Path) -> dict[str, Any]:
        try:
            from_file = yaml.safe_load(file_path.read_text())
            if "camera_placing_strategy" in from_file.get("render_settings", {}).keys():
                from_file["render_settings"]["camera_placing_strategy"] = str(
                    CameraPlacingStrategy(from_file["render_settings"]["camera_placing_strategy"])
                )
            return from_file
        except FileNotFoundError:
            return {}


class RenderingJobSettings(BaseSettings):
    render_settings: RenderSettings = pydantic.Field(default=RenderSettings(), description="rendering settings")

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
                yaml_file=os.getenv("RENDERING_JOB_SETTINGS_PATH", "farm_settings.yaml"),
            ),
        )
