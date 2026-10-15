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

import logging
from typing import List, Literal, Optional

from llm_client import ValidationConfig
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ValidationSettings(BaseSettings):
    """Configuration for the VISION-validation role (per-result VLM relevance check).

    Env prefix ``USDSEARCH_VISION_VALIDATION_``. The model runs on the shared LLM
    connection; only orchestration knobs + the model id live here.
    """

    enabled: bool = Field(default=True)
    mode: Literal["rerank", "filter", "annotate"] = Field(
        default="filter",
        description="What VLM verdicts do when validate_results=true: 'filter' "
        "(default) drops explicit non-matches, 'rerank' keeps every hit and "
        "reorders by verdict score, 'annotate' attaches verdicts without "
        "changing order or membership (the behavior before modes existed). "
        "Hits without a verdict are never demoted or dropped. "
        "See docs/vlm-validation.md, 'Validation modes'.",
    )
    model: str = Field(default="gcp/google/gemini-3.1-flash-lite")
    method: Literal["generative", "logprob"] = Field(
        default="generative",
        description="How each verdict is produced. 'generative' (default) has the VLM "
        "generate a structured JSON verdict. 'logprob' asks the short one-word Yes/No judge "
        "question and reads P(Yes) vs P(No) from the model's first-token log-probs in a "
        "single forward pass — much faster/cheaper, but the configured endpoint must "
        "return top_logprobs. Runs on the same shared LLM connection and model. "
        "See docs/vlm-validation.md ('Validation methods').",
    )
    logprob_domain_context: bool = Field(
        default=False,
        description="Send the configured domain context (domain_context_filepath) alone as the system prompt "
        "of the logprob judge (the generative method always renders it into its system prompt). Default "
        "false: the judge sends its bare question and no system prompt. Opting in re-prefills the context "
        "on every verdict and changes the verdict cache identity. See docs/vlm-validation.md ('Domain context').",
    )
    logprob_asset_facts: Optional[List[str]] = Field(
        default=None,
        description='Asset facts a TEXT query\'s logprob judge reads: any of "path", "vlm_metadata_caption", each '
        "from the request field of that name. None (default) judges the rendered views alone. Changes the verdict "
        "cache identity. See docs/vlm-validation.md ('Asset facts').",
    )
    logprob_asset_path_roots: Optional[List[str]] = Field(
        default=None,
        description="Regexes for a path's content root: the path fact keeps what follows the first match.",
    )
    logprob_asset_path_max_chars: int = Field(
        default=300, ge=1, description="The path fact keeps the path's last N characters."
    )
    logprob_asset_caption_max_chars: int = Field(
        default=200, ge=1, description="The vlm_metadata_caption fact keeps the caption's first N characters."
    )
    logprob_yes_tokens: List[str] = Field(
        default_factory=lambda: ["yes", "y", "true"],
        description="Tokens (case-insensitive) counted as 'match' in the logprob method.",
    )
    logprob_no_tokens: List[str] = Field(
        default_factory=lambda: ["no", "n", "false"],
        description="Tokens (case-insensitive) counted as 'no match' in the logprob method.",
    )
    logprob_cover_min: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Minimum combined Yes/No probability mass for a logprob verdict to be "
        "trusted; below it the method abstains (see logprob_abstain_as_no).",
    )
    logprob_top_logprobs: int = Field(
        default=20,
        ge=1,
        le=20,
        description="top_logprobs window requested per token position for the logprob method.",
    )
    logprob_max_tokens: int = Field(
        default=6,
        ge=1,
        description="Completion token cap for the logprob judge call.",
    )
    logprob_abstain_as_no: bool = Field(
        default=False,
        description="When the logprob method abstains (Yes/No mass below logprob_cover_min): "
        "False (default) yields NO verdict (fail-open), True yields is_match=false.",
    )
    logprob_image_text_query: bool = Field(
        default=True,
        description="An image query with a text query and one asset view: true (default) asks whether the candidate "
        "matches both (the question SimReady Central's validator uses); false names the text in the image "
        "question. Part of the verdict cache identity when true. See docs/vlm-validation.md ('Log-prob prompt').",
    )
    domain_context_filepath: Optional[str] = Field(default=None)
    max_concurrent: int = Field(
        default=50,
        ge=1,
        description="Maximum concurrent provider calls per API process.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        description="Deadline per verdict in seconds, measured from the moment the hit is queued, so it "
        "includes waiting for a max_concurrent slot under a backlog. A hit that misses it gets no verdict "
        "and stays fail-open; the batch continues.",
    )
    max_tries: int = Field(
        default=1,
        description="Max attempts for VLM validation calls (1 = no retries).",
    )
    cache_size: int = Field(
        default=100_000,
        description="In-process L1 LRU size for memoized validation verdicts, keyed by "
        "(config fingerprint, query, asset image identity). ~100k entries ≈ 256 MB of "
        "Python objects. 0 disables the L1 cache. Failed/None verdicts are never cached. "
        "The persistent L2 (Redis) cache is configured separately via "
        "USDSEARCH_VISION_VALIDATION_CACHE_* + REDIS_URL.",
    )
    max_images_per_validation: int = Field(
        default=1,
        ge=1,
        description="Maximum asset views sent to the VLM for one verdict, keeping "
        "the highest-ranked unique matched views first. No upper bound — but VLM "
        "cost and latency scale with it, so values above 8 log a warning.",
    )
    image_max_px: int = Field(
        default=0,
        ge=0,
        description="Longest edge (px) of every image sent to the VLM; larger query and "
        "reference images are shrunk (LANCZOS, never enlarged). 0 (default) sends them at "
        "their stored size. Part of the verdict cache identity when > 0. "
        "See docs/vlm-validation.md ('Server configuration').",
    )

    @field_validator("max_images_per_validation")
    @classmethod
    def _warn_on_high_view_budget(cls, value: int) -> int:
        if value > 8:
            logger.warning(
                "max_images_per_validation=%d exceeds the typical number of rendered "
                "views per asset (8); every verdict sends up to %d images to the VLM, "
                "so cost and latency scale accordingly.",
                value,
                value,
            )
        return value

    model_config = SettingsConfigDict(
        env_prefix="usdsearch_vision_validation_", populate_by_name=True, protected_namespaces=()
    )

    def to_validation_config(self) -> ValidationConfig:
        """Build the llm_client ValidationConfig (model runs on the shared connection)."""
        return ValidationConfig(
            model=self.model,
            domain_context_filepath=self.domain_context_filepath,
            max_tries=self.max_tries,
            method=self.method,
            logprob_yes_tokens=self.logprob_yes_tokens,
            logprob_no_tokens=self.logprob_no_tokens,
            logprob_cover_min=self.logprob_cover_min,
            logprob_top_logprobs=self.logprob_top_logprobs,
            logprob_max_tokens=self.logprob_max_tokens,
            logprob_abstain_as_no=self.logprob_abstain_as_no,
            logprob_image_text_query=self.logprob_image_text_query,
            logprob_domain_context=self.logprob_domain_context,
            logprob_asset_facts=self.logprob_asset_facts,
            logprob_asset_path_roots=self.logprob_asset_path_roots,
            logprob_asset_path_max_chars=self.logprob_asset_path_max_chars,
            logprob_asset_caption_max_chars=self.logprob_asset_caption_max_chars,
            image_max_px=self.image_max_px,
        )
