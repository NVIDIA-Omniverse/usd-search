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
from collections import defaultdict
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
    ListTopLevelAddressesRequest,
    ListTopLevelAddressesResponse,
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
        # Namespace roots served by this Storage API, resolved via ListTopLevelAddresses (with a base_uri
        # fallback) on first use and re-read every config.top_level_addresses_ttl seconds when that is set.
        # See resolve_root_addresses() / refresh_root_addresses().
        self._root_addresses: Optional[List[str]] = None
        self._root_addresses_resolved_at: Optional[float] = None
        self._root_addresses_lock = asyncio.Lock()
        # consecutive refreshes each currently-known root has been missing from ListTopLevelAddresses
        self._root_addresses_misses: Dict[str, int] = {}
        self.events_queue: Optional[asyncio.Queue] = None
        self.subscription_task: Optional[asyncio.Task] = None
        self._openid_token: Optional[Dict[str, str]] = None
        self._token_refresh_time: Optional[float] = None
        self._file_token: Optional[str] = None
        self._file_token_refresh_time: Optional[float] = None
        self._subscription_reconnect_token: Optional[str] = None
        self._channel: Optional[aio.Channel] = None
        self._channel_users = 0
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
    def telemetry_host(self) -> Optional[str]:
        """Falls back to ``grpc_endpoint`` when ``base_uri`` is unset (discovery mode).

        ``base_uri`` is ``None`` there by design -- it doubles as the sentinel that keeps
        path resolution and root discovery in multi-bucket mode (see ``get_path_from_uri`` /
        ``resolve_root_addresses``) -- so telemetry needs its own fallback rather than
        changing what ``base_uri`` means.
        """
        return self.config.base_uri or self.config.grpc_endpoint

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
        # get_path_from_uri / get_uri_from_path are inverses anchored on base_uri. Multi-root
        # awareness deliberately lives only in is_supported_uri (and the subscription filters) —
        # a bare relative path cannot be re-anchored to the right bucket, so round-tripping a
        # non-base_uri URI through here would corrupt it.
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
        roots = self.root_addresses
        if not roots:
            # no roots known (base_uri unset and discovery not run) -> accept any full URI
            return True
        # Match on a root boundary (the root itself or a child under root + "/") rather than a bare
        # string prefix, so a root of "s3://bucket" does not also accept "s3://bucketmeta/..." URIs.
        return any(root and (uri == root.rstrip("/") or uri.startswith(root.rstrip("/") + "/")) for root in roots)

    async def _close_subscription_generator(self) -> None:
        """Cancel the active subscription stream without ever blocking forever.

        A gRPC stream that terminated with an error (e.g. a wrong notification endpoint returning
        UNIMPLEMENTED/404) is already ``done()`` and can never become ``cancelled()``. The previous
        ``while not cancelled()`` wait therefore spun indefinitely inside the context manager's
        ``finally``, swallowing the underlying error and turning a hard failure into a hang. Waiting on
        ``done()`` with a bounded timeout lets the real exception propagate so the caller fails loudly.
        """
        gen = self._subscription_generator
        self._subscription_generator = None
        if gen is None or gen.done():
            return
        gen.cancel()
        for _ in range(50):  # ~5s ceiling — never block forever
            if gen.done():
                break
            await asyncio.sleep(0.1)

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
                    await self._close_subscription_generator()
        else:
            async with aio.insecure_channel(self.notification_service_grpc_endpoint) as channel:
                self._notification_service_channel = channel
                self._event_consumer_service_stub = EventConsumerServiceStub(channel)
                try:
                    yield self._event_consumer_service_stub
                finally:
                    self._notification_service_channel = None
                    self._event_consumer_service_stub = None
                    await self._close_subscription_generator()

    @asynccontextmanager
    async def connection_context(self, *_, **__) -> AsyncIterator["StorageAPIStorageClient"]:
        """Create asynchronous connection context.

        Contexts entered while a channel is open re-use it; the channel is closed only when the last of
        them exits, so a short-lived context cannot close a channel a longer-lived one is still using.

        Yields:
            Iterator[AsyncIterator["StorageAPIStorageClient"]]: resulting client
        """
        if self._channel is None:
            if self.config.ssl:
                self._channel = aio.secure_channel(self.config.grpc_endpoint, ssl_channel_credentials())
            else:
                self._channel = aio.insecure_channel(self.config.grpc_endpoint)
            self._file_object_service_stub = FileObjectServiceStub(self._channel)
            self._capabilities_stub = CapabilitiesServiceStub(self._channel)
        self._channel_users += 1
        try:
            yield self
        finally:
            self._channel_users -= 1
            if self._channel_users == 0:
                channel = self._channel
                self._channel = None
                self._file_object_service_stub = None
                self._capabilities_stub = None
                self._file_folder_service_stub = None
                self._metadata_service_stub = None
                await channel.close()

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

    def _read_token_file(self) -> str:
        try:
            with open(self.config.token_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError as exc:
            # On a failed re-read, prefer the last-known-good token over an auth outage.
            if self._file_token is not None:
                logger.warning(
                    "Failed to re-read Storage API token file %s: %s; keeping cached token",
                    self.config.token_file,
                    exc,
                )
                return self._file_token
            raise

    async def _get_token(self) -> str:
        if self.config.token is not None:
            return self.config.token
        if self.config.token_file is not None:
            if self._file_token_refresh_time is None or time.time() > self._file_token_refresh_time:
                self._file_token = self._read_token_file()
                self._file_token_refresh_time = time.time() + self.config.token_refresh_interval
            return self._file_token
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

    @staticmethod
    def _normalize_address_for_matching(address: str) -> str:
        """Strip a URI scheme and trailing slash so allowlist entries match regardless of either."""
        return address.split("://", 1)[-1].rstrip("/")

    def _apply_allowed_top_level_addresses(self, addresses: List[str]) -> List[str]:
        """Filter discovered addresses down to ``config.allowed_top_level_addresses``, if configured."""
        allowed = self.config.allowed_top_level_addresses
        if not allowed:
            return addresses

        normalized_allowed = {self._normalize_address_for_matching(a) for a in allowed}
        filtered = [a for a in addresses if self._normalize_address_for_matching(a) in normalized_allowed]

        normalized_discovered = {self._normalize_address_for_matching(a) for a in addresses}
        unmatched = [a for a in allowed if self._normalize_address_for_matching(a) not in normalized_discovered]
        if unmatched:
            logger.warning(
                "allowed_top_level_addresses entries not found among discovered Storage API addresses "
                "(ignored): %s. Discovered: %s",
                unmatched,
                addresses,
            )

        if not filtered:
            raise ValueError(
                f"allowed_top_level_addresses={allowed!r} matched none of the discovered Storage API "
                f"addresses {addresses!r}; check for typos or a bucket the server no longer serves."
            )

        return filtered

    async def list_top_level_addresses(self) -> List[str]:
        """Return the top level resource addresses (namespace roots / buckets) served by the server.

        Thin wrapper over the Storage API ``CapabilitiesService.ListTopLevelAddresses`` RPC, restricted to
        ``config.allowed_top_level_addresses`` when that is non-empty. A single Storage API deployment may
        expose several buckets; this discovers them instead of requiring a manually configured ``base_uri``.
        Callers that need the fallback behaviour should use :meth:`resolve_root_addresses` instead of
        calling this directly.
        """
        response: ListTopLevelAddressesResponse = await self.capabilities_stub.ListTopLevelAddresses(
            ListTopLevelAddressesRequest(),
            metadata=await self.get_grpc_request_metadata(),
            timeout=self.config.top_level_addresses_timeout,
        )
        addresses = [self._convert_from_grpc_string(entry.top_level_address) for entry in response.items]
        return self._apply_allowed_top_level_addresses(addresses)

    async def resolve_root_addresses(self) -> List[str]:
        """Resolve the set of namespace roots to operate over.

        An explicitly configured ``base_uri`` is authoritative: it scopes the client to that single
        namespace and discovery is skipped (``allowed_top_level_addresses`` is then irrelevant). Only when
        ``base_uri`` is unset do we discover the served buckets via ``ListTopLevelAddresses`` (a deployment
        may serve several), already filtered by ``allowed_top_level_addresses`` if set.

        When ``base_uri`` is unset and discovery is unavailable (server does not implement the call) or
        returns nothing, an empty set is returned (logged as a WARNING) rather than raising: operations
        that receive explicit URIs/paths still work, and helpers that genuinely need a root degrade
        gracefully (e.g. subscriptions fall back to the requested path).
        """
        if self.config.base_uri is not None:
            if self.config.allowed_top_level_addresses:
                logger.warning(
                    "allowed_top_level_addresses=%s is ignored because base_uri=%r already scopes the "
                    "client to a single namespace.",
                    self.config.allowed_top_level_addresses,
                    self.config.base_uri,
                )
            return [self.config.base_uri]

        try:
            addresses = await self.list_top_level_addresses()
        except aio.AioRpcError as e:
            logger.warning(
                "Storage API ListTopLevelAddresses unavailable (status=%s) and no base_uri is configured; "
                "namespace roots left unresolved. Details: %s",
                e.code(),
                e,
            )
            return []

        if not addresses:
            logger.warning(
                "Storage API ListTopLevelAddresses returned no addresses and no base_uri is configured; "
                "namespace roots left unresolved."
            )
            return []

        logger.info("Discovered %d Storage API top level address(es): %s", len(addresses), addresses)
        return addresses

    @property
    def _root_addresses_refreshable(self) -> bool:
        """Whether resolved roots are re-read at all (discovery in use and a TTL configured)."""
        return self.config.base_uri is None and self.config.top_level_addresses_ttl > 0

    def _root_addresses_stale(self) -> bool:
        if self._root_addresses is None:
            return True
        if not self._root_addresses_refreshable or self._root_addresses_resolved_at is None:
            return False
        return time.monotonic() - self._root_addresses_resolved_at >= self.config.top_level_addresses_ttl

    async def refresh_root_addresses(self, force: bool = False) -> None:
        """Resolve the namespace roots on first use, then re-read them once they are older than the TTL.

        ``force`` re-reads them regardless of age (still only when ``top_level_addresses_ttl`` is set and
        ``base_uri`` is not). Until a non-empty list has been resolved, a resolution simply replaces the
        list (as the initial one always did). After that, a refresh never makes it worse: a failed or
        empty answer keeps the last good list, new roots are added at once, and a missing root is
        dropped only after ``top_level_addresses_drop_after_misses`` consecutive refreshes without it.
        Concurrent callers share one ListTopLevelAddresses call.
        """
        if not force and not self._root_addresses_stale():
            return
        seen_resolved_at = self._root_addresses_resolved_at
        async with self._root_addresses_lock:
            if self._root_addresses is not None:
                if self._root_addresses_resolved_at != seen_resolved_at:
                    return  # another caller refreshed while we waited for the lock
                if not self._root_addresses_refreshable:
                    return
                if not force and not self._root_addresses_stale():
                    return

            if self._root_addresses is None:
                # first resolution: a misconfigured allowlist still fails fast at startup
                self._root_addresses = await self.resolve_root_addresses()
            elif not self._root_addresses:
                # retrying an empty initial resolution from a crawler loop: never raise into it
                try:
                    self._root_addresses = await self.resolve_root_addresses()
                except ValueError as e:
                    logger.warning("Storage API top level address resolution rejected; still none known: %s", e)
            else:
                self._root_addresses = await self._refreshed_root_addresses(self._root_addresses)
            self._root_addresses_resolved_at = time.monotonic()

    async def _refreshed_root_addresses(self, current: List[str]) -> List[str]:
        """Merge a fresh ListTopLevelAddresses answer into ``current`` (see :meth:`refresh_root_addresses`)."""
        try:
            discovered = await self.list_top_level_addresses()
        except aio.AioRpcError as e:
            logger.warning(
                "Storage API ListTopLevelAddresses failed on refresh (status=%s); keeping the %d known top "
                "level address(es). Details: %s",
                e.code(),
                len(current),
                e,
            )
            return current
        except ValueError as e:
            logger.warning("Storage API top level address refresh rejected; keeping the known ones: %s", e)
            return current
        if not discovered:
            logger.warning(
                "Storage API ListTopLevelAddresses returned no addresses on refresh; keeping the %d known "
                "top level address(es).",
                len(current),
            )
            return current

        drop_after = self.config.top_level_addresses_drop_after_misses
        discovered_set = set(discovered)
        kept: List[str] = []
        dropped: List[str] = []
        for root in current:
            if root in discovered_set:
                self._root_addresses_misses.pop(root, None)
                kept.append(root)
                continue
            misses = self._root_addresses_misses.get(root, 0) + 1
            if misses >= drop_after:
                self._root_addresses_misses.pop(root, None)
                dropped.append(root)
            else:
                self._root_addresses_misses[root] = misses
                kept.append(root)
                logger.info(
                    "Storage API top level address %s missing from ListTopLevelAddresses (%d/%d); keeping it "
                    "for now.",
                    root,
                    misses,
                    drop_after,
                )
        current_set = set(current)
        added = [a for a in discovered if a not in current_set]
        if added or dropped:
            logger.info("Storage API top level addresses changed: +%s -%s", added, dropped)
        return kept + added

    @property
    def supported_uris_refreshable(self) -> bool:
        return self._root_addresses_refreshable

    async def refresh_supported_uris(self) -> None:
        """Re-read the roots :meth:`is_supported_uri` matches against once they are older than the TTL.

        No-op unless ``top_level_addresses_ttl`` is set (and ``base_uri`` is not), so a process that has
        not resolved its roots keeps today's behaviour without the opt-in.
        """
        if self._root_addresses_refreshable:
            await self.refresh_root_addresses()

    @property
    def root_addresses(self) -> List[str]:
        """The resolved namespace roots. Defaults to ``[base_uri]`` (when set) until discovery has run."""
        if self._root_addresses is not None:
            return self._root_addresses
        return [self.config.base_uri] if self.config.base_uri is not None else []

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
            elif e.code() == StatusCode.PERMISSION_DENIED:
                logger.info("Access to %s denied: %s", uri, e)
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
        await self.refresh_root_addresses()

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
        # Each top-level listing gets its own max_items budget (matching the S3 backend's per-path
        # limit): one budget per explicitly requested path, or one per discovered root when no path is
        # given. Subfolders inherit their top-level ancestor's budget. Entries are
        # (iterator, uri, budget_key); subfolders are appended during traversal.
        iterators: List[Tuple[AsyncIterator[ListResponse], Optional[RemoteFileUri], str]] = []
        item_counts: Dict[str, int] = defaultdict(int)

        if len(uri_list) == 0:
            # No explicit URIs: enumerate every discovered namespace root (bucket), each with its own budget.
            grpc_metadata = await self.get_grpc_request_metadata()
            iterators = [
                (
                    self.file_folder_service_stub.ListStat(
                        ListStatRequest(folder=FolderAddress(uri=f"{root.rstrip('/')}/")),
                        metadata=grpc_metadata,
                    ),
                    None,
                    root,
                )
                for root in self.root_addresses
                if root
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
                    item_counts[uri] += 1
                    if processing_fn is None:
                        yield item
                    else:
                        yield await run_callable(processing_fn, item)
                else:
                    iterators.append((self.list_stat_wrapper(uri), uri, uri))

        # prepare paths
        list_stat_response: ListStatResponse
        index = 0
        while index < len(iterators):
            iterator, uri, budget_key = iterators[index]
            index += 1

            # this top-level listing has already reached its max_items budget
            if max_items is not None and item_counts[budget_key] >= max_items:
                continue

            async for list_stat_response in iterator:
                subfolder_addresses: FolderAddress
                for subfolder_addresses in getattr(list_stat_response, "subfolder_addresses", []):

                    if match_patterns(subfolder_addresses.uri, patterns=ignore_patterns):
                        continue

                    iterators.append(
                        (
                            self.list_stat_wrapper(subfolder_addresses.uri),
                            subfolder_addresses.uri,
                            budget_key,
                        )
                    )

                item: ListItem
                for item in getattr(list_stat_response, "entries", []):

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

                    item_counts[budget_key] += 1
                    if max_items is not None and item_counts[budget_key] >= max_items:
                        break

                if max_items is not None and item_counts[budget_key] >= max_items:
                    break

    async def _list_items_using_enumerate(
        self,
        uri_list: List[RemoteFileUri],
        ignore_patterns: List[str],
        processing_fn: Optional[Callable[[PathType], Union[PathType, Awaitable[PathType]]]] = None,
        max_items: Optional[int] = None,
    ) -> AsyncIterator[PathType]:
        # Each enumeration gets its own max_items budget (matching _list_items_using_list and the S3
        # backend's per-path limit): one budget per explicitly requested URI, or one per discovered root
        # when no URI is given. Enumerate scopes to its resource_address, so each iterator covers exactly
        # one root/URI. Entries are (iterator, uri, budget_key).
        iterators: List[Tuple[AsyncIterator[EnumerateResponse], Optional[RemoteFileUri], str]] = []
        if len(uri_list) == 0:
            # No explicit URIs: enumerate every discovered namespace root (bucket), each with its own budget.
            iterators = [(self.list_enumerate_wrapper(root), None, root) for root in self.root_addresses if root]
        else:
            for uri in uri_list:

                # check if the items is the actual key in the storage API - process it directly.
                # if the uri is not a key, but rather a prefix (folder) - enumerate the items in the folder.
                if match_patterns(uri, patterns=ignore_patterns):
                    continue

                exists, item = await self.check_if_exists(uri)
                if exists and item.type == FileTypeMapping.asset:
                    # A direct asset hit yields a single item, well within any per-URI budget.
                    if processing_fn is None:
                        yield item
                    else:
                        yield await run_callable(processing_fn, item)
                else:
                    iterators.append((self.list_enumerate_wrapper(uri), uri, uri))

        # prepare paths
        list_queue: asyncio.Queue[PathType] = asyncio.Queue(maxsize=self.config.list_queue_limit)
        queue_population_finished = asyncio.Event()

        async def populate_list_queue() -> None:
            item_counts: Dict[str, int] = defaultdict(int)
            for iterator, _, budget_key in iterators:
                if max_items is not None and item_counts[budget_key] >= max_items:
                    continue
                async for enumerate_response in iterator:
                    for item in enumerate_response.items:
                        if match_patterns(item.resource_address, patterns=ignore_patterns):
                            continue
                        await list_queue.put(item)
                        item_counts[budget_key] += 1
                        if max_items is not None and item_counts[budget_key] >= max_items:
                            break
                    if max_items is not None and item_counts[budget_key] >= max_items:
                        break

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

    def _subscription_roots(self) -> List[str]:
        """Namespace roots to scope a subscription to.

        An explicitly configured ``base_uri`` is the subscription scope: it is the namespace the
        operator chose to watch, and the Storage API's notification ``resource_id``s follow it, so we
        must filter on that exact prefix (not on whatever ``ListTopLevelAddresses`` reports, which may
        use a different string form). Only when ``base_uri`` is unset do we fan out across every
        discovered bucket.
        """
        if self.config.base_uri is not None:
            return [self.config.base_uri]
        return [root for root in self.root_addresses if root]

    def _subscription_resource_ids(self, path: Optional[str] = None) -> List[str]:
        """Build one folder resource-id per subscription root for a sub-``path``.

        A deployment can serve multiple buckets, so a relative ``path`` cannot be anchored to one URL.
        We anchor it under every subscription root (see :meth:`_subscription_roots`) and let the server
        OR the resulting filters together. Storage event subscriptions only accept **folder** values, so
        every resource_id ends with ``/``.

        When no root is known (base_uri unset and discovery unavailable) we fall back to the requested
        ``path`` anchored via :meth:`get_uri_from_path` — the pre-discovery behaviour, which lets a
        client that watches an explicit path keep working against a server without ``ListTopLevelAddresses``.
        Returns ``[]`` only when neither a root nor a path is available.
        """
        roots = [root.rstrip("/") for root in self._subscription_roots() if root]
        if not roots:
            if path is None or path in ("", "/"):
                return []
            anchored = self.get_uri_from_path(path)
            return [anchored if anchored.endswith("/") else f"{anchored}/"]
        if path is None or path in ("", "/"):
            return [f"{root}/" for root in roots]
        return [f"{root}/{path.strip('/')}/" for root in roots]

    def prepare_subscription_request(
        self,
        path: Optional[str] = None,
        filter_type: ResourceFilter.FilterType = ResourceFilter.FilterType.FILTER_TYPE_STARTS_WITH_GREEDY,
        storage_events: List[str] = [STORAGE_CREATED],
    ) -> Iterator[ConsumeNonDurableEventsRequest]:
        """
        Prepare a request to subscribe to notifications.

        One resource filter is emitted per served backend root (filters within a FilterGroup are OR'd
        by the server). The Storage API requires at least one folder resource filter for storage events,
        so a subscription cannot be built when no namespace root is known.

        On reconnect (``reconnect_token`` set) the server reuses the existing queue's filters, and per
        the proto ``filter_groups`` must be omitted unless we are intentionally changing them (which
        also requires ``previous_filter_groups``). We never change filters mid-stream, so filters are
        only sent on the initial connect.
        """
        request = ConsumeNonDurableEventsRequest(reconnect_token=self._subscription_reconnect_token)

        if not self._subscription_reconnect_token:
            resource_ids = self._subscription_resource_ids(path)
            if not resource_ids:
                raise ValueError(
                    "Cannot subscribe to Storage API events: no namespace root is known. Set base_uri "
                    "(STORAGE_API_BASE_URI) or ensure ListTopLevelAddresses is available — storage event "
                    "subscriptions require at least one folder resource_id."
                )
            storage_resource_filters = [
                ResourceFilter(filter_type=filter_type, resource_id=resource_id) for resource_id in resource_ids
            ]

            for event_type in storage_events:
                fg = FilterGroup(event_type=event_type)
                fg.filters.extend(storage_resource_filters)
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

        # Client-side safety net: the server already filters by these prefixes, but if it emits an
        # event outside the served roots / sub-path we drop it here before a Stat round-trip. Empty
        # means no roots are known -> accept everything (matches the empty greedy server filter).
        allowed_prefixes = self._subscription_resource_ids(path)

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
                                        if allowed_prefixes and not any(
                                            field_value.string_value.startswith(prefix) for prefix in allowed_prefixes
                                        ):
                                            logger.debug(
                                                "Event outside subscribed roots, skipping: %s",
                                                field_value.string_value,
                                            )
                                            continue
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
                # Pass the relative sub-path; subscribe_to_notifications anchors it under every served
                # backend root (multiple buckets are supported), so no single URL is assumed here.
                self.subscribe_to_notifications(
                    self.events_queue,
                    path=path,
                )
            )

        # update path to be a full URI
        if ignore_patterns is None:
            ignore_patterns = []
        first_pass = True
        while True:
            if not first_pass:
                # make every re-scan cover the roots served now, not those served at startup
                await self.refresh_root_addresses(force=True)
            first_pass = False
            if self.config.full_listing_enabled:
                logger.info(
                    "Scanning Storage API '%s' for path=%s...",
                    self.config.grpc_endpoint,
                    path,
                )
                n_items = 0
                async for item in self.list_items(
                    uri_list=(
                        [RemoteFileUri(self.get_uri_from_path(path))] if path is not None and path != "/" else []
                    ),
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
                            event = self.events_queue.get_nowait()
                            # the subscription task reports failures by enqueuing the exception; surface it
                            # as a raise rather than yielding it as if it were a PathType item
                            if isinstance(event, BaseException):
                                raise event
                            yield [event]

                    n_items += 1
                    logger.debug("Found item %s", item.uri)
                    yield [item]

                logger.info(
                    "Scan of Storage API backend '%s' for path=%s finished, found %s items",
                    self.config.grpc_endpoint,
                    path,
                    n_items,
                )
            else:
                logger.info("Storage API '%s' full listing disabled, indexing updates only", self.config.grpc_endpoint)

            if self.config.notification_subscription_enabled:
                while True:
                    if self.subscription_task is not None and self.subscription_task.done():
                        raise self.subscription_task.exception()
                    if self.events_queue is not None:
                        event = await self.events_queue.get()
                        # surface an enqueued subscription failure as a raise, not a bogus item
                        if isinstance(event, BaseException):
                            raise event
                        yield [event]

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
            metadata=await self.get_grpc_request_metadata(),
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
