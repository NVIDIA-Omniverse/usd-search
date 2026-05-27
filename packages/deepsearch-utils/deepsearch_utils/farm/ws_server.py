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

# standard modules
import os

# third party modules
import websockets

# local / proprietary modules
from search_utils.cache_utils.redis_async import AsyncCacheRedis

from . import farm_utils_logger
from .farm_io import writer


class FarmWebsocketServer:
    def __init__(
        self,
        redis_url: str,
        redis_db: int,
        redis_ttl_seconds: int,
        internal_ws_host,
        internal_ws_port,
        max_queue=int(os.getenv("FARM_CLIENT_WS_MAX_QUEUE", "10000")),
    ) -> None:
        # output dictionary to hold results from FARM
        self.cache = AsyncCacheRedis(redis_url=redis_url, database=redis_db, ttl_seconds=redis_ttl_seconds)
        farm_utils_logger.info(
            f"FarmWebsocketServer configured to store results in {redis_url}/{redis_db} {redis_ttl_seconds=}"
        )
        self.internal_ws_host = internal_ws_host
        self.internal_ws_port = internal_ws_port
        self.max_queue = max_queue
        # init websocket server
        self.websocket_server()

    async def ws_task(self, ws, path):
        # recived data from client
        try:
            resp = await ws.recv()
        except websockets.exceptions.ConnectionClosedError as e:
            farm_utils_logger.exception(f"Websocket connection closed: {str(e)}")
            return

        try:
            await writer(resp, self.cache)
        except Exception as e:
            farm_utils_logger.exception(f"Data writing error: {e}")

    def websocket_server(self):
        asyncio.ensure_future(
            websockets.serve(
                self.ws_task,
                self.internal_ws_host,
                self.internal_ws_port,
                max_size=None,
                ping_timeout=None,
                ping_interval=None,
                max_queue=self.max_queue,
            )
        )

    def run(self):
        loop = asyncio.get_event_loop()
        loop.run_forever()


def run_farm_websocket(
    output_dict_redis_url: str,
    output_dict_redis_db: int,
    output_dict_redis_ttl_seconds: int,
    internal_ws_host: str,
    internal_ws_port: int,
):
    """Run websocket server

    Args:
        output_dict_redis_url (str): url of redis where results are stored
        output_dict_redis_db (int): db where results are stored
        internal_ws_host (str): host name or IP for the server
        internal_ws_port (int): port number for the server
    """
    ws = FarmWebsocketServer(
        redis_url=output_dict_redis_url,
        redis_db=output_dict_redis_db,
        redis_ttl_seconds=output_dict_redis_ttl_seconds,
        internal_ws_host=internal_ws_host,
        internal_ws_port=internal_ws_port,
    )
    ws.run()
