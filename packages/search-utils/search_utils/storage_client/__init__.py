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
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

# third party modules
from opentelemetry import trace

from ..misc_utils import str2bool

# local / proprietary modules
from .config import (
    AvailableStorageClients,
    StorageClientConfig,
    get_backend_config_class,
)
from .data import (
    CopyResult,
    DataClassGetter,
    EventMapping,
    FileTypeMapping,
    LocalFilePath,
    PathType,
    RemoteFilePath,
    RemoteFileUri,
    TagAction,
    TagName,
    TagQueryResult,
    TagResultField,
    TagType,
    TagValue,
    ThumbnailItem,
    ThumbnailLoadMode,
    VerifyBatchAccessResponse,
)

EXTENDED_TRACING = str2bool(os.getenv("EXTENDED_TRACING", "False"))

tracer = trace.get_tracer(__name__)

MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "128"))


class StorageConnection(DataClassGetter, ABC):
    conn = None
    auth = None
    timeout: float = None


class StorageClient(ABC):
    def __init__(self, config: StorageClientConfig) -> None:
        self.config = config
        self._listing_finished = asyncio.Event()

    @property
    def listing_finished(self) -> asyncio.Event:
        return self._listing_finished

    @property
    @abstractmethod
    def connection(self):
        # For compatibility with the interface of Nucleus storage client
        return None

    @abstractmethod
    async def get_connection(self) -> StorageConnection: ...

    @property
    @abstractmethod
    def connection_info(self) -> str: ...

    @property
    @abstractmethod
    def base_uri(self) -> str: ...

    @abstractmethod
    async def authenticate_connection(
        self, c: Any, token: str, timeout: Optional[float] = None
    ) -> StorageConnection: ...

    @abstractmethod
    async def connect(
        self,
    ) -> Union[StorageConnection, Dict[str, StorageConnection]]: ...

    @asynccontextmanager
    @abstractmethod
    async def connection_context(
        self,
        connection: Optional[StorageConnection],
        return_self: Optional[bool] = False,
    ) -> AsyncIterator["StorageClient"]:
        yield

    @abstractmethod
    def get_backend_from_uri(self, uri: RemoteFileUri) -> Optional["StorageClient"]: ...

    @abstractmethod
    async def close_connection(self, conn: Optional[Union[StorageConnection, Any]] = None): ...

    @abstractmethod
    def connection_getter(self) -> StorageConnection: ...

    @abstractmethod
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
        yield PathType()

    @abstractmethod
    async def list_items_and_subscribe(
        self,
        uri: Optional[
            RemoteFilePath
        ] = None,  # DEPRECATED - use `path` instead; `uri` is kept for backwards compatibility but both `uri` and `path` expect a path NOT AN URI
        path: Optional[RemoteFilePath] = None,
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
        yield PathType()

    @abstractmethod
    async def list_and_subscribe_multiple_files(
        self,
        paths: Optional[List[str]] = None,
        delay: float = 5,
        processing_event: Optional[asyncio.Event] = None,
        uris: Optional[List[RemoteFileUri]] = None,
    ) -> AsyncIterator[PathType]: ...

    @abstractmethod
    async def check_if_exists(self, uri: Union[RemoteFileUri, RemoteFilePath]) -> Tuple[bool, Optional[PathType]]: ...

    @abstractmethod
    async def get_item(self, uri: Union[RemoteFileUri, RemoteFilePath]) -> Optional[PathType]: ...

    @abstractmethod
    async def upload_items(
        self,
        item_dict: Dict[RemoteFileUri, LocalFilePath],
        overwrite_content: bool = True,
        overwrite_if_fn: Optional[Callable[[PathType], bool]] = None,
    ) -> None: ...

    @abstractmethod
    async def upload_items_content(
        self,
        item_dict: Dict[RemoteFileUri, bytes],
        overwrite_content: bool = True,
        # overwrite_if_fn: Optional[Callable] = None,
    ): ...

    @abstractmethod
    async def delete_items(self, uri_list: Union[RemoteFileUri, List[RemoteFileUri]]) -> None: ...

    @abstractmethod
    async def download_items(self, item_dict: Dict[LocalFilePath, RemoteFileUri], cap_size: float = -1) -> bool: ...

    @abstractmethod
    async def download_file_content(
        self, uri: Union[RemoteFileUri, RemoteFilePath], timeout: Optional[float] = None
    ) -> bytes: ...

    @abstractmethod
    async def copy(self, source: str, target: str) -> Tuple[bool, CopyResult]: ...

    @abstractmethod
    async def check_connection(self, ping_timeout: Optional[float]): ...

    @abstractmethod
    async def batch_verify_access(
        self,
        uri_list: List[RemoteFileUri],
        max_nucleus_requests: int = 512,
        batch_return: bool = True,
        return_meta: bool = False,
    ) -> AsyncIterator[List[VerifyBatchAccessResponse]]:
        yield

    @abstractmethod
    async def update_acl(self, path_dict: Dict[str, str]): ...

    @abstractmethod
    async def load_thumbnail(
        self,
        uri: RemoteFileUri,
        thumbs_loc: str = ".thumbs",
        res_map: Optional[List[Tuple[int, int]]] = None,
        mode: ThumbnailLoadMode = ThumbnailLoadMode.one,
        suffixes: Optional[List[str]] = None,
        thumbnail_path_templates: Optional[List[str]] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Union[List[ThumbnailItem], ThumbnailItem]: ...

    @abstractmethod
    def get_path_from_uri(self, uri: RemoteFileUri) -> RemoteFilePath: ...

    @abstractmethod
    def get_uri_from_path(self, path: RemoteFilePath) -> RemoteFileUri: ...

    @abstractmethod
    def is_supported_uri(self, uri: str) -> bool: ...

    @abstractmethod
    def is_valid_uri(self, uri: str) -> bool: ...

    @abstractmethod
    def get_file_type(self, item: PathType) -> FileTypeMapping: ...

    @abstractmethod
    def get_event_type(self, item: PathType) -> Optional[EventMapping]: ...

    @abstractmethod
    def status_ok(self, item: PathType) -> bool: ...

    @abstractmethod
    def assert_on_bad_status(self, item: PathType): ...

    @asynccontextmanager
    async def connection_context_with_tagging(
        self,
        connection: Optional[StorageConnection] = None,
        return_self: Optional[bool] = False,
    ) -> AsyncIterator["StorageClient"]:
        async with self.connection_context(connection=connection, return_self=return_self) as client:
            yield client

    @abstractmethod
    async def add_tags(
        self,
        paths: List[Union[RemoteFilePath, RemoteFileUri]],
        tags: Union[List[TagName], Dict[TagName, TagValue]],
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
        tag_action: TagAction = TagAction.add,
    ) -> None: ...

    @abstractmethod
    async def get_tags(self, path: Union[RemoteFilePath, RemoteFileUri]) -> TagResultField: ...

    @abstractmethod
    async def read_tags_all_paths(
        self,
        paths: List[Union[RemoteFilePath, RemoteFileUri]],
        batch_size: Optional[int] = None,
        logging_timeout: float = 10,
    ) -> List[TagResultField]: ...

    @abstractmethod
    async def read_tags_from_gen(
        self,
        path_generator: AsyncIterator[str],
        batch_size: Optional[int] = None,
    ) -> AsyncIterator[List[TagResultField]]: ...

    @abstractmethod
    def filter_tags(
        self,
        input_: TagResultField,
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
    ) -> Tuple[List[TagName], List[TagValue]]: ...

    @abstractmethod
    async def clear_tags(
        self,
        paths: List[str],
        tag_type: TagType,
        target_namespace: str = "",
    ) -> None: ...

    @abstractmethod
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
    ) -> TagQueryResult: ...

    @abstractmethod
    async def tag_subscription(
        self,
        uri: str,
        subscription_ready: Optional[asyncio.Event] = None,
        connection_getter: Optional[Callable] = None,
    ) -> AsyncIterator[TagResultField]: ...

    @abstractmethod
    async def tag_update_probe(self, probe_uri: Optional[str] = None) -> None: ...


def get_client(
    client_type: AvailableStorageClients,
    config: Optional[StorageClientConfig] = None,
) -> StorageClient:
    # get default config
    if config is None:
        config = get_backend_config_class(client_type)()

    # depending on the client type - retrieve the appropriate client.
    if client_type == AvailableStorageClients.nucleus:
        from .nucleus.client import NucleusStorageClient

        return NucleusStorageClient(config=config)
    elif client_type == AvailableStorageClients.s3:
        from .s3.client import S3StorageClient

        return S3StorageClient(config=config)
    elif client_type == AvailableStorageClients.storage_api:
        from .storage_api.client import StorageAPIStorageClient

        return StorageAPIStorageClient(config=config)
    else:
        raise NotImplementedError(f"Storage of type {client_type} is not supported at the moment")


class StorageClientAuthenticationError(ConnectionError):
    def __init__(self, *args, reason: str = "", **kwargs):
        self.reason = reason
        super().__init__(*args, **kwargs)
