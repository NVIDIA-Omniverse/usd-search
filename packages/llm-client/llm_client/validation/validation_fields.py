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

"""Validation schema + prompt loader (the VISION-validation role).

Field definitions live in ``validation_fields.yaml`` and the prompt in
``validation_prompt.txt`` (both files, discoverable). Env: ``USDSEARCH_VISION_VALIDATION_*``.
"""

# standard modules
import json
import logging
import os
import re
from typing import Literal, Optional, cast

# third party modules
import yaml
from pydantic import BaseModel, Field, create_model, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.realpath(__file__))

# The one relevance number every verdict carries: ``similarity_score`` on the
# 0-100 scale. The yaml asks the generative model for an integer; the verdict
# widens it to a float so the log-prob method keeps its full resolution (see
# ValidationFields.verdict_model). Also the public API model's field description
# (deepsearch_api.routers_v2.models), so it lives in one place.
SIMILARITY_SCORE_DESCRIPTION = (
    "Query-asset relevance 0-100 (float): P(Yes) x 100 for the logprob method, "
    "the generated value for generative; the rerank sort key"
)


# Asset facts the logprob judge can read in a TEXT query's prompt (logprob_asset_facts), in prompt order;
# each names the request field that carries it.
ASSET_FACT_NAMES = ("path", "vlm_metadata_caption")


