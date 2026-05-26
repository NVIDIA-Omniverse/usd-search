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

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from vision_endpoint.validation import ValidationConfig
from vision_endpoint.vlm import VLMService


class ValidationSettings(BaseSettings):
    """Configuration settings for VLM validation."""

    enabled: bool = True
    vlm_service: VLMService = Field(default=VLMService.azure_openai)
    domain_context_filepath: Optional[str] = Field(default=None)
    max_concurrent: int = 10
    timeout_seconds: float = 30.0
    max_tries: int = Field(
        default=1,
        description="Max attempts for VLM validation calls (1 = no retries). "
        "Controls vision-endpoint's retry logic on transient VLM errors.",
    )

    model_config = SettingsConfigDict(env_prefix="VLM_VALIDATION_")

    def to_validation_config(self) -> ValidationConfig:
        """Create a ValidationConfig from these settings."""
        return ValidationConfig(
            vlm_service=self.vlm_service,
            domain_context_filepath=self.domain_context_filepath,
            max_tries=self.max_tries,
        )
