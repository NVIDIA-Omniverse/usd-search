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
import re
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .exceptions import (
    LLMBadRequestException,
    LLMException,
    LLMLengthException,
    ParsingException,
)

logger = logging.getLogger(__name__)


def _chain_find(exc: BaseException, exc_type: type) -> Optional[BaseException]:
    """First exception in ``exc``'s cause/context chain that is an ``exc_type``, or None."""
    seen: set[int] = set()
    cur: Optional[BaseException] = exc
    while cur is not None and id(cur) not in seen:
        if isinstance(cur, exc_type):
            return cur
        seen.add(id(cur))
        cur = cur.__cause__ or cur.__context__
    return None


def _chain_contains(exc: BaseException, exc_type: type) -> bool:
    """Whether ``exc`` or anything in its cause/context chain is an ``exc_type``."""
    return _chain_find(exc, exc_type) is not None


def _safe_validation_errors(validation_error: Any) -> tuple[tuple[str, str], ...]:
    """Return bounded, prompt-safe Pydantic error locations and type codes only."""
    safe_errors: list[tuple[str, str]] = []
    errors = validation_error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )
    for error in errors[:20]:
        location_parts: list[str] = []
        for part in error.get("loc", ()):
            if isinstance(part, int):
                location_parts.append(str(part))
            elif isinstance(part, str):
                # Locations can contain input-derived mapping keys. Keep only a
                # short identifier token so they cannot carry prompt instructions.
                token = re.sub(r"[^A-Za-z0-9_]", "_", part)[:64]
                if token:
                    location_parts.append(token)
        location = ".".join(location_parts) or "schema"
        error_type = re.sub(
            r"[^a-z0-9_.-]",
            "_",
            str(error.get("type", "validation_error")).lower(),
        )[:64]
        safe_errors.append((location, error_type or "validation_error"))
    return tuple(safe_errors) or (("schema", "validation_error"),)


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
      - ``USDSEARCH_LLM_DEFAULT_HEADERS`` — JSON object of extra HTTP headers sent
        on every request (e.g. ``{"X-HF-Bill-To": "my-org"}``).
    """

    api_key: str = Field(default="", description="Bearer key for the OpenAI-compatible endpoint.")
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        description="OpenAI-compatible base URL. Override to point at any OpenAI-API server.",
    )
    default_headers: dict[str, str] = Field(
        default_factory=dict,
        description="Extra HTTP headers sent on every request (JSON object in the env var).",
    )

    model_config = SettingsConfigDict(env_prefix="usdsearch_llm_", populate_by_name=True)


class LLMClient:
    """Thin wrapper over ``ChatOpenAI`` for one model on the shared connection.

    Args:
        model: model id to call (e.g. ``gcp/google/gemini-3.5-flash``).
        connection: shared connection config; defaults to ``LLMConnectionConfig()``.
        max_tokens: response cap (keep >= 4096 — reasoning models burn budget).
        temperature: sampling temperature; 0 = deterministic. ``None`` sends none
            (Claude Opus 5.x on the Inference Hub rejects the field).
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
        temperature: Optional[float] = 0.0,
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
            default_headers=conn.default_headers or None,
        )
        if body:
            kwargs["extra_body"] = body

        self._base: BaseChatModel = ChatOpenAI(**kwargs)
        self._llm: BaseChatModel = self._base

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        """The connection endpoint (base_url). Part of a role's answer identity;
        exposed for cache-key fingerprinting. Never exposes ``api_key``."""
        return self._connection.base_url

    @property
    def llm(self) -> BaseChatModel:
        return self._llm

    @property
    def base_llm(self) -> BaseChatModel:
        """The raw (never structured-output-wrapped) chat model.

        Repair/fixing parsers must run on this: a structured-output chain returns
        a BaseModel, which crashes langchain's ``retry_chain`` (it pipes the llm
        into a ``StrOutputParser``), so a fixing parser built on ``llm`` can never
        actually repair anything.
        """
        return self._base

    def with_structured_output(self, schema: BaseModel, method: Optional[str] = None) -> None:
        """Constrain output to ``schema`` (re-derives from the base model each call).

        ``method`` is langchain's: ``json_schema`` (its default), ``function_calling``
        or ``json_mode``. Claude on the Inference Hub needs ``json_mode``: the Hub
        turns a JSON schema into a forced tool call, which Claude Opus 5.x refuses."""
        if method:
            self._llm = self._base.with_structured_output(schema=schema, method=method)
        else:
            self._llm = self._base.with_structured_output(schema=schema)

    @staticmethod
    def _image_media_type(base64_image: str) -> str:
        """Media type for a base64-encoded image, sniffed from its magic bytes.

        The declared media type must match the actual bytes — strict
        OpenAI-compatible endpoints (some vLLM builds) reject mismatches.
        """
        if base64_image.startswith("iVBOR"):  # PNG magic \x89PNG
            return "image/png"
        if base64_image.startswith("/9j/"):  # JPEG magic \xff\xd8\xff
            return "image/jpeg"
        if base64_image.startswith("UklGR"):  # RIFF container (WebP)
            return "image/webp"
        return "image/png"

    def _messages(
        self,
        base64_images: Optional[list[str]],
        prompt: str,
        system_prompt: Optional[str],
        label_images: bool = False,
        image_labels: Optional[list[str]] = None,
    ) -> list[dict]:
        """Build an OpenAI chat message list with optional inline base64 images.

        With ``label_images`` each image is preceded by a "View i of N" text part
        so the model can reference and reconcile views (used by the metadata role,
        which sends many views of one asset). ``image_labels`` (one per image,
        e.g. "front", "spin 2", "open") names each view: "View i of N (front):".
        Without labels the text is unchanged.
        """
        if image_labels is not None and (base64_images is None or len(image_labels) != len(base64_images)):
            raise ValueError("image_labels must name every image, in order")
        user_content: list[dict] = [{"type": "text", "text": prompt}]
        if base64_images is not None:
            n = len(base64_images)
            for i, image in enumerate(base64_images, start=1):
                if label_images:
                    label = " ".join(str(image_labels[i - 1]).split()) if image_labels else ""
                    view = f"View {i} of {n} ({label}):" if label else f"View {i} of {n}:"
                    user_content.append({"type": "text", "text": view})
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{self._image_media_type(image)};base64,{image}", "detail": "high"},
                    }
                )
        messages: list[dict] = []
        if system_prompt is not None:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        return messages

    @staticmethod
    def _raise_llm_error(e: Exception) -> None:
        """Classify a raw invocation error and re-raise as an ``LLMException`` subtype."""
        logger.error(e, exc_info=True)
        # finish_reason=length surfaces as openai.LengthFinishReasonError from the
        # structured-output path (an OpenAIError, not an APIError, so langchain
        # re-raises it unchanged). It is deterministic for a given prompt +
        # max_tokens — classify it so callers can skip pointless retries.
        from openai import (
            APIStatusError,
            BadRequestError,
            LengthFinishReasonError,
            UnprocessableEntityError,
        )
        from pydantic import ValidationError

        if _chain_contains(e, LengthFinishReasonError):
            raise LLMLengthException(f"LLM hit the completion token limit (finish_reason=length): {e}") from e
        # The structured-output chain validates client-side; a schema violation
        # (e.g. off-vocabulary enum) is the MODEL's output failing validation, not
        # a transport failure. Deterministic at temperature 0 — retrying the same
        # request cannot succeed, so classify it as a parsing problem the caller
        # can repair (re-ask with the validation errors) instead of a retryable
        # LLMException.
        validation_error = _chain_find(e, ValidationError)
        if validation_error is not None:
            safe_errors = _safe_validation_errors(validation_error)
            summary = "; ".join(f"{location}: {error_type}" for location, error_type in safe_errors)
            raise ParsingException(
                f"LLM output failed schema validation: {summary}",
                validation_errors=safe_errors,
            ) from e
        status_error = _chain_find(e, APIStatusError)
        if status_error is not None and getattr(status_error, "status_code", None) == 413:
            raise LLMBadRequestException(
                "LLM rejected the request because its payload is too large (HTTP 413)",
                status_code=413,
            ) from e
        # A provider 4xx (400 BadRequest / 422 Unprocessable) means the request is
        # malformed or unsupported for this model — e.g. logprobs not supported.
        # It is permanent for a given config, so classify it distinctly: callers
        # surface a configuration error instead of a transient "service down".
        for exc_type in (BadRequestError, UnprocessableEntityError):
            match = _chain_find(e, exc_type)
            if match is not None:
                status = getattr(match, "status_code", None)
                raise LLMBadRequestException(f"LLM rejected the request (bad request): {e}", status_code=status) from e
        raise LLMException(f"LLM invocation failed: {e}") from e

    async def ainvoke(
        self,
        prompt: str,
        system_prompt: str = None,
        base64_images: list[str] = None,
        label_images: bool = False,
        image_labels: Optional[list[str]] = None,
        **kwargs,
    ) -> Any:
        try:
            return await self._llm.ainvoke(
                input=self._messages(
                    base64_images, prompt, system_prompt, label_images=label_images, image_labels=image_labels
                ),
                **kwargs,
            )
        except Exception as e:
            self._raise_llm_error(e)

    async def ainvoke_logprobs(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        base64_images: Optional[list[str]] = None,
        top_logprobs: int = 20,
        max_tokens: int = 6,
    ) -> list[dict]:
        """Plain (non-structured) chat completion that returns per-token top-logprobs.

        Used by the log-prob validation method: a single forward pass with
        ``logprobs=true`` from which the caller reads P(Yes) vs P(No) instead of
        generating a verdict. Always runs on ``self._base`` — never the
        structured-output-wrapped ``self._llm`` — so ``with_structured_output``
        does not force JSON decoding. Returns the OpenAI ``logprobs.content`` list
        (one entry per generated token, each carrying a ``top_logprobs`` list), or
        an empty list if the endpoint returned no logprobs.
        """
        # bind() layers per-call request params onto the shared ChatOpenAI without
        # mutating it: logprobs/top_logprobs turn on the distribution, and the tiny
        # max_tokens keeps the call to (effectively) one scored token.
        bound = self._base.bind(logprobs=True, top_logprobs=top_logprobs, max_tokens=max_tokens)
        try:
            message = await bound.ainvoke(input=self._messages(base64_images, prompt, system_prompt))
        except Exception as e:
            self._raise_llm_error(e)
        logprobs = (getattr(message, "response_metadata", None) or {}).get("logprobs") or {}
        return logprobs.get("content") or []

    async def aping(self, timeout: float = 5.0) -> bool:
        """Lightweight reachability check: a tiny call that returns True iff it succeeds."""
        import asyncio

        try:
            await asyncio.wait_for(self._base.ainvoke(input=self._messages(None, "ping", None)), timeout=timeout)
            return True
        except Exception as e:  # noqa: BLE001 - reachability probe; any failure means "unavailable"
            logger.warning("LLM reachability check failed: %s", e)
            return False
