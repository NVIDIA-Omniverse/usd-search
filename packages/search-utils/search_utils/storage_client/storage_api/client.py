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
import logging
import os
import time
import warnings
from collections.abc import Iterable, Set
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)
from xml.dom.minicompat import StringTypes

from authlib.integrations.httpx_client import AsyncOAuth2Client
from google.protobuf import struct_pb2
from grpc import StatusCode, aio, ssl_channel_credentials
from nvidia.omniverse.notifications.consumer.v1beta.event_consumer_pb2 import (
    ConsumeNonDurableEventsRequest,
    ConsumeNonDurableEventsResponse,
    Event,
    FilterGroup,
    ResourceFilter,
)
from nvidia.omniverse.notifications.consumer.v1beta.event_consumer_pb2_grpc import (
    EventConsumerServiceStub,
)
from nvidia.omniverse.storage.capabilities.v1alpha.capabilities_pb2 import (
    ListServicesRequest,
    ListServicesResponse,
    ServiceEntry,
)
from nvidia.omniverse.storage.capabilities.v1alpha.capabilities_pb2_grpc import (
    CapabilitiesServiceStub,
)
from nvidia.omniverse.storage.filefolder.v1alpha.filefolder_service_pb2 import (
    FolderAddress,
    ListItem,
    ListResponse,
    ListStatRequest,
    ListStatResponse,
)
from nvidia.omniverse.storage.filefolder.v1alpha.filefolder_service_pb2_grpc import (
    FileFolderServiceStub,
)
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_pb2 import (
    AddressInfo,
    ResourceInfo,
)
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_service_pb2 import (
    DeleteRequest,
    EnumerateRequest,
    EnumerateResponse,
    StatRequest,
    StatResponse,
)
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_service_pb2_grpc import (
    FileObjectServiceStub,
)
from nvidia.omniverse.storage.metadata.v1alpha.metadata_pb2 import (
    GetMetadataRequest,
    GetMetadataResponse,
)
from nvidia.omniverse.storage.metadata.v1alpha.metadata_pb2_grpc import (
    MetadataServiceStub,
)

from .. import (
    CopyResult,
    EventMapping,
    FileTypeMapping,
    LocalFilePath,
    PathType,
    RemoteFilePath,
    RemoteFileUri,
    StorageClient,
    StorageConnection,
    TagAction,
    TagName,
    TagQueryResult,
    TagResultField,
    TagType,
    TagValue,
    VerifyBatchAccessResponse,
)
from ..data import ACL, SubscriptionSource, TagField, ThumbnailItem, ThumbnailLoadMode
from ..exceptions import AccessDeniedError
from ..utils import get_thumbnails_nucleus_style, match_patterns, run_callable
from .config import (
    STORAGE_CREATED,
    KnownStorageAPITypes,
    StorageAPIStorageClientConfig,
    ThumbnailStyle,
)
from .utils import download, quote_uri, unquote_uri, upload

logger = logging.getLogger(__name__)


