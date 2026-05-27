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
import logging
import os
import sys
from typing import Any, Callable, Optional

# third party modules
import backoff
from langchain_classic.output_parsers import OutputFixingParser
from langchain_core.messages.ai import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

# local / proprietary modules
from ..vlm import BaseVLM, VLMService
from ..vlm.exceptions import ParsingException, VLMException
from .metadata import Metadata

logger = logging.getLogger(__name__)

OUTPUT_PARSING_SUPPORTED = sys.version_info >= (3, 12)
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() in ("true", "1")

_VLM_REGISTRY: dict[VLMService, Callable[[], BaseVLM]] = {}


def _register_vlm_factories() -> None:
    global _VLM_REGISTRY
    if _VLM_REGISTRY:
        return

    _VLM_REGISTRY = {
        VLMService.openai: lambda: __import__("vision_endpoint.vlm", fromlist=["OpenAIVLM"]).OpenAIVLM(),
        VLMService.anthropic: lambda: __import__("vision_endpoint.vlm", fromlist=["AnthropicVLM"]).AnthropicVLM(),
        VLMService.azure_openai: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["AzureOpenAIVLM"]
        ).AzureOpenAIVLM(),
        VLMService.mistralai: lambda: __import__("vision_endpoint.vlm", fromlist=["MistralAIVLM"]).MistralAIVLM(),
        VLMService.nim: lambda: __import__("vision_endpoint.vlm", fromlist=["NimVLM"]).NimVLM(),
        VLMService.google: lambda: __import__("vision_endpoint.vlm", fromlist=["GoogleVLM"]).GoogleVLM(),
        VLMService.qwen: lambda: __import__("vision_endpoint.vlm", fromlist=["QwenVLM"]).QwenVLM(),
        VLMService.qwen_alibaba: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["QwenAlibabaVLM"]
        ).QwenAlibabaVLM(),
        VLMService.inference_hub: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["InferenceHubVLM"]
        ).InferenceHubVLM(),
    }


class MetadataGenerationConfig(BaseSettings):
    model_config = {"env_prefix": "metadata_generation_"}

    vlm_service: VLMService = Field(default=VLMService.inference_hub)
    max_tries: int = Field(default=3)


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
    ):
        self._config = config or MetadataGenerationConfig()
        self._metadata = metadata or Metadata()
        self._system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT

        self.vlm: BaseVLM = self._create_vlm(self.vlm_service)
        self.vlm.with_structured_output(base_model=self._metadata.base_model)

        pydantic_parser: PydanticOutputParser[BaseModel] = PydanticOutputParser(
            pydantic_object=self._metadata.base_model
        )
        self.parser = OutputFixingParser.from_llm(
            parser=pydantic_parser,
            llm=self.vlm.vlm,
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
    def vlm_service(self) -> VLMService:
        return self._config.vlm_service

    @property
    def model_name(self) -> str:
        return self.vlm.model

    @property
    def model(self) -> str:
        return self.vlm.model

    def _create_vlm(self, vlm_service: VLMService) -> BaseVLM:
        _register_vlm_factories()

        if vlm_service not in _VLM_REGISTRY:
            supported = ", ".join(s.value for s in _VLM_REGISTRY.keys())
            raise ValueError(f"Unsupported VLM service: {vlm_service}. Supported: {supported}")

        return _VLM_REGISTRY[vlm_service]()

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

    def parse(self, content: str) -> BaseModel:
        try:
            metadata = self.parser.parse(content)
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

    def _parse_response_impl(
        self,
        response: Any,
        parse_output: bool,
        llm_only: bool,
        parser_func: Callable[[str], BaseModel],
    ) -> BaseModel | str:
        if isinstance(response, BaseModel):
            return response

        if parse_output and not llm_only:
            content = self._extract_content(response)
            return parser_func(content)

        if isinstance(response, AIMessage):
            return response.content

        if OUTPUT_PARSING_SUPPORTED:
            raise ValueError(f"Unexpected response type: {type(response)}")

        return self._extract_content(response)

    def parse_response(self, response: Any, parse_output: bool, llm_only: bool) -> BaseModel | str:
        return self._parse_response_impl(response, parse_output, llm_only, self.parse)

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

    def generate(
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
            invoke_fn = self.vlm.invoke
            if self.config.max_tries > 0:
                invoke_fn = backoff.on_exception(
                    backoff.expo,
                    VLMException,
                    max_tries=self.config.max_tries,
                    logger=logger,
                )(invoke_fn)

            response = invoke_fn(
                prompt=prepared_prompt,
                system_prompt=self.system_prompt,
                base64_images=base64_images,
                **kwargs,
            )
        except VLMException:
            raise
        except Exception as e:
            logger.error("VLM invocation failed: %s", e, exc_info=True)
            raise VLMException(f"Error invoking VLM: {e}") from e

        try:
            return self.parse_response(response, parse_output, llm_only)
        except ParsingException:
            raise
        except Exception as e:
            logger.error("Response parsing failed: %s", e, exc_info=True)
            raise ParsingException(f"Error parsing VLM output: {e}") from e

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
            ainvoke_fn = self.vlm.ainvoke
            if self.config.max_tries > 0:
                ainvoke_fn = backoff.on_exception(
                    backoff.expo,
                    VLMException,
                    max_tries=self.config.max_tries,
                    logger=logger,
                )(ainvoke_fn)

            response = await ainvoke_fn(
                prompt=prepared_prompt,
                system_prompt=self.system_prompt,
                base64_images=base64_images,
                **kwargs,
            )
        except VLMException:
            raise
        except Exception as e:
            logger.error("VLM invocation failed: %s", e, exc_info=True)
            raise VLMException(f"Error invoking VLM: {e}") from e

        try:
            return await self.aparse_response(response, parse_output, llm_only)
        except ParsingException:
            raise
        except Exception as e:
            logger.error("Response parsing failed: %s", e, exc_info=True)
            raise ParsingException(f"Error parsing VLM output: {e}") from e
