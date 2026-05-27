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
import json
import logging
import os
from typing import Optional

# third party modules
import yaml
from pydantic import BaseModel, Field, create_model, model_validator
from pydantic_settings import BaseSettings

# local / proprietary modules

logger = logging.getLogger()


class MetadataConfig(BaseSettings):
    yaml_filepath: str = Field(
        default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "metadata_fields.yaml")
    )
    prompt_filepath: str = Field(
        default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "metadata_prompt.txt")
    )

    class Config:
        env_prefix = "metadata_"


class Metadata:
    def __init__(self, metadata_config: Optional[MetadataConfig] = None):
        if metadata_config is None:
            metadata_config = MetadataConfig()
        self._metadata_fields = self.set_metadata_fields(metadata_config)
        self._base_model = self.set_base_model()
        self._prompt = self.set_prompt(fpath=metadata_config.prompt_filepath)

    @property
    def metadata_fields(self) -> dict[str, str]:
        return self._metadata_fields

    @property
    def base_model(self) -> BaseModel:
        return self._base_model

    @property
    def prompt(self) -> str:
        return self._prompt

    @property
    def field_names(self) -> list[str]:
        return list(self._base_model.model_fields.keys())

    def set_metadata_fields(self, metadata_config) -> dict:
        try:
            with open(metadata_config.yaml_filepath, "r") as stream:
                metadata_fields = yaml.safe_load(stream)
                return metadata_fields["metadata_fields"]
        except yaml.YAMLError as e:
            logger.error(e, exc_info=True)
            raise Exception(f"Reading YAML Exception: {str(e)}") from e
        except Exception as e:
            logger.error(f"Error reading metadata fields: {e}", exc_info=True)
            raise Exception(f"Error reading metadata fields: {e}") from e

    def set_base_model(self):
        field_definitions = {}
        list_fields = []
        for metadata_field in self.metadata_fields:
            name = metadata_field["name"]
            t = metadata_field["type"]
            if t == "str":
                field_definitions[name] = (str, ...)
            elif t == "list[str]":
                field_definitions[name] = (list[str], ...)
                list_fields.append(name)
            elif t == "bool":
                field_definitions[name] = (bool, ...)
            elif t == "float":
                field_definitions[name] = (float, ...)
            elif t == "int":
                field_definitions[name] = (int, ...)
            else:
                raise Exception(f"Unsupported type: {t}")

        # Create a validator that converts comma-separated strings to lists
        @model_validator(mode="before")
        @classmethod
        def fix_comma_separated_lists(cls, data):
            """Convert comma-separated strings to lists for list[str] fields."""
            if isinstance(data, dict):
                for field_name in list_fields:
                    if field_name in data and isinstance(data[field_name], str):
                        data[field_name] = [item.strip() for item in data[field_name].split(",") if item.strip()]
            return data

        base_model: BaseModel = create_model(
            "Metadata",
            __validators__={"fix_comma_separated_lists": fix_comma_separated_lists},
            **field_definitions,
        )
        base_model.__str__ = lambda self: self.model_dump_json(indent=2)
        return base_model

    def set_prompt(self, fpath: str) -> str:
        metadata_types = {}
        metadata_definitions = {}
        for metadata_field in self.metadata_fields:
            name = metadata_field["name"]
            metadata_types[name] = metadata_field["type"]
            metadata_definitions[name] = metadata_field["description"]
        try:
            with open(fpath, "r") as file:
                s = file.read()
                metadata_types = json.dumps(metadata_types, indent=2)
                metadata_definitions = json.dumps(metadata_definitions, indent=2)
                return s.format(
                    metadata_types=metadata_types,
                    metadata_definitions=metadata_definitions,
                )
        except Exception as e:
            logger.error(f"Error reading prompt file: {e}", exc_info=True)
            raise


def get_base_model() -> BaseModel:
    return Metadata().base_model
