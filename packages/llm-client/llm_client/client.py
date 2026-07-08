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

"""Lean OpenAI-compatible LLM/VLM client.

One shared connection (``LLMConnectionConfig`` — base_url + api_key, set once via
``USDSEARCH_LLM_*``) is reused by every role; each role only picks a ``model``. The
client wraps ``langchain_openai.ChatOpenAI`` and supports text + optional base64
images in, and Pydantic-structured or raw text out — the only capabilities the
search / validation / metadata roles need.
"""

import logging
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import LLMException, LLMLengthException

logger = logging.getLogger(__name__)


def _chain_contains(exc: BaseException, exc_type: type) -> bool:
    """Whether ``exc`` or anything in its cause/context chain is an ``exc_type``."""
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, exc_type):
            return True
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return False


# The endpoint the stack ships pointed at out of the box (an OpenAI-compatible
# server). Override with ``USDSEARCH_LLM_BASE_URL`` to use any other one.
DEFAULT_BASE_URL = "https://inference-api.nvidia.com"


class LLMConnectionConfig(BaseSettings):
    """Connection to **any** OpenAI-compatible chat-completions endpoint.

    The client is just ``ChatOpenAI``, so it works against any server that speaks
    the OpenAI API — vLLM, LiteLLM, Azure OpenAI, OpenAI itself, etc. The stack
    ships pointed at a default endpoint; swap it by setting ``USDSEARCH_LLM_BASE_URL``
    (and the matching ``USDSEARCH_LLM_API_KEY``). Read **once** and reused by every
    role, so the key/endpoint live in exactly one place.

    Env vars:
      - ``USDSEARCH_LLM_API_KEY`` — bearer key for the endpoint.
      - ``USDSEARCH_LLM_BASE_URL`` — base URL (defaults to the shipped endpoint;
        an empty value falls back to ``api.openai.com``).
    """

    api_key: str = Field(default="", description="Bearer key for the OpenAI-compatible endpoint.")
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="OpenAI-compatible base URL. Override to point at any OpenAI-API server.",
    )

    model_config = SettingsConfigDict(env_prefix="usdsearch_llm_", populate_by_name=True)


class LLMClient:
    """Thin wrapper over ``ChatOpenAI`` for one model on the shared connection.

    Args:
        model: model id to call (e.g. ``gcp/google/gemini-3.5-flash``).
        connection: shared connection config; defaults to ``LLMConnectionConfig()``.
        max_tokens: response cap (keep >= 4096 — reasoning models burn budget).
        temperature: sampling temperature; 0 = deterministic.
        max_retries: ChatOpenAI client-level retries (0 = fail fast; retries are
            usually handled at the role level).
        reasoning_effort: when set, sent as ``extra_body={"reasoning_effort": ...}``
            to disable/limit model "thinking". Defaults to ``"none"``. Set to ``None``
            (env empty) if a gateway/model rejects the field.
        extra_body: additional OpenAI request-body fields (merged after reasoning).
    """

    def __init__(
        self,
        model: str,
        *,
        connection: Optional[LLMConnectionConfig] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        max_retries: int = 0,
        reasoning_effort: Optional[str] = "none",
        extra_body: Optional[dict] = None,
    ) -> None:
        conn = connection or LLMConnectionConfig()
        self._model = model
        self._connection = conn

        body: dict[str, Any] = dict(extra_body or {})
        # reasoning_effort is a standard OpenAI request field; OpenAI-compatible
        # gateways (incl. Inference Hub's vLLM backends) ignore unknown body keys,
        # so "none" is a safe way to suppress chain-of-thought for structured output.
        if reasoning_effort:
            body.setdefault("reasoning_effort", reasoning_effort)

        kwargs: dict[str, Any] = dict(
            model=model,
            api_key=conn.api_key,
            # An empty base_url means "use ChatOpenAI's default" (api.openai.com).
            base_url=conn.base_url or None,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
        )
        if body:
            kwargs["extra_body"] = body

        self._base: BaseChatModel = ChatOpenAI(**kwargs)
        self._llm: BaseChatModel = self._base

    @property
    def model(self) -> str:
        return self._model

    @property
    def llm(self) -> BaseChatModel:
        return self._llm

    def with_structured_output(self, schema: BaseModel) -> None:
        """Constrain output to ``schema`` (re-derives from the base model each call)."""
        self._llm = self._base.with_structured_output(schema=schema)

    def _messages(self, base64_images: Optional[list[str]], prompt: str, system_prompt: Optional[str]) -> list[dict]:
        """Build an OpenAI chat message list with optional inline base64 images."""
        user_content: list[dict] = [{"type": "text", "text": prompt}]
        if base64_images is not None:
            for image in base64_images:
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}", "detail": "high"},
                    }
                )
        messages: list[dict] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        return messages

    async def ainvoke(self, prompt: str, system_prompt: str = None, base64_images: list[str] = None, **kwargs) -> Any:
        try:
            return await self._llm.ainvoke(input=self._messages(base64_images, prompt, system_prompt), **kwargs)
        except Exception as e:
            logger.error(e, exc_info=True)
            # finish_reason=length surfaces as openai.LengthFinishReasonError from the
            # structured-output path (an OpenAIError, not an APIError, so langchain
            # re-raises it unchanged). It is deterministic for a given prompt +
            # max_tokens — classify it so callers can skip pointless retries.
            from openai import LengthFinishReasonError

            if _chain_contains(e, LengthFinishReasonError):
                raise LLMLengthException(f"LLM hit the completion token limit (finish_reason=length): {e}") from e
            raise LLMException(f"LLM invocation failed: {e}") from e

    async def aping(self, timeout: float = 5.0) -> bool:
        """Lightweight reachability check: a tiny call that returns True iff it succeeds."""
        import asyncio

        try:
            await asyncio.wait_for(self._base.ainvoke(input=self._messages(None, "ping", None)), timeout=timeout)
            return True
        except Exception as e:  # noqa: BLE001 - reachability probe; any failure means "unavailable"
            logger.warning("LLM reachability check failed: %s", e)
            return False