class ValidationConfig(BaseSettings):
    """VISION-validation role config; model + tuning only (connection is shared)."""

    model: str = Field(default="gcp/google/gemini-3.1-flash-lite")
    method: Literal["generative", "logprob"] = Field(
        default="generative",
        description="How a verdict is produced. 'generative' (default) has the VLM "
        "generate a structured JSON verdict. 'logprob' asks the short one-word Yes/No judge "
        "question and reads P(Yes) vs P(No) from the first-token log-probs in a single "
        "forward pass — much faster/cheaper, but requires an endpoint that returns "
        "top_logprobs. Both produce the same verdict shape. "
        "See docs/vlm-validation.md ('Validation methods').",
    )
    logprob_domain_context: bool = Field(
        default=False,
        description="Send the configured domain context (domain_context_filepath) alone as the system prompt "
        "of the logprob judge (the generative method always renders it into its system prompt). Default "
        "false: the judge sends its bare question and no system prompt. Opting in re-prefills the context "
        "on every verdict and changes the verdict cache identity. "
        "Env: USDSEARCH_VISION_VALIDATION_LOGPROB_DOMAIN_CONTEXT.",
    )
    logprob_asset_facts: Optional[list[str]] = Field(
        default=None,
        description="Asset facts a TEXT query's logprob judge reads, between the query and the question: "
        f"any of {list(ASSET_FACT_NAMES)}, each from the request field of that name when given. None (default) "
        "judges the rendered views alone; keep it off where file names mislead. Changes the verdict cache "
        'identity. Env: USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_FACTS (JSON list, e.g. ["path"]).',
    )
    logprob_asset_path_roots: Optional[list[str]] = Field(
        default=None,
        description="Regexes for a path's content root: the path fact keeps what follows the first match "
        "(else the whole path). Env: USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_PATH_ROOTS (JSON list).",
    )
    logprob_asset_path_max_chars: int = Field(
        default=300,
        ge=1,
        description="The path fact keeps the path's last N characters (its file and folders name the asset). "
        "Env: USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_PATH_MAX_CHARS.",
    )
    logprob_asset_caption_max_chars: int = Field(
        default=200,
        ge=1,
        description="The vlm_metadata_caption fact keeps the caption's first N characters. "
        "Env: USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_CAPTION_MAX_CHARS.",
    )
    logprob_yes_tokens: list[str] = Field(
        default_factory=lambda: ["yes", "y", "true"],
        description="Tokens (case-insensitive) whose probability mass counts as 'match' " "in the logprob method.",
    )
    logprob_no_tokens: list[str] = Field(
        default_factory=lambda: ["no", "n", "false"],
        description="Tokens (case-insensitive) whose probability mass counts as 'no match' " "in the logprob method.",
    )
    logprob_cover_min: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum combined Yes/No probability mass at a token position for the "
        "logprob verdict to be trusted. Below this the model is genuinely uncertain and the "
        "method abstains (see logprob_abstain_as_no).",
    )
    logprob_top_logprobs: int = Field(
        default=20,
        ge=1,
        le=20,
        description="How many top tokens to request per position (logprobs top_logprobs). "
        "The Yes/No token may not be rank-1, so a wide window is needed.",
    )
    logprob_max_tokens: int = Field(
        default=6,
        ge=1,
        description="Completion token cap for the logprob judge call. Only the first scored "
        "position is read; a few tokens covers models that emit a begin-of-answer token first.",
    )
    logprob_abstain_as_no: bool = Field(
        default=False,
        description="When the logprob method abstains (Yes/No mass below logprob_cover_min): "
        "False (default) yields NO verdict (fail-open — the hit is neither dropped nor "
        "reordered), True yields is_match=false (filter mode then drops it).",
    )
    logprob_image_text_query: bool = Field(
        default=True,
        description="An image query with a text query and ONE asset view: true (default) asks whether the candidate "
        "matches the text and the query image together (LOGPROB_JUDGE_PROMPT_IMAGE_TEXT_QUERY); false names the text "
        "in the image question, which passes unrelated assets more often. Part of the verdict cache identity when "
        "true. Env: USDSEARCH_VISION_VALIDATION_LOGPROB_IMAGE_TEXT_QUERY.",
    )
    max_tries: int = Field(default=3)
    reasoning_effort: Optional[str] = Field(default="none")
    extra_body: Optional[dict] = Field(
        default=None,
        description="Extra OpenAI request-body fields passed through to the endpoint. "
        "Needed e.g. for hub-served Qwen, where reasoning_effort alone does not disable "
        "thinking and the model burns the whole completion budget: set to "
        '{"chat_template_kwargs": {"enable_thinking": false}}. '
        "Env: USDSEARCH_VISION_VALIDATION_EXTRA_BODY (JSON).",
    )
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.0)
    yaml_filepath: str = Field(default=os.path.join(_HERE, "validation_fields.yaml"))
    prompt_filepath: str = Field(default=os.path.join(_HERE, "validation_prompt.txt"))
    domain_context_filepath: Optional[str] = Field(
        default=None,
        description="Optional path to domain-specific context file to customize validation for specific industries",
    )
    min_base64_detect_len: int = Field(
        default=100,
        description="Minimum string length (chars) before a query value is heuristically "
        "treated as a possible base64-encoded image; shorter strings are assumed to be "
        "plain text (env: USDSEARCH_VISION_VALIDATION_MIN_BASE64_DETECT_LEN).",
    )
    image_max_px: int = Field(
        default=0,
        ge=0,
        description="Longest edge (px) of every image sent to the VLM: larger query and "
        "reference images are shrunk (LANCZOS, aspect kept, never enlarged). 0 (default) "
        "sends them at their stored size. Part of the verdict cache identity when > 0. "
        "Env: USDSEARCH_VISION_VALIDATION_IMAGE_MAX_PX.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_validation_", populate_by_name=True, protected_namespaces=()
    )

    @field_validator("logprob_asset_facts")
    @classmethod
    def _known_asset_facts(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        """Known names only (a typo fails at startup); deduplicated in prompt order, [] -> None."""
        if value is None:
            return None
        unknown = sorted(set(value) - set(ASSET_FACT_NAMES))
        if unknown:
            raise ValueError(f"unknown asset facts {unknown}; known: {list(ASSET_FACT_NAMES)}")
        return [name for name in ASSET_FACT_NAMES if name in value] or None

    @field_validator("logprob_asset_path_roots")
    @classmethod
    def _compilable_path_roots(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        for pattern in value or []:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"invalid asset path root {pattern!r}: {exc}") from exc
        return value or None


class ValidationFields:
    def __init__(self, validation_config: Optional[ValidationConfig] = None):
        if validation_config is None:
            validation_config = ValidationConfig()
        self._validation_fields = self._load_validation_fields(validation_config.yaml_filepath)
        self._base_model = self._create_base_model()
        self._verdict_model = self._create_verdict_model()
        self._domain_context = self._load_domain_context(validation_config.domain_context_filepath)
        self._prompt = self._load_prompt(validation_config.prompt_filepath)

    @property
    def validation_fields(self) -> list[dict]:
        return self._validation_fields

    @property
    def base_model(self) -> type[BaseModel]:
        """The schema the generative method constrains the VLM's output to (yaml fields only)."""
        return self._base_model

    @property
    def verdict_model(self) -> type[BaseModel]:
        """What every method returns: the yaml schema with ``similarity_score`` widened to a float 0-100."""
        return self._verdict_model

    @property
    def prompt(self) -> str:
        return self._prompt

    @property
    def domain_context(self) -> str:
        """The rendered domain-context section (``""`` when none is configured or loadable).

        Baked into :attr:`prompt`; sent alone as the logprob judge's system prompt only
        when ``logprob_domain_context`` opts in."""
        return self._domain_context

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

    def _create_verdict_model(self) -> type[BaseModel]:
        # The yaml (and so the structured-output schema and the rendered prompt) keeps
        # asking the generative model for an integer 0-100; the verdict widens the
        # field to a float on a subclass so P(Yes) x 100 keeps its full resolution
        # while the cache identity stays byte-identical.
        verdict_model = create_model(
            "ValidationVerdict",
            __base__=self._base_model,
            similarity_score=(float, Field(ge=0.0, le=100.0, description=SIMILARITY_SCORE_DESCRIPTION)),
        )
        return cast(type[BaseModel], verdict_model)

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
