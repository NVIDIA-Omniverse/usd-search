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

"""Metadata schema + prompt loader.

The metadata vocabulary lives in ``metadata_fields.yaml`` (file, discoverable) and
the instruction prompt in ``metadata_prompt.txt``. ``Metadata`` builds a Pydantic
model from the YAML so the VLM output is schema-validated.
"""

# standard modules
import json
import logging
import os
import re
from typing import Literal, Optional

# third party modules
import yaml
from pydantic import BaseModel, Field, create_model, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger()

_HERE = os.path.dirname(os.path.realpath(__file__))


def _normalize_enum_value(value: str) -> str:
    """Case/spacing drift normalization shared by str enums and list vocabularies."""
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    return re.sub(r"[^a-z0-9_]", "", normalized)


def _canonical_vocabulary(field_name: str, allowed_values: object) -> dict[str, str]:
    """Validate a configured vocabulary and map normalized values to canonical ones.

    The VLM-facing normalizer is deliberately lossy, so two configured values that
    collapse to the same key would otherwise be order-dependent. Fail while loading
    the schema instead of silently choosing one canonical indexed value.
    """
    if not isinstance(allowed_values, list) or not allowed_values:
        raise ValueError(f"Field {field_name!r} allowed_values must be a non-empty list of strings")

    canonical_by_normalized: dict[str, str] = {}
    for index, canonical in enumerate(allowed_values):
        if not isinstance(canonical, str) or not canonical.strip():
            raise ValueError(f"Field {field_name!r} allowed_values[{index}] must be a non-empty string")
        normalized = _normalize_enum_value(canonical)
        if not normalized.strip("_"):
            raise ValueError(f"Field {field_name!r} allowed_values[{index}] has no normalizable characters")
        previous = canonical_by_normalized.get(normalized)
        if previous is not None:
            raise ValueError(
                f"Field {field_name!r} allowed_values contain a normalization collision: "
                f"{previous!r} and {canonical!r} both normalize to {normalized!r}"
            )
        canonical_by_normalized[normalized] = canonical
    return canonical_by_normalized


