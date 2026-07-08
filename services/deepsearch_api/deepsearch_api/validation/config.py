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

from typing import Optional

from llm_client import ValidationConfig
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ValidationSettings(BaseSettings):
    """Configuration for the VISION-validation role (per-result VLM relevance check).

    Env prefix ``USDSEARCH_VISION_VALIDATION_``. The model runs on the shared LLM
    connection; only orchestration knobs + the model id live here.
    """

    enabled: bool = Field(default=True)
    model: str = Field(default="gcp/google/gemini-3.5-flash")
    domain_context_filepath: Optional[str] = Field(default=None)
    max_concurrent: int = Field(default=10)
    timeout_seconds: float = Field(default=30.0)
    max_tries: int = Field(
        default=1,
        description="Max attempts for VLM validation calls (1 = no retries).",
    )
    cache_size: int = Field(
        default=2048,
        description="In-process LRU size for memoized validation verdicts, keyed by "
        "(model, query, asset image identity). 0 disables caching. Failed/None "
        "verdicts are never cached.",
    )

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_validation_", populate_by_name=True, protected_namespaces=()
    )

    def to_validation_config(self) -> ValidationConfig:
        """Build the llm_client ValidationConfig (model runs on the shared connection)."""
        return ValidationConfig(
            model=self.model,
            domain_context_filepath=self.domain_context_filepath,
            max_tries=self.max_tries,
        )