class StorageAPIStorageClient(StorageClient):
    def __init__(self, config: StorageAPIStorageClientConfig) -> None:
        logger.debug("Initializing Storage API client with config %s", config)
        self.config = config

        self._file_object_service_stub: Optional[FileObjectServiceStub] = None
        self._capabilities_stub: Optional[CapabilitiesServiceStub] = None
        self._file_folder_service_stub: Optional[FileFolderServiceStub] = None
        self._metadata_service_stub: Optional[MetadataServiceStub] = None
        self._event_consumer_service_stub: Optional[EventConsumerServiceStub] = None
        self._listing_finished = asyncio.Event()
        self._services: Optional[List[ServiceEntry]] = None
        self.events_queue: Optional[asyncio.Queue] = None
        self.subscription_task: Optional[asyncio.Task] = None
        self._openid_token: Optional[Dict[str, str]] = None
        self._token_refresh_time: Optional[float] = None
        self._subscription_reconnect_token: Optional[str] = None
        self._channel: Optional[aio.Channel] = None
        self._notification_service_channel: Optional[aio.Channel] = None
        self._subscription_generator: Optional[AsyncIterator[ConsumeNonDurableEventsResponse]] = None

    @property
    def notification_service_grpc_endpoint(self) -> str:
        """
        Returns the notification service endpoint.
        If notification_service_grpc_endpoint is not set, returns the grpc endpoint.
        """
        if self.config.notification_service_grpc_endpoint is None:
            return self.config.grpc_endpoint
        return self.config.notification_service_grpc_endpoint

    async def get_metadata(
        self,
        uri: RemoteFileUri,
        user_metadata_keys: Optional[Union[List[str], str]] = None,
    ) -> GetMetadataResponse:
        await self.verify_services_initialized()
        if user_metadata_keys is None:
            user_metadata_keys = self.config.user_metadata_keys

        return await self.metadata_service_stub.GetMetadata(
            GetMetadataRequest(uri=uri, user_metadata_keys=user_metadata_keys),
            metadata=await self.get_grpc_request_metadata(),
        )

    @property
    def services(self) -> List[ServiceEntry]:
        if self._services is None:
            raise ValueError("Services are not initialized")
        return self._services

    def check_if_service_exists(self, service_name: str, version: Optional[str] = None) -> bool:
        """Check if a service exists in the list of services.

        Args:
            service_name (str): The name of the service to check.
            version (Optional[str], optional): The version of the service to check. Defaults to None.

        Returns:
            bool: True if the service exists, False otherwise.
        """
        for service in self.services:
            if service.service_name == service_name:
                if version is None:
                    return True
                elif version in service.service_versions:
                    return True
        return False

    @property
    def base_uri(self) -> Optional[str]:
        return self.config.base_uri

    @property
    def connection_info(self) -> str:
        return self.base_uri

    @property
    def _default_acl(self) -> Set[ACL]:
        return {ACL.admin, ACL.write, ACL.read}

    @property
    def channel(self) -> aio.Channel:
        if self._channel is None:
            raise ValueError("Channel is not initialized")
        return self._channel

    @property
    def notification_service_channel(self) -> aio.Channel:
        if self._notification_service_channel is None:
            raise ValueError("Notification service channel is not initialized")
        return self._notification_service_channel

    @property
    def file_folder_service_stub(self) -> FileFolderServiceStub:
        if self._file_folder_service_stub is None:
            if self.check_if_service_exists("filefolder"):
                self._file_folder_service_stub = FileFolderServiceStub(self.channel)
            else:
                raise ValueError("File folder service is not supported")
        return self._file_folder_service_stub

    @property
    def metadata_service_stub(self) -> MetadataServiceStub:
        if self._metadata_service_stub is None:
            if self.check_if_service_exists("metadata"):
                self._metadata_service_stub = MetadataServiceStub(self.channel)
            else:
                raise ValueError("Metadata service is not supported")
        return self._metadata_service_stub

    def get_path_from_uri(self, uri: str) -> RemoteFilePath:
        if self.base_uri is not None and uri.startswith(self.base_uri):
            return RemoteFilePath(uri[len(self.base_uri) :])
        elif self.base_uri is None:
            # if base_uri is not set, we assume that the path is already a full URI
            return RemoteFilePath(uri)
        return RemoteFilePath(uri)

    def get_uri_from_path(self, path: Union[RemoteFileUri, RemoteFilePath]) -> RemoteFileUri:
        if self.base_uri is not None and path.startswith(self.base_uri):
            return RemoteFileUri(path)
        elif self.base_uri is None:
            # if base_uri is not set, we assume that the path is already a full URI
            return RemoteFileUri(path)
        return RemoteFileUri(f"{self.base_uri.rstrip('/')}/{path.lstrip('/')}")

    def is_supported_uri(self, uri: RemoteFileUri) -> bool:
        return uri.startswith(self.base_uri) if self.base_uri is not None else True

    @asynccontextmanager
    async def notification_service_connection_context(
        self,
    ) -> AsyncIterator[EventConsumerServiceStub]:
        """Create asynchronous notification service connection context."""
        if self.config.ssl:
            creds = ssl_channel_credentials()
            async with aio.secure_channel(self.notification_service_grpc_endpoint, creds) as channel:
                self._notification_service_channel = channel
                self._event_consumer_service_stub = EventConsumerServiceStub(channel)
                try:
                    yield self._event_consumer_service_stub
                finally:
                    self._event_consumer_service_stub = None
                    self._notification_service_channel = None
                    if self._subscription_generator is not None and not self._subscription_generator.cancelled():
                        self._subscription_generator.cancel()
                        while not self._subscription_generator.cancelled():
                            await asyncio.sleep(0.1)
                        self._subscription_generator = None
        else:
            async with aio.insecure_channel(self.notification_service_grpc_endpoint) as channel:
                self._notification_service_channel = channel
                self._event_consumer_service_stub = EventConsumerServiceStub(channel)
                try:
                    yield self._event_consumer_service_stub
                finally:
                    self._notification_service_channel = None
                    self._event_consumer_service_stub = None
                    if self._subscription_generator is not None and not self._subscription_generator.cancelled():
                        self._subscription_generator.cancel()
                        while not self._subscription_generator.cancelled():
                            await asyncio.sleep(0.1)
                        self._subscription_generator = None

    @asynccontextmanager
    async def connection_context(self, *_, **__) -> AsyncIterator["StorageAPIStorageClient"]:
        """Create asynchronous connection context.

        Yields:
            Iterator[AsyncIterator["StorageAPIStorageClient"]]: resulting client
        """
        if self._channel is not None:
            # Already connected — re-use the existing channel and stubs.
            yield self
            return

        if self.config.ssl:
            creds = ssl_channel_credentials()
            async with aio.secure_channel(self.config.grpc_endpoint, creds) as channel:
                self._channel = channel
                self._file_object_service_stub = FileObjectServiceStub(channel)
                self._capabilities_stub = CapabilitiesServiceStub(channel)

                try:
                    yield self
                finally:
                    self._channel = None
                    self._file_object_service_stub = None
                    self._capabilities_stub = None
                    self._file_folder_service_stub = None
                    self._metadata_service_stub = None
        else:
            async with aio.insecure_channel(self.config.grpc_endpoint) as channel:
                self._channel = channel
                self._file_object_service_stub = FileObjectServiceStub(channel)
                self._capabilities_stub = CapabilitiesServiceStub(channel)

                try:
                    yield self
                finally:
                    self._channel = None
                    self._file_object_service_stub = None
                    self._capabilities_stub = None
                    self._file_folder_service_stub = None
                    self._metadata_service_stub = None

    @property
    def file_object_service_stub(self) -> FileObjectServiceStub:
        if self._file_object_service_stub is None:
            raise ValueError("FileObjectServiceStub is not initialized")
        return self._file_object_service_stub

    @property
    def capabilities_stub(self) -> CapabilitiesServiceStub:
        if self._capabilities_stub is None:
            raise ValueError("CapabilitiesServiceStub is not initialized")
        return self._capabilities_stub

    async def _get_token(self) -> str:
        if self.config.token is not None:
            return self.config.token
        if self.config.openid_client_id is not None and self.config.openid_client_secret is not None:
            if self._token_refresh_time is None or time.time() > self._token_refresh_time:
                client = AsyncOAuth2Client(
                    client_id=self.config.openid_client_id,
                    client_secret=self.config.openid_client_secret,
                    scope=self.config.openid_scope,
                    token_endpoint=self.config.openid_token_url,
                    grant_type=self.config.openid_grant_type,
                )
                self._openid_token = await client.fetch_token()
                self._token_refresh_time = time.time() + self.config.token_refresh_interval
                return self._openid_token["access_token"]
            else:
                return self._openid_token["access_token"]
        return None

    async def get_grpc_request_metadata(self) -> List[Tuple[str, str]]:
        """
        Metadata for Storage API.
        If headers are provided, they will be added to the metadata.
        If token is provided, it will be added to the metadata with the "authorization" key.
        """
        metadata = []
        if self.config.headers is not None:
            metadata = [(k, v) for k, v in self.config.headers.items()]
        token = await self._get_token()
        if token is not None:
            metadata.append(("authorization", f"Bearer {token}"))
        return metadata

    async def path_type_from_address_info(self, address_info: AddressInfo) -> PathType:
        """
        Extracts metadata from the address info.
        If storage_api_type is not set, it uses the Stat API to extract the metadata.
        If storage_api_type is set to sevan, it raises an error.
        """
        extra_metadata = {}
        if self.config.storage_api_type is None:
            try:
                resource_info: StatResponse = await self.file_object_service_stub.Stat(
                    StatRequest(resource_address=address_info.resource_address),
                    metadata=await self.get_grpc_request_metadata(),
                )
                extra_metadata = {"hash_value": resource_info.resource_info.resource_identity.encoded_identity}
            except aio.AioRpcError as e:
                if e.code() != StatusCode.NOT_FOUND:
                    logger.warning("Error getting path type from address info: %s", e)
                extra_metadata = {}
        elif self.config.storage_api_type == KnownStorageAPITypes.sevan:
            raise NotImplementedError("Metadata has to be extracted by using metadata API in Sevan")

        return PathType.model_construct(
            uri=self._convert_from_grpc_string(address_info.resource_address),
            type=(FileTypeMapping.folder if address_info.resource_address.endswith("/") else FileTypeMapping.asset),
            size=address_info.metadata.data_object_size,
            modified_date_seconds=address_info.metadata.last_modified_timestamp.ToDatetime().timestamp(),
            **extra_metadata,
        )

    async def path_type_from_resource_info(self, url: str, resource_info: ResourceInfo) -> PathType:
        """
        Extracts metadata from the resource info.
        If storage_api_type is not set, it uses the resource info to extract the metadata.
        If storage_api_type is set to sevan, it raises an error.
        """
        extra_metadata = {}
        if self.config.storage_api_type is None:
            extra_metadata = {"hash_value": resource_info.resource_identity.encoded_identity}
        elif self.config.storage_api_type == KnownStorageAPITypes.sevan:
            raise NotImplementedError("Metadata has to be extracted by using metadata API in Sevan")

        return PathType.model_construct(
            uri=self._convert_from_grpc_string(url),
            type=FileTypeMapping.folder if url.endswith("/") else FileTypeMapping.asset,
            size=resource_info.metadata.data_object_size,
            modified_date_seconds=resource_info.metadata.last_modified_timestamp.ToDatetime().timestamp(),
            **extra_metadata,
        )

    async def list_services(self) -> List[ServiceEntry]:
        list_services_response: ListServicesResponse
        list_services_response = await self.capabilities_stub.ListServices(
            ListServicesRequest(), metadata=await self.get_grpc_request_metadata()
        )
        return list_services_response.services

    def _convert_to_grpc_string(self, uri: RemoteFileUri) -> str:
        if self.config.apply_url_quote:
            return quote_uri(uri)
        else:
            return uri

    def _convert_from_grpc_string(self, uri: RemoteFileUri) -> str:
        if self.config.apply_url_quote:
            return unquote_uri(uri)
        else:
            return uri

    async def check_if_exists(self, uri: RemoteFileUri) -> Tuple[bool, Optional[Union[PathType, str]]]:
        # make sure URI is well-formed
        uri = self.get_uri_from_path(uri)
        try:
            item: StatResponse = await self.file_object_service_stub.Stat(
                StatRequest(resource_address=self._convert_to_grpc_string(uri)),
                metadata=await self.get_grpc_request_metadata(),
            )
            return True, await self.path_type_from_resource_info(uri, item.resource_info)
        except aio.AioRpcError as e:
            if e.code() == StatusCode.NOT_FOUND:
                logger.info("URI %s is not found: %s", uri, e)
                return False, None
            elif e.code() == StatusCode.ABORTED:
                logger.warning("Stat request with uri %s is aborted: %s", uri, e)
                return False, None
            elif e.code() == StatusCode.INVALID_ARGUMENT:
                logger.warning("Invalid argument: %s: %s", uri, e)
                return False, None
            elif e.code() == StatusCode.UNAVAILABLE:
                raise ConnectionError(f"Storage API is unavailable: {e}") from e
            else:
                raise e

    async def verify_services_initialized(self) -> None:
        """Verify that the services are initialized.
        If not, initialize them.
        """
        if self._services is None:
            self._services = await self.list_services()

    async def list_stat_wrapper(self, uri: RemoteFileUri) -> AsyncIterator[ListStatResponse]:
        try:
            item: ListStatResponse
            async for item in self.file_folder_service_stub.ListStat(
                ListStatRequest(folder=FolderAddress(uri=self._convert_to_grpc_string(uri))),
                metadata=await self.get_grpc_request_metadata(),
            ):
                yield item
        except aio.AioRpcError as e:
            if e.code() == StatusCode.NOT_FOUND:
                logger.warning("%s not found on the server: %s", uri, str(e))
            else:
                raise e from e

    async def list_enumerate_wrapper(self, uri: RemoteFileUri) -> AsyncIterator[EnumerateResponse]:
        try:
            async for item in self.file_object_service_stub.Enumerate(
                EnumerateRequest(resource_address=self._convert_to_grpc_string(uri)),
                metadata=await self.get_grpc_request_metadata(),
            ):
                yield item
        except aio.AioRpcError as e:
            if e.code() == StatusCode.NOT_FOUND:
                logger.warning("%s not found on the server: %s", uri, str(e))
            else:
                raise e from e

    async def list_items(
        self,
        path_list: Optional[List[RemoteFilePath]] = None,
        uri_list: Optional[List[RemoteFileUri]] = None,
        max_concurrent_requests: Optional[int] = -1,
        logging_timeout: Optional[float] = 10,
        listing_timeout: Optional[float] = 20,
        show_hidden: Optional[bool] = False,
        recursive: Optional[bool] = True,
        ignore_patterns: Optional[List[str]] = None,
        raise_on_error: Optional[bool] = True,
        list_type: Optional[str] = None,
        processing_fn: Optional[Callable[[PathType], Union[PathType, Awaitable[PathType]]]] = None,
        max_items: Optional[int] = None,
    ) -> AsyncIterator[PathType]:
        if uri_list is None and path_list is not None:
            logger.warning("path_list is deprecated - use uri_list instead")
            uri_list = [self.get_uri_from_path(path) for path in path_list]

        if uri_list is None:
            uri_list = []

        await self.verify_services_initialized()

        # Mark that listing of items has started
        self._listing_finished.clear()

        if not self.config.ignore_filefolder_api and self.check_if_service_exists("filefolder"):
            logger.info("Listing items using list")
            async for item in self._list_items_using_list(uri_list, ignore_patterns, processing_fn, max_items):
                item.source = SubscriptionSource.recursive_list.value
                yield item
        else:
            logger.info("Listing items using enumerate")
            async for item in self._list_items_using_enumerate(uri_list, ignore_patterns, processing_fn, max_items):
                item.source = SubscriptionSource.recursive_list.value
                yield item

        logger.debug("Storage API listing complete")
        # Mark that listing of items has finished
        self._listing_finished.set()

    async def _list_items_using_list(
        self,
        uri_list: List[RemoteFileUri],
        ignore_patterns: List[str],
        processing_fn: Optional[Callable[[PathType], Union[PathType, Awaitable[PathType]]]] = None,
        max_items: Optional[int] = None,
    ) -> AsyncIterator[PathType]:
        item_count = 0
        iterators: List[Tuple[AsyncIterator[ListResponse], Optional[RemoteFileUri]]] = []

        if len(uri_list) == 0:
            iterators = [
                (
                    self.file_folder_service_stub.ListStat(
                        ListStatRequest(folder=FolderAddress(uri=f"{self.base_uri.rstrip('/')}/")),
                        metadata=await self.get_grpc_request_metadata(),
                    ),
                    None,
                )
            ]
        else:
            for uri in uri_list:

                # check if the items is the actual key in the storage API - process it directly.
                # if the uri is not a key, but rather a prefix (folder) - enumerate the items in the folder.
                if match_patterns(uri, patterns=ignore_patterns):
                    continue

                exists, item = await self.check_if_exists(uri)
                # check if the URL is a folder - if not - return it back
                if exists:
                    item_count += 1
                    if processing_fn is None:
                        yield item
                    else:
                        yield await run_callable(processing_fn, item)
                else:
                    iterators.append((self.list_stat_wrapper(uri), uri))

        iterators_count = len(iterators)

        # prepare paths
        list_stat_response: ListStatResponse
        for iterator, uri in iterators:
            async for list_stat_response in iterator:
                subfolder_addresses: FolderAddress
                for subfolder_addresses in getattr(list_stat_response, "subfolder_addresses", []):

                    if match_patterns(subfolder_addresses.uri, patterns=ignore_patterns):
                        continue

                    iterators.append(
                        (
                            self.list_stat_wrapper(subfolder_addresses.uri),
                            subfolder_addresses.uri,
                        )
                    )

                item: ListItem
                for item in getattr(list_stat_response, "entries", []):
                    item_count += 1

                    if match_patterns(item.resource_address, patterns=ignore_patterns):
                        continue

                    if processing_fn is None:
                        yield await self.path_type_from_resource_info(
                            url=item.resource_address, resource_info=item.resource_info
                        )
                    else:
                        yield await run_callable(
                            processing_fn,
                            await self.path_type_from_resource_info(
                                url=item.resource_address,
                                resource_info=item.resource_info,
                            ),
                        )

                    if max_items is not None and item_count >= max_items * iterators_count:
                        break

                if max_items is not None and item_count >= max_items * iterators_count:
                    break

            if max_items is not None and item_count >= max_items * iterators_count:
                break

    async def _list_items_using_enumerate(
        self,
        uri_list: List[RemoteFileUri],
        ignore_patterns: List[str],
        processing_fn: Optional[Callable[[PathType], Union[PathType, Awaitable[PathType]]]] = None,
        max_items: Optional[int] = None,
    ) -> AsyncIterator[PathType]:
        item_count = 0
        iterators: List[Tuple[AsyncIterator[EnumerateResponse], Optional[RemoteFileUri]]] = []
        if len(uri_list) == 0:
            iterators = [(self.list_enumerate_wrapper(self.base_uri), None)]
        else:
            for uri in uri_list:

                # check if the items is the actual key in the storage API - process it directly.
                # if the uri is not a key, but rather a prefix (folder) - enumerate the items in the folder.
                if match_patterns(uri, patterns=ignore_patterns):
                    continue

                exists, item = await self.check_if_exists(uri)
                if exists and item.type == FileTypeMapping.asset:
                    item_count += 1
                    if processing_fn is None:
                        yield item
                    else:
                        yield await run_callable(processing_fn, item)
                else:
                    iterators.append((self.list_enumerate_wrapper(uri), uri))

        # prepare paths
        list_queue: asyncio.Queue[PathType] = asyncio.Queue(maxsize=self.config.list_queue_limit)
        queue_population_finished = asyncio.Event()

        async def populate_list_queue() -> None:
            item_count = 0
            for iterator, _ in iterators:
                async for enumerate_response in iterator:
                    for item in enumerate_response.items:
                        if match_patterns(item.resource_address, patterns=ignore_patterns):
                            continue
                        await list_queue.put(item)
                        item_count += 1
                        if max_items is not None and item_count >= max_items:
                            queue_population_finished.set()
                            return

            queue_population_finished.set()

        # create listing task to accumulate all items and not be bottle-necked by Stat command
        queue_population_task = asyncio.create_task(populate_list_queue())

        try:
            while not (queue_population_finished.is_set() and list_queue.empty()):
                try:
                    item = await asyncio.wait_for(list_queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    continue
                if processing_fn is None:
                    yield await self.path_type_from_address_info(item)
                else:
                    yield await run_callable(processing_fn, await self.path_type_from_address_info(item))

        finally:
            if not queue_population_finished.is_set():
                queue_population_task.cancel()
            try:
                await queue_population_task
            except asyncio.CancelledError:
                pass

    def prepare_subscription_request(
        self,
        path: Optional[str] = None,
        filter_type: ResourceFilter.FilterType = ResourceFilter.FilterType.FILTER_TYPE_STARTS_WITH_GREEDY,
        storage_events: List[str] = [STORAGE_CREATED],
    ) -> Iterator[ConsumeNonDurableEventsRequest]:
        """
        Prepare a request to subscribe to notifications.
        """
        request = ConsumeNonDurableEventsRequest(reconnect_token=self._subscription_reconnect_token)

        storage_resource_filter = ResourceFilter(
            filter_type=filter_type,
            resource_id=self.get_uri_from_path(path),
        )

        for event_type in storage_events:
            fg = FilterGroup(event_type=event_type)
            fg.filters.append(storage_resource_filter)
            request.filter_groups.append(fg)

        def request_iterator() -> Iterator[ConsumeNonDurableEventsRequest]:
            for _ in range(0, 1):
                yield request

        return request_iterator()

    async def subscribe_to_notifications(self, queue: asyncio.Queue, path: Optional[str] = None) -> None:
        """
        Subscribe to notifications.
        """

        self._subscription_generator = None

        while True:
            try:
                request_iterator: Iterator[ConsumeNonDurableEventsRequest] = self.prepare_subscription_request(path)

                async with self.notification_service_connection_context():
                    non_durable_event: ConsumeNonDurableEventsResponse
                    self._subscription_generator = self._event_consumer_service_stub.ConsumeNonDurableEvents(
                        request_iterator,
                        metadata=await self.get_grpc_request_metadata(),
                    )
                    async for non_durable_event in self._subscription_generator:

                        if non_durable_event.reconnect_token:
                            self._subscription_reconnect_token = non_durable_event.reconnect_token

                        event: Event
                        for event in non_durable_event.events:
                            if event.message.fields:
                                for (
                                    field_key,
                                    field_value,
                                ) in event.message.fields.items():
                                    if field_key == "resource_address":
                                        exists, item = await self.check_if_exists(field_value.string_value)
                                        if exists:
                                            item.source = SubscriptionSource.subscription.value
                                            queue.put_nowait(item)
                                        else:
                                            logger.debug("Resource missing: %s", field_value.string_value)
            except aio.AioRpcError as e:
                if e.code() == StatusCode.PERMISSION_DENIED or e.code() == StatusCode.UNAUTHENTICATED:
                    logger.error("Permission denied (likely expired token)")
                    continue
                else:
                    queue.put_nowait(e)
                    raise e from e
            except Exception as e:
                queue.put_nowait(e)
                raise e from e

    async def list_items_and_subscribe(
        self,
        uri: Optional[
            str
        ] = None,  # DEPRECATED - use `path` instead; `uri` is kept for backwards compatibility but both `uri` and `path` expect a path NOT AN URI
        path: Optional[str] = None,
        batch_size: Optional[int] = -1,
        logging_timeout: Optional[float] = 10,
        listing_timeout: Optional[float] = 20,
        show_hidden: Optional[bool] = False,
        ignore_patterns: Optional[List[str]] = None,
        raise_on_error: Optional[bool] = True,
        list_type: Optional[str] = None,
        recursive: Optional[bool] = True,
        processing_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[List[PathType]]:
        if uri and path is not None:
            raise ValueError("Setting both `uri` and `path` is not allowed")
        if uri is not None:
            path = uri
            warnings.warn(
                "`uri` parameter of NucleusStorageClient.list_items_and_subscribe is deprecated; use `path` instead",
                DeprecationWarning,
            )

        await self.verify_services_initialized()

        if self.config.notification_subscription_enabled:
            self.events_queue = asyncio.Queue()
            self.subscription_task = asyncio.create_task(
                self.subscribe_to_notifications(
                    self.events_queue,
                    path=self.get_uri_from_path(path) if path is not None else None,
                )
            )

        # update path to be a full URI
        if ignore_patterns is None:
            ignore_patterns = []
        while True:
            logger.info(
                "Scanning Storage API '%s' for path=%s...",
                self.config.grpc_endpoint,
                path,
            )
            n_items = 0
            async for item in self.list_items(
                uri_list=([RemoteFileUri(self.get_uri_from_path(path))] if path is not None and path != "/" else []),
                logging_timeout=logging_timeout,
                show_hidden=show_hidden,
                ignore_patterns=ignore_patterns,
                raise_on_error=raise_on_error,
                recursive=recursive,
                list_type=list_type,
            ):
                if self.config.notification_subscription_enabled:
                    if self.subscription_task is not None and self.subscription_task.done():
                        raise self.subscription_task.exception()
                    if self.events_queue is not None and not self.events_queue.empty():
                        yield [self.events_queue.get_nowait()]

                n_items += 1
                logger.debug("Found item %s", item.uri)
                yield [item]

            logger.info(
                "Scan of Storage API backend '%s' for path=%s finished, found %s items",
                self.config.grpc_endpoint,
                path,
                n_items,
            )

            if self.config.notification_subscription_enabled:
                while True:
                    if self.subscription_task is not None and self.subscription_task.done():
                        raise self.subscription_task.exception()
                    if self.events_queue is not None:
                        yield [await self.events_queue.get()]

            else:
                if self.config.re_scan_timeout is None or self.config.re_scan_timeout <= 0:
                    logger.info("Re-scanning is disabled")
                    await asyncio.sleep(float("inf"))
                else:
                    logger.info("Re-scanning in %ss", self.config.re_scan_timeout)
                    await asyncio.sleep(self.config.re_scan_timeout)

    async def _upload_file_contents(self, file_contents: bytes, key: Union[RemoteFilePath, RemoteFileUri]) -> None:
        key = self.get_uri_from_path(key)
        logger.debug("Uploading file key=%s", key)
        t_start = datetime.now()

        try:
            await upload(
                self.file_object_service_stub,
                self._convert_to_grpc_string(key),
                upload_preference=self.config.upload_preference,
                content=BytesIO(file_contents),
                metadata=await self.get_grpc_request_metadata(),
            )
        except aio.AioRpcError as e:
            if e.code() == StatusCode.PERMISSION_DENIED or e.code() == StatusCode.UNAUTHENTICATED:
                raise AccessDeniedError(f"failed to upload asset to '{key}'") from e
            else:
                raise e from e

        duration_seconds = (datetime.now() - t_start).total_seconds()
        logger.debug("Uploading file key=%s done in %ss", key, duration_seconds)

    async def upload_items_content(
        self,
        item_dict: Dict[RemoteFileUri, bytes],
        overwrite_content: bool = True,
        # overwrite_if_fn: Optional[Callable] = None,
    ) -> None:
        logger.debug("Uploading a batch of %s files", len(item_dict))
        await asyncio.gather(*[self._upload_file_contents(content, uri) for uri, content in item_dict.items()])

    async def _upload_file(
        self,
        local_file: str,
        key: Union[RemoteFilePath, RemoteFileUri],
    ) -> None:
        key = self.get_uri_from_path(key)
        # reading the content
        if os.path.exists(local_file):
            with open(local_file, "rb") as f:
                content = f.read()
            # uploading the content
            await self._upload_file_contents(content, key)
        else:
            logger.warning(f"File {local_file} does not exist. ")

    async def upload_items(
        self,
        item_dict: Dict[RemoteFileUri, LocalFilePath],
        overwrite_content: bool = True,
        overwrite_if_fn: Optional[Callable[[PathType], bool]] = None,
    ) -> None:
        logger.debug("Uploading a batch of %s files", len(item_dict))
        await asyncio.gather(*[self._upload_file(local_file_path, uri) for uri, local_file_path in item_dict.items()])

    def is_valid_uri(self, uri: RemoteFileUri) -> bool:
        return self.is_supported_uri(uri)

    async def batch_verify_access(
        self,
        uri_list: List[RemoteFileUri],
        max_nucleus_requests: int = 512,
        batch_return: bool = True,
        return_meta: bool = False,
    ) -> AsyncIterator[List[VerifyBatchAccessResponse]]:
        # NOTE: Currently this method only checks if paths exist on the bucket, it does not check the actual ACL
        for idx in range(0, len(uri_list), max_nucleus_requests):
            uris_batch = uri_list[idx : idx + max_nucleus_requests]

            batch_exists_results = await asyncio.gather(*[self.check_if_exists(uri) for uri in uris_batch])

            yield [
                VerifyBatchAccessResponse(uri=uri, exists=exists_result, acl=self._default_acl)
                for uri, (exists_result, _) in zip(uris_batch, batch_exists_results)
            ]

    def get_backend_from_uri(self, uri: RemoteFileUri) -> Optional["StorageAPIStorageClient"]:
        return self

    async def close_connection(self, conn: Optional[StorageConnection] = None) -> None:
        pass

    async def download_file_content(
        self, uri: RemoteFileUri, etag: str = "", timeout: Optional[float] = -1
    ) -> bytearray:
        """Download the file from omniverse.

        Args:
            conn: omniverse connection
            str uri: path to a file location in omniverse
            str etag: unique ID of the file. Can be set to ``""``. Default: ``""``
            logger: logging function
        """

        # make sure timeout is int
        if timeout is None:
            timeout = -1

        file_exists, _ = await self.check_if_exists(uri)

        if not file_exists:
            raise FileNotFoundError(f"File {uri} does not exist on the omniverse server")

        data = await download(
            self.file_object_service_stub,
            self._convert_to_grpc_string(uri),
            download_preference=self.config.download_preference,
        )

        return data

    async def download_items(self, item_dict: Dict[LocalFilePath, RemoteFileUri], cap_size: float = -1) -> bool:
        # TODO: add cap size functionality, for now the data is not capped
        was_capped = False
        for local_file_path, remote_file_uri in item_dict.items():
            try:
                data = await self.download_file_content(remote_file_uri)
            except Exception as exc:
                raise exc

            # create destination folder if it does not exist
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)

            with open(local_file_path, "wb") as fl:
                fl.write(data)

            logger.debug("%s downloaded to %s", remote_file_uri, local_file_path)
        return was_capped

    async def get_item(self, uri: Union[RemoteFileUri, RemoteFilePath]) -> Optional[PathType]:
        """Get single asset metadata from the storage backend

        Args:
            uri (str): Asset URI

        Returns:
            Optional[PathType]: Asset metadata if it exists and None otherwise.
        """
        _, item = await self.check_if_exists(uri)
        return item

    async def check_connection(self) -> bool:
        try:
            await self.list_services()
            return True
        except Exception as e:
            logger.error(f"Error checking connection: {e}")
            return False

    async def delete_items(self, uri_list: Union[RemoteFileUri, List[RemoteFileUri]]) -> None:
        logger.debug("Deleting item_list=%s", uri_list)

        # TODO: Split into batches when len(item_list) > 1000
        # if provided item is not iterable - make it a list
        if not (isinstance(uri_list, Iterable) and not isinstance(uri_list, StringTypes)):
            uri_list = [uri_list]

        for uri in uri_list:
            try:
                _ = await self.file_object_service_stub.Delete(
                    DeleteRequest(resource_address=self._convert_to_grpc_string(uri)),
                    metadata=await self.get_grpc_request_metadata(),
                )
                logger.debug("Done deleting via grpc, file %s!", uri)
            except aio.AioRpcError as e:
                if e.code() == StatusCode.INVALID_ARGUMENT:
                    logger.warning(f"Failure to delete {uri}: {str(e)}")
                    continue
                elif e.code() == StatusCode.NOT_FOUND:
                    logger.warning("Not found: %s", uri)
                elif e.code() == StatusCode.PERMISSION_DENIED or e.code() == StatusCode.UNAUTHENTICATED:
                    raise AccessDeniedError(f"failed to remove asset '{uri}'") from e
                else:
                    logger.error(f"Failure to delete {uri}: {str(e)}")
                    raise e from e

    async def load_thumbnail(
        self,
        uri: RemoteFileUri,
        res_map: Optional[List[Tuple[int, int]]] = None,
        mode: ThumbnailLoadMode = ThumbnailLoadMode.one,
        thumbs_loc: str = ".thumbs",
        suffixes: Optional[List[str]] = None,
        thumbnail_path_templates: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Union[List[ThumbnailItem], ThumbnailItem]:
        """
        Loads the thumbnail for the given URI.
        If storage_api_type is set to sevan, it raises an error.
        """
        if self.config.storage_api_type == KnownStorageAPITypes.sevan:
            raise NotImplementedError("Thumbnails are not yet supported for Sevan architecture")

        if self.config.thumbnail_style == ThumbnailStyle.nucleus.value:
            thumbnail_uris_list = await get_thumbnails_nucleus_style(
                storage_client=self,
                uri=uri,
                thumbnail_path_templates=thumbnail_path_templates,
                thumbs_loc=thumbs_loc,
                suffixes=suffixes,
                res_map=res_map,
            )
        else:
            thumbnail_uris_list: List[str] = []
            tags_result: TagResultField = await self.get_tags(uri)
            for tag in tags_result.tags:
                if tag.name in self.config.thumbnail_metadata_fields:
                    thumbnail_uris_list.append(tag.value)

        thumbnail_list: List[ThumbnailItem] = []

        for thumbnail_uri in thumbnail_uris_list:
            try:
                item: PathType
                exists, item = await self.check_if_exists(thumbnail_uri)
                if exists:
                    if mode == ThumbnailLoadMode.one:
                        return ThumbnailItem(
                            data=await asyncio.wait_for(
                                self.download_file_content(thumbnail_uri),
                                timeout=timeout,
                            ),
                            uri=thumbnail_uri,
                            etag=item.hash_value,
                        )
                    elif mode == ThumbnailLoadMode.all:
                        thumbnail_list.append(
                            ThumbnailItem(
                                data=await asyncio.wait_for(
                                    self.download_file_content(thumbnail_uri),
                                    timeout=timeout,
                                ),
                                uri=thumbnail_uri,
                                etag=item.hash_value,
                            )
                        )
                    else:
                        raise ValueError(f"thumbnail mode is incorrectly set: {mode}")
            except FileNotFoundError:
                logger.debug("Thumbnail thumbnail_uri=%s not found", thumbnail_uri)
        if len(thumbnail_list) == 0:
            # if no file found
            logger.debug("Thumbnail is missing for asset uri=%s", uri)
            raise FileNotFoundError(f"Thumbnail is missing for asset {uri=}")

        return thumbnail_list

    # ------------------------------------------------------------------------------------------------
    # Below there are methods that are not implemented for the Storage API client and are kept for compatibility with the StorageClient interface
    # ------------------------------------------------------------------------------------------------

    async def add_tags(
        self,
        paths: List[Union[RemoteFilePath, RemoteFileUri]],
        tags: Union[List[TagName], Dict[TagName, TagValue]],
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
        tag_action: TagAction = TagAction.add,
    ) -> None:
        raise NotImplementedError

    @staticmethod
    def _get_tag_field_from_metadata_response(
        tag_name: str,
        tag_value: Optional[struct_pb2.Value] = None,
        tag_namespace: Optional[str] = None,
    ) -> List[TagField]:
        if tag_value is None:
            return [TagField(name=tag_name, value=None, tag_namespace=tag_namespace)]
        elif tag_value.string_value is not None and tag_value.string_value != "":
            return [
                TagField(
                    name=tag_name,
                    value=tag_value.string_value,
                    tag_namespace=tag_namespace,
                )
            ]
        elif tag_value.list_value is not None and len(tag_value.list_value.values) > 0:
            tags: List[TagField] = []
            for item in tag_value.list_value.values:
                tags.extend(
                    StorageAPIStorageClient._get_tag_field_from_metadata_response(
                        tag_name=tag_name, tag_value=item, tag_namespace=tag_namespace
                    )
                )
            return tags
        elif tag_value.struct_value is not None and len(tag_value.struct_value.fields) > 0:
            tags: List[TagField] = []
            for key, item in tag_value.struct_value.fields.items():
                tags.extend(
                    StorageAPIStorageClient._get_tag_field_from_metadata_response(
                        tag_name=key, tag_value=item, tag_namespace=tag_namespace
                    )
                )
                tags.extend(
                    StorageAPIStorageClient._get_tag_field_from_metadata_response(
                        tag_name=f"{tag_name}.{key}",
                        tag_value=item,
                        tag_namespace=tag_namespace,
                    )
                )
            return tags

        logger.warning(f"Unsupported tag value: {tag_value}")
        return [TagField(name=tag_name, value=None, tag_namespace=tag_namespace)]

    async def get_tags(self, path: Union[RemoteFilePath, RemoteFileUri]) -> TagResultField:
        metadata: GetMetadataResponse = await self.get_metadata(uri=path)
        tags: List[TagField] = []
        for key, value in metadata.user_metadata.items():
            _tags = self._get_tag_field_from_metadata_response(tag_name=key, tag_value=value.value)
            tags.extend(_tags)

        return TagResultField(tags=tags, uri=path)

    async def read_tags_all_paths(
        self,
        paths: List[Union[RemoteFilePath, RemoteFileUri]],
        batch_size: Optional[int] = None,
        logging_timeout: float = 10,
    ) -> List[TagResultField]:
        raise NotImplementedError

    async def read_tags_from_gen(
        self, path_generator: AsyncIterator[str], batch_size: Optional[int] = None
    ) -> AsyncIterator[List[TagResultField]]:
        raise NotImplementedError

    def filter_tags(
        self,
        input_: TagResultField,
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
    ) -> Tuple[List[TagName], List[TagValue]]:
        raise NotImplementedError

    async def clear_tags(
        self,
        paths: List[str],
        tag_type: TagType,
        target_namespace: str = "",
    ) -> None:
        raise NotImplementedError

    async def query_tagged_paths(
        self,
        namespace: str = "",
        path: str = "",
        return_paths: bool = True,
        return_tags: bool = True,
        return_values: bool = True,
        return_namespaces: bool = True,
        exclude_hidden: bool = False,
        max_results: Optional[int] = None,
    ) -> TagQueryResult:
        raise NotImplementedError

    async def tag_subscription(
        self,
        uri: str,
        subscription_ready: Optional[asyncio.Event] = None,
        connection_getter: Optional[Callable[[], StorageConnection]] = None,
    ) -> AsyncIterator[TagResultField]:
        raise NotImplementedError

    async def tag_update_probe(self, probe_uri: Optional[str] = None) -> None:
        raise NotImplementedError

    def get_file_type(self, item: PathType) -> FileTypeMapping:
        if item.uri.endswith("/"):
            return FileTypeMapping.folder
        else:
            return FileTypeMapping.asset

    def get_event_type(self, item: PathType) -> Optional[EventMapping]:
        pass

    def status_ok(self, item: PathType) -> bool:
        return True

    def assert_on_bad_status(self, item: PathType) -> None:
        pass

    async def list_and_subscribe_multiple_files(
        self,
        paths: Optional[List[str]] = None,
        delay: float = 5,
        processing_event: Optional[asyncio.Event] = None,
        uris: Optional[List[RemoteFileUri]] = None,
    ) -> AsyncIterator[PathType]:
        raise NotImplementedError

    async def get_connection(self) -> StorageConnection:
        return self.connection

    async def authenticate_connection(
        self, c: StorageConnection, token: str, timeout: Optional[float] = None
    ) -> StorageConnection:
        return self.connection

    async def connect(self) -> StorageConnection:
        return self.connection

    def connection_getter(self) -> StorageConnection:
        return self.connection

    async def update_acl(self, path_dict: Dict[str, str]) -> None:
        raise NotImplementedError

    @property
    def connection(self) -> StorageConnection:
        # For compatibility with the interface of Nucleus storage client
        return StorageConnection()

    async def copy(self, source: str, target: str) -> Tuple[bool, CopyResult]:
        raise NotImplementedError