class MetadataConfig(BaseSettings):
    """Paths to the metadata schema + prompt (env ``USDSEARCH_VISION_METADATA_*``)."""

    yaml_filepath: str = Field(default=os.path.join(_HERE, "metadata_fields.yaml"))
    prompt_filepath: str = Field(default=os.path.join(_HERE, "metadata_prompt.txt"))

    model_config = SettingsConfigDict(env_prefix="usdsearch_vision_metadata_", populate_by_name=True)


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
        # enum fields: schema-enforced closed vocabularies (Literal), so
        # off-vocabulary values fail validation instead of polluting the index.
        # Nullable enums coerce off-vocabulary values to None instead: for
        # open-ended vocabularies (category/style) a missing value beats a
        # forced wrong one when a new asset type isn't covered yet.
        enum_fields: dict[str, dict[str, str]] = {}
        nullable_enum_fields: set[str] = set()
        # list fields with a closed item vocabulary: items are drift-normalized
        # and off-vocabulary items dropped (logged) — see the YAML header.
        list_enum_fields: dict[str, dict[str, str]] = {}
        # per-list max bounds: over-long lists are truncated (they are ordered
        # most->least relevant, so dropping the tail is the intended repair and
        # never fails an asset for being too thorough).
        list_max_items: dict[str, int] = {}
        for metadata_field in self.metadata_fields:
            name = metadata_field["name"]
            t = metadata_field["type"]
            has_allowed_values = "allowed_values" in metadata_field
            allowed_values = metadata_field.get("allowed_values")
            canonical_vocabulary = _canonical_vocabulary(name, allowed_values) if has_allowed_values else None
            if t == "str":
                if canonical_vocabulary is not None:
                    enum_fields[name] = canonical_vocabulary
                    canonical_values = tuple(canonical_vocabulary.values())
                    if metadata_field.get("nullable"):
                        nullable_enum_fields.add(name)
                        field_definitions[name] = (Optional[Literal[canonical_values]], ...)
                    else:
                        field_definitions[name] = (Literal[canonical_values], ...)
                elif metadata_field.get("nullable"):
                    # free-text but nullable (e.g. category in the generic
                    # deployment, where the closed vocabulary is opt-in)
                    field_definitions[name] = (Optional[str], ...)
                else:
                    field_definitions[name] = (str, ...)
            elif t == "list[str]":
                # min_items is deliberately NOT schema-enforced: an under-min list
                # would hard-fail the asset (deterministic at temp 0 — retries
                # can't help), which is worse than indexing a sparse list. It stays
                # prompt-only guidance; max_items is repaired by truncation below.
                # allowed_values on a list stays list[str]-typed (never Literal):
                # off-vocabulary items are dropped in the before-validator, so
                # they can neither fail validation nor burn the repair re-ask.
                if canonical_vocabulary is not None:
                    list_enum_fields[name] = canonical_vocabulary
                field_kwargs = {}
                if "max_items" in metadata_field:
                    list_max_items[name] = metadata_field["max_items"]
                    field_kwargs["max_length"] = metadata_field["max_items"]
                field_definitions[name] = (list[str], Field(..., **field_kwargs) if field_kwargs else ...)
                list_fields.append(name)
            elif t == "bool":
                field_definitions[name] = (bool, ...)
            elif t == "float":
                field_definitions[name] = (float, ...)
            elif t == "int":
                field_definitions[name] = (int, ...)
            else:
                raise Exception(f"Unsupported type: {t}")

        # Normalize common VLM output drift before validation: comma-joined lists,
        # over-long lists, and case/spacing variants of enum values.
        @model_validator(mode="before")
        @classmethod
        def normalize_vlm_output(cls, data):
            if isinstance(data, dict):
                for field_name in list_fields:
                    if field_name in data and isinstance(data[field_name], str):
                        data[field_name] = [item.strip() for item in data[field_name].split(",") if item.strip()]
                    canonical_items = list_enum_fields.get(field_name)
                    if canonical_items and isinstance(data.get(field_name), list):
                        # vocabulary filter runs BEFORE truncation so off-vocab
                        # items cannot waste max_items slots
                        kept = []
                        for item in data[field_name]:
                            normalized = _normalize_enum_value(item) if isinstance(item, str) else ""
                            canonical = canonical_items.get(normalized)
                            if canonical is not None:
                                kept.append(canonical)
                            else:
                                logger.info(f"Dropping off-vocabulary {field_name} item: {item!r}")
                        data[field_name] = kept
                    max_items = list_max_items.get(field_name)
                    if max_items is not None and isinstance(data.get(field_name), list):
                        data[field_name] = data[field_name][:max_items]
                for field_name, canonical_values in enum_fields.items():
                    value = data.get(field_name)
                    if isinstance(value, str):
                        normalized = _normalize_enum_value(value)
                        canonical = canonical_values.get(normalized)
                        if canonical is not None:
                            data[field_name] = canonical
                        elif field_name in nullable_enum_fields:
                            data[field_name] = None
            return data

        base_model: BaseModel = create_model(
            "Metadata",
            __validators__={"normalize_vlm_output": normalize_vlm_output},
            **field_definitions,
        )
        base_model.__str__ = lambda self: self.model_dump_json(indent=2)
        return base_model

    def set_prompt(self, fpath: str) -> str:
        metadata_types = {}
        metadata_definitions = {}
        for metadata_field in self.metadata_fields:
            name = metadata_field["name"]
            # Surface schema constraints in the prompt too: not every endpoint
            # enforces the structured-output schema, and the OutputFixingParser
            # repair path only sees the prompt text.
            # ASCII separators only: the blobs go through json.dumps and non-ASCII
            # would render as \uXXXX escapes in the prompt.
            type_str = metadata_field["type"]
            if "allowed_values" in metadata_field:
                if metadata_field["type"] == "list[str]":
                    type_str += " - each item only from: " + ", ".join(metadata_field["allowed_values"])
                else:
                    type_str += " - exactly one of: " + ", ".join(metadata_field["allowed_values"])
                    if metadata_field.get("nullable"):
                        type_str += ", or null if none fits"
            bounds = []
            if "min_items" in metadata_field:
                bounds.append(f"at least {metadata_field['min_items']}")
            if "max_items" in metadata_field:
                bounds.append(f"at most {metadata_field['max_items']}")
            if bounds:
                type_str += f" ({', '.join(bounds)} items)"
            metadata_types[name] = type_str
            metadata_definitions[name] = metadata_field["description"]
        try:
            with open(fpath, "r") as file:
                s = file.read()
                # ensure_ascii=False: descriptions carry em-dashes/arrows that
                # would otherwise reach the model as \uXXXX escapes.
                metadata_types = json.dumps(metadata_types, indent=2, ensure_ascii=False)
                metadata_definitions = json.dumps(metadata_definitions, indent=2, ensure_ascii=False)
                return s.format(
                    metadata_types=metadata_types,
                    metadata_definitions=metadata_definitions,
                )
        except Exception as e:
            logger.error(f"Error reading prompt file: {e}", exc_info=True)
            raise


def get_base_model() -> BaseModel:
    return Metadata().base_model
