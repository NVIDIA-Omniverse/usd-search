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

import functools
import logging
from typing import Annotated, AsyncGenerator, Awaitable, Callable

import aiohttp
from asset_graph_service.db import BaseGraphDB
from asset_graph_service.db.neo4j import Neo4jDBBackend, get_settings
from fastapi import Depends, HTTPException
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from starlette.requests import Request

http_bearer = HTTPBearer(auto_error=False)
http_basic = HTTPBasic(auto_error=False)
http_api_key = APIKeyHeader(name="x-api-key", auto_error=False)

logger = logging.getLogger(__name__)


async def database(request: Request) -> AsyncGenerator[BaseGraphDB, None]:
    async with Neo4jDBBackend(request.app.neo4j_settings).session() as db:
        yield db


async def _verify_access(urls: list[str], endpoint: str, headers: dict) -> list[str]:
    headers_to_forward = {"x-api-key", "authorization"}
    headers = {k: v for k, v in headers.items() if k.lower() in headers_to_forward}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(endpoint, json={"urls": list(urls)}) as response:
            if response.status in [401, 403]:
                auth_response = await response.text()
                raise HTTPException(
                    status_code=response.status,
                    detail=f"Failed to verify access: {auth_response}",
                )
            elif response.status >= 500:
                auth_response = await response.text()
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to verify access: authorization service is unavailable. {auth_response}",
                )
            else:
                response_json = await response.json()
                logger.debug(
                    "Verify access: %s / %s URLs available",
                    len(response_json),
                    len(urls),
                )
                return response_json


async def verify_access(
    request: Request,
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    api_key_auth: Annotated[str, Depends(http_api_key)],
) -> Callable[[list[str]], Awaitable[list[str]]]:
    if not request.app.config.verify_access:
        logger.debug("Skipping access verification")

        async def _noop(urls: list[str]) -> list[str]:
            return urls

        return _noop
    return functools.partial(
        _verify_access,
        endpoint=request.app.config.verify_access_endpoint,
        headers=request.headers,
    )
