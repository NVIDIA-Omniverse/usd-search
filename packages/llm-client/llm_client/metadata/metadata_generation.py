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
import logging
import os
import sys
from typing import Any, Optional

# third party modules
import backoff
from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.messages.ai import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
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
    temperature: float = Field(default=0.0)

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_metadata_", populate_by_name=True, protected_namespaces=()
    )


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

        self.client = LLMClient(
            model=self._config.model,
            connection=connection,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            reasoning_effort=self._config.reasoning_effort,
            extra_body=self._config.extra_body,
        )
        self.client.with_structured_output(schema=self._metadata.base_model)

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

    def prepare_prompt(self, prompt: Optional[str], extra_context: Optional[str]) -> str:
        final_prompt = prompt if prompt is not None else self.prompt
        if extra_context:
            final_prompt = f"Additional context about the object: {extra_context}\n\n{final_prompt}"
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
    ) -> BaseModel | str:
        llm_only = base64_images is None
        prepared_prompt = self.prepare_prompt(prompt, extra_context)
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
