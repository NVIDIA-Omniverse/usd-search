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

"""Settings for the LLM query parser (query -> IR extraction).

The per-query parsing role. By default it runs on the shared LLM connection
(``USDSEARCH_LLM_*``, set once via ``llm_client.LLMConnectionConfig``) and only a
model id + tuning live here. It can optionally be pointed at its **own**
OpenAI-compatible endpoint via ``base_url`` / ``api_key`` (env
``USDSEARCH_LLM_PARSING_BASE_URL`` / ``USDSEARCH_LLM_PARSING_API_KEY``) — set either
to override just that part of the connection; leave both empty to keep using the
shared one. Env prefix ``USDSEARCH_LLM_PARSING_``.
"""

import os

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROMPT_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "prompts")


class LLMParseSettings(BaseSettings):
    """Configuration for the LLM query parser (query -> IR extraction)."""

    enabled: bool = Field(default=True)
    prompt_filepath: str = Field(
        default=os.path.join(_PROMPT_DIR, "llm_parsing_system_prompt.txt"),
        description="System-prompt template file ($catalog / $today placeholders).",
    )
    model: str = Field(
        default="gcp/google/gemini-3.1-flash-lite-preview",
        description="Model id (on the query-parsing LLM connection) used to extract the IR. "
        "Must support structured output (json_schema).",
    )
    base_url: str = Field(
        default="",
        description="Optional OpenAI-compatible base URL for a parsing-specific "
        "endpoint. Empty keeps the shared connection (USDSEARCH_LLM_BASE_URL).",
    )
    api_key: str = Field(
        default="",
        description="Optional bearer key for the parsing-specific endpoint. Empty "
        "keeps the shared connection's key (USDSEARCH_LLM_API_KEY).",
    )
    property_catalog_filepath: str = Field(
        default="",
        description="Optional usd_property_catalog.yaml (from the /usd-property-catalog skill). "
        "When set, the extractor grounds the generic usd_property filter on the real property "
        "keys/values present in the corpus (-> $properties in the prompt). Empty disables grounding.",
    )
    reasoning_effort: str = Field(default="none")
    max_tokens: int = Field(default=4096)
    temperature: float = Field(default=0.0)
    timeout_seconds: float = Field(
        default=15.0,
        description="Per-call timeout for the extractor LLM request.",
    )
    max_tries: int = Field(
        default=2,
        description="Max attempts for transient LLM errors (1 = no retry).",
    )
    cache_size: int = Field(
        default=256,
        description="In-process LRU size for identical query -> IR results.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_llm_parsing_", populate_by_name=True, protected_namespaces=()
    )


# The IR field registry — and the corpus-specific USD property keys behind the
# semantic-alias fields — now live in ``search_fields.yaml`` (see ``fields.py``),
# editable per deployment. Per-field property keys are env-overridable there via
# ``USDSEARCH_LLM_PARSING_<FIELD>_PROPERTY`` without touching code.
