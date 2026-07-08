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

"""Query -> IR extractor backed by the configured LLM provider.

Reuses llm-client's text-only ``ainvoke`` + LangChain
``with_structured_output`` (the same path the VLM validator uses) so the LLM is
constrained to emit a valid ``SearchIR``. Adds retry-with-backoff, a per-call
timeout, and an in-process LRU cache on the raw query string.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from collections import OrderedDict
from string import Template
from typing import Optional

from llm_client import (
    LLMClient,
    LLMConnectionConfig,
    LLMException,
    LLMLengthException,
    ParsingException,
)
from pydantic import ValidationError

from .config import LLMParseSettings
from .fields import build_field_catalog
from .grounding import build_property_grounding
from .models import SearchIR

logger = logging.getLogger(__name__)


class LLMParseExtractionError(RuntimeError):
    """Raised when the LLM extraction fails after all retries. The endpoint
    catches this and falls back to plain semantic search on the raw text."""


class LLMParseExtractor:
    """Extract a ``SearchIR`` from a free-text query via the query-parsing LLM.

    The system prompt is loaded from a file (``settings.prompt_filepath``) using
    ``$catalog`` / ``$today`` placeholders, so it is editable without touching code.
    """

    def __init__(self, settings: LLMParseSettings) -> None:
        self.settings = settings
        self._vlm = LLMClient(
            model=settings.model,
            connection=self._build_connection(settings),
            max_tokens=settings.max_tokens,
            temperature=settings.temperature,
            reasoning_effort=settings.reasoning_effort,
        )
        self._vlm.with_structured_output(SearchIR)
        self._catalog = build_field_catalog()
        # Optional corpus-property grounding for the generic usd_property field.
        # Built once at startup (the catalog file is static for the process);
        # empty string when not configured, so $properties expands to nothing.
        self._properties = build_property_grounding(settings.property_catalog_filepath)
        with open(settings.prompt_filepath, "r") as f:
            self._prompt_template = Template(f.read())
        self._cache: "OrderedDict[str, SearchIR]" = OrderedDict()

    @staticmethod
    def _build_connection(settings: LLMParseSettings) -> Optional[LLMConnectionConfig]:
        """Connection for the query-parsing LLM.

        Returns ``None`` (use the shared ``USDSEARCH_LLM_*`` connection) unless the
        deployment set a parsing-specific ``base_url`` and/or ``api_key`` — in
        which case only the provided field(s) override; any omitted field falls
        back to the shared connection's value via ``LLMConnectionConfig``.
        """
        if not (settings.base_url or settings.api_key):
            return None
        overrides = {}
        if settings.base_url:
            overrides["base_url"] = settings.base_url
        if settings.api_key:
            overrides["api_key"] = settings.api_key
        return LLMConnectionConfig(**overrides)

    async def aping(self) -> bool:
        """Reachability probe for the query-parsing LLM (used at startup to gate the feature)."""
        return await self._vlm.aping(timeout=self.settings.timeout_seconds)

    def _system_prompt(self) -> str:
        # safe_substitute leaves the JSON examples' braces untouched (only
        # $catalog / $properties / $today are substituted), so the prompt file
        # can contain literal JSON. $properties is "" unless a property catalog
        # is configured (see grounding.build_property_grounding).
        return self._prompt_template.safe_substitute(
            catalog=self._catalog,
            properties=self._properties,
            today=datetime.date.today().isoformat(),
        )

    def _cache_get(self, key: str) -> Optional[SearchIR]:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, key: str, value: SearchIR) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self.settings.cache_size:
            self._cache.popitem(last=False)

    async def extract(self, query: str) -> SearchIR:
        """Return the structured IR for ``query``, or raise LLMParseExtractionError."""
        cache_key = query.strip().lower()
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        system_prompt = self._system_prompt()
        last_exc: Optional[Exception] = None
        last_reason = "unknown error"
        attempt = 0
        for attempt in range(1, self.settings.max_tries + 1):
            retryable = True
            try:
                result = await asyncio.wait_for(
                    self._vlm.ainvoke(prompt=query, system_prompt=system_prompt, base64_images=None),
                    timeout=self.settings.timeout_seconds,
                )
                ir = result if isinstance(result, SearchIR) else SearchIR.model_validate(result)
                self._cache_put(cache_key, ir)
                return ir
            except asyncio.TimeoutError as exc:  # builtins.TimeoutError on Python >= 3.11
                last_exc = exc
                last_reason = (
                    f"the LLM call timed out after {self.settings.timeout_seconds:g}s "
                    f"(model={self.settings.model}; raise USDSEARCH_LLM_PARSING_TIMEOUT_SECONDS if persistent)"
                )
            except LLMLengthException as exc:  # subclass — must precede LLMException
                last_exc = exc
                last_reason = (
                    "the extractor LLM hit its completion token limit (finish_reason=length); "
                    "retrying cannot help — raise USDSEARCH_LLM_PARSING_MAX_TOKENS "
                    f"(currently {self.settings.max_tokens}) or use a different model"
                )
                retryable = False  # deterministic at temperature 0: a retry only doubles latency
            except (ParsingException, ValidationError) as exc:
                last_exc = exc
                last_reason = f"the LLM output did not match the SearchIR schema: {exc}"
            except LLMException as exc:
                last_exc = exc
                last_reason = f"the LLM call failed (likely transient): {exc}"
            except Exception as exc:  # noqa: BLE001 - safety net for unclassified errors
                last_exc = exc
                last_reason = f"unexpected error: {exc}"

            logger.warning("LLM query parsing attempt %d/%d failed: %s", attempt, self.settings.max_tries, last_reason)
            if not retryable:
                break
            if attempt < self.settings.max_tries:
                await asyncio.sleep(0.5 * attempt)  # linear backoff

        raise LLMParseExtractionError(
            f"Failed to extract structured query after {attempt} attempt(s): {last_reason}"
        ) from last_exc
