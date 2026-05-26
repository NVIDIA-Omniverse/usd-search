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
from pydantic import BaseModel, Field, create_model
from pydantic_settings import BaseSettings

# local / proprietary modules
from vision_endpoint.vlm import VLMService

logger = logging.getLogger(__name__)


class ValidationConfig(BaseSettings):
    vlm_service: VLMService = Field(default=VLMService.inference_hub)
    max_tries: int = Field(default=3)
    yaml_filepath: str = Field(
        default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "validation_fields.yaml")
    )
    prompt_filepath: str = Field(
        default=os.path.join(os.path.dirname(os.path.realpath(__file__)), "validation_prompt.txt")
    )
    domain_context_filepath: Optional[str] = Field(
        default=None,
        description="Optional path to domain-specific context file to customize validation for specific industries",
    )

    class Config:
        env_prefix = "validation_"


class ValidationFields:

    def __init__(self, validation_config: Optional[ValidationConfig] = None):
        if validation_config is None:
            validation_config = ValidationConfig()
        self._validation_fields = self._load_validation_fields(validation_config.yaml_filepath)
        self._base_model = self._create_base_model()
        self._domain_context = self._load_domain_context(validation_config.domain_context_filepath)
        self._prompt = self._load_prompt(validation_config.prompt_filepath)

    @property
    def validation_fields(self) -> list[dict]:
        return self._validation_fields

    @property
    def base_model(self) -> type[BaseModel]:
        return self._base_model

    @property
    def prompt(self) -> str:
        return self._prompt

    @property
    def field_names(self) -> list[str]:
        return list(self._base_model.model_fields.keys())

    def _load_validation_fields(self, yaml_filepath: str) -> list[dict]:
        try:
            with open(yaml_filepath, "r") as stream:
                data = yaml.safe_load(stream)
                return data["validation_fields"]
        except yaml.YAMLError as e:
            logger.error(e, exc_info=True)
            raise Exception(f"Reading YAML Exception: {str(e)}") from e
        except Exception as e:
            logger.error(f"Error reading validation fields: {e}", exc_info=True)
            raise Exception(f"Error reading validation fields: {e}") from e

    def _create_base_model(self) -> type[BaseModel]:
        field_definitions = {}
        for field in self._validation_fields:
            name = field["name"]
            t = field["type"]
            description = field.get("description", "")

            if t == "str":
                field_definitions[name] = (str, Field(description=description))
            elif t == "list[str]":
                field_definitions[name] = (list[str], Field(description=description))
            elif t == "bool":
                field_definitions[name] = (bool, Field(description=description))
            elif t == "float":
                field_definitions[name] = (
                    float,
                    Field(ge=0.0, le=1.0, description=description),
                )
            elif t == "int":
                field_definitions[name] = (int, Field(description=description))
            else:
                raise Exception(f"Unsupported type: {t}")

        base_model = create_model("ValidationResult", **field_definitions)
        base_model.__str__ = lambda self: self.model_dump_json(indent=2)
        return base_model

    def _load_domain_context(self, domain_context_filepath: Optional[str]) -> str:
        if domain_context_filepath is None or not os.path.exists(domain_context_filepath):
            return ""

        try:
            with open(domain_context_filepath, "r") as file:
                context = file.read().strip()
                if context:
                    return f"\n\n# Domain-Specific Context\n\n{context}\n"
                return ""
        except Exception as e:
            logger.warning(f"Could not load domain context file: {e}")
            return ""

    def _load_prompt(self, prompt_filepath: str) -> str:
        validation_types = {}
        validation_definitions = {}
        for field in self._validation_fields:
            name = field["name"]
            validation_types[name] = field["type"]
            validation_definitions[name] = field["description"]

        try:
            with open(prompt_filepath, "r") as file:
                s = file.read()
                validation_types_str = json.dumps(validation_types, indent=2)
                validation_definitions_str = json.dumps(validation_definitions, indent=2)

                domain_context = self._domain_context if self._domain_context else ""

                return s.format(
                    validation_types=validation_types_str,
                    validation_definitions=validation_definitions_str,
                    domain_context=domain_context,
                )
        except Exception as e:
            logger.error(f"Error reading prompt file: {e}", exc_info=True)
            raise


def get_validation_model() -> type[BaseModel]:
    return ValidationFields().base_model
