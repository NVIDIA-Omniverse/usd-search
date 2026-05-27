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

"""Liveness probe + the response model and headers it shares with tests."""

import logging
from typing import Dict

from fastapi import APIRouter
from pydantic import BaseModel, Field

response_headers = {
    "cache-control": ["no-cache", "no-store", "max-age=0", "must-revalidate"],
    "expires": 0,
    "pragma": "no-cache",
}


class HealthResponse(BaseModel):
    health_code: str = Field(
        examples=["200"],
        description="Status code, OK if successful, otherwise error code.",
    )
    health_code_description: str = Field(examples=["OK"], description="Status description.")
    headers: Dict = Field(default=response_headers, description="Response headers.")


router = APIRouter(tags=["internal_health"])

logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse, include_in_schema=False)
async def health() -> HealthResponse:
    return HealthResponse(health_code="200", health_code_description="DeepSearch API is live")
