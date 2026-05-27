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

# standard modules
import asyncio
import logging
import time
from contextlib import asynccontextmanager

# thir party modules
from prometheus_client import Gauge

from search_utils import log_utils as lu

# local / proprietary modules
from search_utils.cache_utils.base import InMemoryCache

from . import StorageClient, StorageConnection
from .nucleus.auth import NucleusStorageClientAuthenticationError

logger = logging.getLogger(__name__)


class ConnectionRegistry:
    """Class to store different omniverse connections with authentication tokens

    Args:
        ov_server (str): nucleus server, which is used for requesting connections
        backlog_length (int, optional): lenght of the unathenticated connection backlog. Defaults to 1.
        registry_size (int, optional): maximum size of connection registry. Defaults to 2048.
    """

    def __init__(
        self,
        # ov_server: str,
        client: StorageClient,
        backlog_length: int = 1,
        registry_size: int = 256,
        connection_timeout: float = 3600,
        use_prom_metrics: bool = False,
        prom_metrics_labels: dict = {},
        connection_retry_delay_seconds: float = 5.0,
    ) -> None:
        self.client: StorageClient = client
        self.backlog_length = backlog_length
        self.registry_size = registry_size
        self.connection_timeout = connection_timeout
        self.connection_backlog = asyncio.Queue()
        self.use_prom_metrics = use_prom_metrics
        self.prom_metrics_labels = prom_metrics_labels
        self.connection_registry = InMemoryCache()
        self.backlog_ready = asyncio.Event()
        self.connection_retry_delay = connection_retry_delay_seconds

        if self.use_prom_metrics:
            self.nucleus_connection_registry_backlog_size = Gauge(
                "connection_registry_backlog_size",
                "connection registry backlog size",
                labelnames=list(self.prom_metrics_labels.keys()),
            )
            self.nucleus_connection_registry_backlog_size.labels(**self.prom_metrics_labels).set(0)
            self.nucleus_connection_registry_registry_size = Gauge(
                "connection_registry_registry_size",
                "connection registry registry size",
                labelnames=list(self.prom_metrics_labels.keys()),
            )
            self.nucleus_connection_registry_registry_size.labels(**self.prom_metrics_labels).set(0)
            self.connection_failure_count = Gauge(
                "connection_failure_count",
                "connection failure count",
                labelnames=["reason"] + list(self.prom_metrics_labels.keys()),
            )

        # create a task for creating connections
        loop = asyncio.get_event_loop()
        loop.create_task(self.connection_creation_task(backlog_length))
        loop.create_task(self.connection_release_on_timeout_task())
        loop.create_task(self.connection_release_on_registry_limit_exceed())

    def __len__(self):
        return len(self.connection_registry)

    async def connection_creation_task(self, backlog_length: int = 1):
        """Create some unathenticated connections to nucleus in the background,
        so that when needed - they will be provided in no time.

        Args:
            backlog_length (int, optional): maximum number of connections, kept in the backlog. Defaults to 1.
        """
        while True:
            try:
                if self.connection_backlog.qsize() < backlog_length:
                    c = await self.client.get_connection()
                    # c = await get_nucleus_connection(self.ov_server)
                    await self.connection_backlog.put(c)
                    # update prometheus metrics
                    if self.use_prom_metrics:
                        self.nucleus_connection_registry_backlog_size.labels(**self.prom_metrics_labels).inc(1)

                    self.backlog_ready.set()
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Connection creation error: {str(e)}\n Cause: {str(getattr(e, '__cause__', ''))}")
                if self.use_prom_metrics:
                    self.connection_failure_count.labels(reason="Establishment error", **self.prom_metrics_labels).inc(
                        1
                    )
                await asyncio.sleep(self.connection_retry_delay)

    async def connection_release_on_registry_limit_exceed(
        self,
    ):
        """Close connections when the registry size limit is reached"""
        while True:
            try:
                if len(self.connection_registry) > self.registry_size:
                    keys = list(self.connection_registry.last_accessed.keys())
                    tokens_to_del = keys[: (len(self.connection_registry.last_accessed) - self.registry_size)]

                    await asyncio.gather(*[self.release_connection(token) for token in tokens_to_del])
            except Exception as e:
                logger.error(f"Connection registry limit exceed exception: {str(e)}")
            finally:
                await asyncio.sleep(1)

    async def connection_release_on_timeout_task(
        self,
    ):
        """Close connections when the timeout is reached"""
        if self.connection_timeout > 0:
            while True:
                try:
                    for token in self.connection_registry.keys():
                        if time.time() - self.connection_registry.last_accessed[token] > self.connection_timeout:
                            await self.release_connection(token)
                        else:
                            # exit the loop as when going further down only more recent connections can be found
                            break
                except Exception as e:
                    logger.error(f"Connection release on timeout exception: {str(e)}")
                finally:
                    # release the async loop
                    await asyncio.sleep(1)

    async def _acquire_connection(
        self,
    ) -> StorageConnection:
        """Get connection from the backlog.

        Returns:
            Connection: nucleus connection
        """
        c = await self.connection_backlog.get()

        # update prometheus metrics
        if self.use_prom_metrics:
            self.nucleus_connection_registry_backlog_size.labels(**self.prom_metrics_labels).dec(1)

        self.backlog_ready.clear()
        return c

    async def get_authenticated_connection(self, token: str, timeout: float = 30) -> StorageConnection:
        """Get connection from backlog, auhtenticate it and store in connection registry

        Args:
            token (str): user authentication token
            timeout (float, optional): timeout for connection authentication. Defaults to 30.

        Raises:
            ConnectionError: when authentication process fails

        Returns:
            dict: connection and authentication parameters
        """
        # if token already in connection registry - return
        if token in self.connection_registry:
            return self.connection_registry[token]

        acquired = False
        try:
            # get nucleus connection and authenticate it
            with lu.print_wrapper(
                "Get nucleus connection",
                logger=logger.debug,
                print_after=False,
            ):
                c = await self._acquire_connection()
            acquired = True
        except Exception as e:
            logger.warning(f"Failed acquiring connection: {str(e)}")

        if not acquired:
            if self.use_prom_metrics:
                self.connection_failure_count.labels(reason="Acquiring error", **self.prom_metrics_labels).inc(1)
            raise ConnectionError("connection cannot be established")

        with lu.print_wrapper(
            "Authenticate connection",
            logger=logger.debug,
            print_after=False,
        ):
            try:
                connection: StorageConnection = await self.client.authenticate_connection(c, token=token)
            except ConnectionError as e:
                await self.client.close_connection(c)
                if self.use_prom_metrics:
                    self.connection_failure_count.labels(reason="Authentication error", **self.prom_metrics_labels).inc(
                        1
                    )
                raise NucleusStorageClientAuthenticationError(f"auth failed: {e}", reason=str(e))
        # update connection registry
        self.connection_registry[token] = connection

        if self.use_prom_metrics:
            self.nucleus_connection_registry_registry_size.labels(**self.prom_metrics_labels).inc(1)
        # return connection and authentication token
        return self.connection_registry[token]

    async def release_connection(self, token: str):
        """Release connection from registry

        Args:
            token (str): user authentication token
        """
        if token not in self.connection_registry.keys():
            return
        else:
            await self.client.close_connection(self.connection_registry[token]["conn"])
            # update prometheus metrics
            if self.use_prom_metrics:
                self.nucleus_connection_registry_registry_size.labels(**self.prom_metrics_labels).dec(1)
            try:
                del self.connection_registry[token]
            except KeyError:
                logger.info("connection registry item was already removed")

    @asynccontextmanager
    async def connection_context(self, token: str) -> StorageClient:
        try:
            conn: StorageConnection = await self.get_authenticated_connection(token)
            async with self.client.connection_context(connection=conn) as client:
                yield client
        finally:
            await self.release_connection(token)

    async def close_all(self):
        """Close all connections"""
        # release all connecions from registry
        for token in self.connection_registry:
            await self.release_connection(token)
        # close all connections from backlog
        while not self.connection_backlog.empty():
            await self.client.close_connection(await self.connection_backlog.get())
