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

"""Batch VLM metadata generation (the VISION-metadata role).

Runs offline at crawl time against the one shared LLM connection; the model is
chosen by ``MetadataGenerationConfig.model`` (default a Gemini Pro preview).
"""

# standard modules
import json
import logging
import os
import sys
from typing import Any, Literal, Optional

# third party modules
import backoff
from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.messages.ai import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# local / proprietary modules
from ..client import LLMClient, LLMConnectionConfig
from ..exceptions import (
    LLMBadRequestException,
    LLMException,
    LLMLengthException,
    ParsingException,
)
from .metadata import Metadata

logger = logging.getLogger(__name__)

OUTPUT_PARSING_SUPPORTED = sys.version_info >= (3, 12)
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() in ("true", "1")


# Appended only when the caller labels its views or passes a name hint; without
# them the prompt is byte-identical to before.
LABELLED_VIEWS_SECTION = (
    "## Labelled views\n"
    "Each image is labelled with the view it shows (e.g. front, right, back, left, open). "
    'A view labelled "open" shows the asset with its moving parts (doors, drawers, lids) '
    "opened: use it to tell what the object is and which parts move, but describe the object "
    "itself, not one moment of it."
)
ASSET_HINT_SECTION = (
    "## Name hint\n"
    "What the asset's publisher says it is (its maker or brand, product name, model and file name): "
    "{hint}. The publishers are the manufacturers and partners who made these assets: always use "
    "their brand, company and product names and model numbers where the hint gives them, in the "
    'caption, object_type, queries and tags (for example "FANUC CRX-10iA collaborative robot '
    'arm"). Ignore any part of it that is only a hash or a random id. Describe what the views '
    "show; if the hint names a different kind of object than the views clearly show, follow the "
    "views for what the object is."
)
ASSET_HINT_MAX_CHARS = 600


def _is_permanent_llm_error(exc: Exception) -> bool:
    """Return whether retrying the same metadata request cannot succeed."""

    return isinstance(exc, (LLMBadRequestException, LLMLengthException))


class MetadataGenerationConfig(BaseSettings):
    """VISION-metadata role config (env ``USDSEARCH_VISION_METADATA_*``).

    Carries only a model + tuning; the connection (key/base_url) is the shared
    ``LLMConnectionConfig``.
    """

    # Default set by the 2026-08 metadata bake-off: won on faithfulness,
    # compliance, and searchability (see docs/models-and-config.md).
    model: str = Field(default="azure/openai/gpt-5.6-sol")
    max_tries: int = Field(default=3)
    reasoning_effort: Optional[str] = Field(default="none")
    extra_body: Optional[dict] = Field(
        default=None,
        description="Extra OpenAI request-body fields passed through to the endpoint. "
        "Needed e.g. for hub-served Qwen, where reasoning_effort alone does not disable "
        "thinking and the model burns the whole completion budget: set to "
        '{"chat_template_kwargs": {"enable_thinking": false}}. '
        "Env: USDSEARCH_VISION_METADATA_EXTRA_BODY (JSON).",
    )
    max_tokens: int = Field(default=4096)
    temperature: Optional[float] = Field(default=0.0)
    structured_output_method: Optional[Literal["json_schema", "json_mode", "function_calling"]] = Field(
        default=None,
        description="langchain's structured-output method; unset = json_schema, except json_mode for a "
        "Claude model (the Inference Hub turns a schema into a forced tool call Claude Opus 5.x refuses). "
        "Env: USDSEARCH_VISION_METADATA_STRUCTURED_OUTPUT_METHOD.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_metadata_", populate_by_name=True, protected_namespaces=()
    )

    @field_validator("reasoning_effort", "structured_output_method", mode="before")
    @classmethod
    def blank_is_unset(cls, value):
        # An empty env var means "send none" (e.g. a model that rejects the field).
        return None if isinstance(value, str) and not value.strip() else value


def is_claude_model(model: str) -> bool:
    return "claude" in model.lower()


