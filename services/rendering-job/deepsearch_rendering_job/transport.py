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

import asyncio
import json

# standard modules
import logging
from enum import Enum
from typing import Any, Dict

# third party modules
import aiohttp
import websockets
from pydantic import BaseModel, Field
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ContentType(BaseModel):
    path: str = Field(..., title="URL of the asset that is being loaded")
    content: str = Field(..., title="serialized content of rendered data")


class ResponsePayload(BaseModel):
    request: str = Field(..., title="request type")
    url: str = Field(..., title="URL of the asset that is being loaded")
    url_hash: str = Field(..., title="Hash of the URL that can be used as a key")
    payload: ContentType = Field(..., title="rendered data")


class ResponseStatus(str, Enum):
    ok = "ok"
    error = "error"
    transport_error = "transport_error"
    payload_to_large = "payload_to_large"


async def ws_send(url: str, content: ResponsePayload, n_retries: int = 20) -> Dict[str, Any]:
    """Send rendered data over websocket.

    Args:
        url (str): URL of the websocket server.
        content (dict): content that needs to be send over. Must be JSON serializable.
        n_retries (int, optional): number of times the transfer is attempted on error. Defaults to 20.

    Returns:
        dict: status of the operation and some debugging info in case of an error.
    """
    response = None
    # send data back
    for _ in range(n_retries):
        try:
            async with websockets.connect(url) as ws:
                await ws.send(json.dumps(content.dict()))

            return {"status": ResponseStatus.ok}
        except websockets.exceptions.ConnectionClosedError as exc_info:
            logger.error("%s: connection closed, retrying", str(exc_info))
            response = str(exc_info)
            await asyncio.sleep(1)
        except websockets.exceptions.ConnectionClosed as exc_info:
            logger.info("%s: connection closed", str(exc_info))
            response = str(exc_info)
            await asyncio.sleep(1)
        except Exception as exc_info:
            logger.error("Exception: %s", str(exc_info))
            response = str(exc_info)
            await asyncio.sleep(1)

    return {"status": ResponseStatus.error, "response": response}


async def http_send(url: str, content: ResponsePayload, n_retries: int = 20) -> Dict[str, Any]:
    """Send rendered data over http.

    Args:
        url (str): URL of the HTTP server.
        content (dict): content that needs to be send over. Must be JSON serializable.
        n_retries (int, optional): number of times the transfer is attempted on error. Defaults to 20.

    Returns:
        dict: status of the operation and some debugging info in case of an error.
    """
    # connect to receiving socket server
    response = None
    for _ in range(n_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=content.dict()) as resp:
                    if resp.status == 413:
                        return {
                            "status": ResponseStatus.payload_to_large,
                            "response": "payload too large",
                        }

                    jresp = await resp.json()
                    if resp.status == 200:
                        return {"status": ResponseStatus.ok, "response": jresp}
                    else:
                        response = jresp
        except Exception as exc_info:
            logger.exception("http send error: %s", str(exc_info))
            response = str(exc_info)
            await asyncio.sleep(1)

    return {"status": ResponseStatus.error, "response": response}


async def redis_send(url: str, content: ResponsePayload, n_retries: int = 20) -> Dict[str, Any]:
    """Send rendered data over http.

    Args:
        url (str): URL of the HTTP server.
        content (dict): content that needs to be send over. Must be JSON serializable.
        n_retries (int, optional): number of times the transfer is attempted on error. Defaults to 20.

    Returns:
        dict: status of the operation and some debugging info in case of an error.
    """

    for _ in range(n_retries):
        try:
            connection = Redis.from_url(url)
            res = dict(
                status=ResponseStatus.ok,
                response=await connection.set(content.url, json.dumps(content.dict())),
            )
            await connection.close()
            return res
        except Exception as exc_info:
            logger.exception("redis send error: %s", str(exc_info))
            response: str = str(exc_info)
            await asyncio.sleep(1)

    return {"status": ResponseStatus.error, "response": response}