def request_settings(config: MetadataGenerationConfig) -> dict:
    """The temperature, reasoning effort and structured-output method actually sent for ``config.model``.

    Claude (Opus 5.x) on the Inference Hub rejects ``temperature`` and a forced tool call, and takes no
    ``reasoning_effort``: for a Claude model none of the three is sent and the output is requested as
    JSON (``json_mode``) unless a method is configured. Every other model keeps its configured values."""
    if is_claude_model(config.model):
        return {
            "temperature": None,
            "reasoning_effort": None,
            "method": config.structured_output_method or "json_mode",
        }
    return {
        "temperature": config.temperature,
        "reasoning_effort": config.reasoning_effort,
        "method": config.structured_output_method,
    }


class MetadataGeneration:
    DEFAULT_SYSTEM_PROMPT = (
        "You are an AI specialist for cataloging 3D assets. "
        "Generate accurate, searchable metadata based on the provided images."
    )

    def __init__(
        self,
        config: Optional[MetadataGenerationConfig] = None,
        metadata: Optional[Metadata] = None,
        system_prompt: Optional[str] = None,
        connection: Optional[LLMConnectionConfig] = None,
    ):
        self._config = config or MetadataGenerationConfig()
        self._metadata = metadata or Metadata()
        self._system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

        settings = request_settings(self._config)
        self.client = LLMClient(
            model=self._config.model,
            connection=connection,
            max_tokens=self._config.max_tokens,
            temperature=settings["temperature"],
            reasoning_effort=settings["reasoning_effort"],
            extra_body=self._config.extra_body,
        )
        self.client.with_structured_output(schema=self._metadata.base_model, method=settings["method"])

        pydantic_parser: PydanticOutputParser[BaseModel] = PydanticOutputParser(
            pydantic_object=self._metadata.base_model
        )
        # The fixing parser must run on the RAW model: the structured-output
        # wrapper returns a BaseModel, which crashes the fixing retry_chain
        # (it ends in a StrOutputParser) — a fixing parser built on client.llm
        # could never repair anything.
        self.parser = OutputFixingParser.from_llm(
            parser=pydantic_parser,
            llm=self.client.base_llm,
        )

    @property
    def prompt(self) -> str:
        return self._metadata.prompt

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def config(self) -> MetadataGenerationConfig:
        return self._config

    @property
    def model_name(self) -> str:
        return self.client.model

    @property
    def model(self) -> str:
        return self.client.model

    async def aparse(self, content: str) -> BaseModel:
        try:
            metadata = await self.parser.aparse(content)
            if not isinstance(metadata, BaseModel):
                raise ParsingException(f"Expected BaseModel, got {type(metadata)}")
            return metadata
        except ParsingException:
            raise
        except Exception as e:
            logger.error("Failed to parse VLM output: %s", e, exc_info=True)
            raise ParsingException(f"Error parsing VLM output: {e}") from e

    def prepare_prompt(
        self,
        prompt: Optional[str],
        extra_context: Optional[str],
        image_labels: Optional[list[str]] = None,
        asset_hint: Optional[str] = None,
    ) -> str:
        final_prompt = prompt if prompt is not None else self.prompt
        if extra_context:
            final_prompt = f"Additional context about the object: {extra_context}\n\n{final_prompt}"
        if image_labels:
            final_prompt = f"{final_prompt}\n\n{LABELLED_VIEWS_SECTION}"
        hint = " ".join((asset_hint or "").split())[:ASSET_HINT_MAX_CHARS]
        if hint:
            final_prompt = f"{final_prompt}\n\n{ASSET_HINT_SECTION.format(hint=json.dumps(hint))}"
        return final_prompt

    def _extract_content(self, response: Any) -> str:
        if hasattr(response, "content"):
            return response.content
        return str(response)

    async def aparse_response(self, response: Any, parse_output: bool, llm_only: bool) -> BaseModel | str:
        if isinstance(response, BaseModel):
            return response

        if parse_output and not llm_only:
            content = self._extract_content(response)
            return await self.aparse(content)

        if isinstance(response, AIMessage):
            return response.content

        if OUTPUT_PARSING_SUPPORTED:
            raise ValueError(f"Unexpected response type: {type(response)}")

        return self._extract_content(response)

    def _build_invoke_kwargs(
        self,
        max_tokens: Optional[int],
        temperature: Optional[float],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if temperature is not None:
            kwargs["temperature"] = temperature
        return kwargs

    def _get_langfuse_kwargs(self) -> dict[str, Any]:
        if not LANGFUSE_ENABLED:
            return {}

        try:
            from langfuse.langchain import CallbackHandler

            return {"config": {"callbacks": [CallbackHandler()]}}
        except ImportError:
            logger.warning("Langfuse enabled but not installed. Run: pip install langfuse")
            return {}

    async def agenerate(
        self,
        base64_images: Optional[list[str]] = None,
        prompt: Optional[str] = None,
        extra_context: Optional[str] = None,
        parse_output: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        image_labels: Optional[list[str]] = None,
        asset_hint: Optional[str] = None,
    ) -> BaseModel | str:
        """``image_labels`` names each image in order ("front", "spin 2", "open");
        ``asset_hint`` is what the publisher says the asset is (maker, product name,
        model, file name); the prompt has the model use those names and follow the
        views for what the object is. Both default to None, which leaves the request
        exactly as before."""
        llm_only = base64_images is None
        if image_labels is not None:
            image_labels = [" ".join(str(label).split()) for label in image_labels]
            if base64_images is None or len(image_labels) != len(base64_images) or not all(image_labels):
                raise ValueError("image_labels must name every image, in order")
        prepared_prompt = self.prepare_prompt(prompt, extra_context, image_labels=image_labels, asset_hint=asset_hint)
        kwargs = self._build_invoke_kwargs(max_tokens, temperature)
        kwargs.update(self._get_langfuse_kwargs())

        try:
            ainvoke_fn = self.client.ainvoke
            if self.config.max_tries > 0:
                ainvoke_fn = backoff.on_exception(
                    backoff.expo,
                    LLMException,
                    max_tries=self.config.max_tries,
                    giveup=_is_permanent_llm_error,
                    logger=logger,
                )(ainvoke_fn)

            invoke_kwargs = dict(
                system_prompt=self.system_prompt,
                base64_images=base64_images,
                # Views of one asset: label them so the model can aggregate and
                # reconcile evidence across views (see prompt "How to analyze").
                label_images=True,
                **kwargs,
            )
            if image_labels is not None:
                invoke_kwargs["image_labels"] = image_labels
            try:
                response = await ainvoke_fn(prompt=prepared_prompt, **invoke_kwargs)
            except ParsingException as e:
                # Schema-validation failure (e.g. off-vocabulary enum) — the call
                # succeeded but the OUTPUT is wrong. Deterministic at temp 0, so a
                # plain retry can't help; re-ask once with the errors spelled out.
                logger.warning("VLM output failed schema validation, re-asking with errors: %s", e)
                validation_errors = e.validation_errors or (("schema", "validation_error"),)
                safe_error_summary = "\n".join(
                    f"- {location}: {error_type}" for location, error_type in validation_errors
                )
                repair_prompt = (
                    f"{prepared_prompt}\n\n## Correction\n"
                    "Your previous answer failed schema validation with the following "
                    "errors — fix them and return the full corrected JSON object:\n"
                    f"{safe_error_summary}"
                )
                response = await ainvoke_fn(prompt=repair_prompt, **invoke_kwargs)
        except (LLMException, ParsingException):
            raise
        except Exception as e:
            logger.error("VLM invocation failed: %s", e, exc_info=True)
            raise LLMException(f"Error invoking VLM: {e}") from e

        try:
            return await self.aparse_response(response, parse_output, llm_only)
        except ParsingException:
            raise
        except Exception as e:
            logger.error("Response parsing failed: %s", e, exc_info=True)
            raise ParsingException(f"Error parsing VLM output: {e}") from e
