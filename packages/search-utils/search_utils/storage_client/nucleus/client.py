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
import warnings

# standard modules
from collections.abc import Iterable
from contextlib import asynccontextmanager
from typing import (
    Any,
    AsyncContextManager,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)
from xml.dom.minicompat import StringTypes

from idl.types.initialization import ValidationTypeError
from omni.tagging.client._generated.data import GetTagsResult, StatusCode

from .. import MAX_CONCURRENT_REQUESTS, RemoteFilePath, StorageClient
from ..data import (
    EventMapping,
    FileTypeMapping,
    LocalFilePath,
    RemoteFileUri,
    TagAction,
    TagField,
    TagName,
    TagQueryResult,
    TagResultField,
    TagType,
    TagValue,
    ThumbnailItem,
    ThumbnailLoadMode,
    VerifyBatchAccessResponse,
)
from ..exceptions import AccessDeniedError, TokenExpired
from ..utils import get_thumbnails_nucleus_style, run_callable

# local / proprietary modules
from . import READ_BATCH_SIZE
from .auth import (
    NucleusAuth,
    NucleusAuthEnv,
    NucleusAuthResponse,
    authenticate_connection,
)
from .config import NucleusStorageConfig
from .connection import (
    NucleusConnection,
    batch_verify_access,
    check_connection,
    check_if_exists,
    close_connection,
    delete_file,
    download_file,
    download_file_content,
    get_nucleus_connection,
    get_path_from_uri,
    get_single_item,
    get_uri_from_path_without_port,
    omni_connection_wrapper,
    omni_copy,
    omni_list_and_subscribe,
    omni_list_and_subscribe_multiple,
    recursive_list_gen,
    update_acl,
    upload_file,
    upload_file_content,
)
from .utils import assert_on_bad_status, get_event_mapping, status_ok

logger = logging.getLogger(__name__)

try:
    from .tag_utils import (
        TaggingClientContextAsync,
        TaggingClientSubContextAsync,
        assert_status_ok_tagging,
        result_wrapper,
    )
except ModuleNotFoundError:
    logger.warning("Tagging service not available")


from omni.client import Connection, PathType, Response, StatusType


class NucleusStorageClient(StorageClient):
    def __init__(
        self,
        config: NucleusStorageConfig,
    ) -> None:
        logger.debug("Initializing Nucleus client with config %s", str(config))
        self.config = config
        self._ov_server = config.ov_server
        self._auth = config.auth
        self._timeout = config.timeout
        self._connection: Optional[NucleusConnection] = None
        self._tag_context: Optional[TaggingClientContextAsync] = None
        self._tag_sub_context: Optional[TaggingClientSubContextAsync] = None

    @property
    def connection(self):
        return self._connection

    @property
    def base_uri(self) -> str:
        return f"omniverse://{self._ov_server}"

    async def get_connection(self) -> Connection:
        return await get_nucleus_connection(self._ov_server)

    @property
    def connection_info(self) -> str:
        return str(self.connection.conn)

    def get_backend_from_uri(self, uri: RemoteFileUri) -> Optional["NucleusStorageClient"]:
        return self

    async def authenticate_connection(
        self,
        c: Connection,
        token: str,
    ) -> NucleusConnection:
        auth: Union[NucleusAuthEnv, NucleusAuth] = await authenticate_connection(
            c,
            token,
            timeout=self._timeout,
        )
        return NucleusConnection(
            conn=c,
            auth=NucleusAuthResponse(auth=auth, auth_token=token),
            timeout=self._timeout,
        )

    def _transform_nucleus_results_list(self, items: List[PathType]) -> List[PathType]:
        return [self._transform_nucleus_result(result) for result in items]

    def _transform_nucleus_result(self, item: PathType) -> PathType:
        # Convert Nucleus path to a full URI
        # (e.g. /Projects/DeepSearch/ -> omniverse://omniverse://rc-r15.ov.nvidia.com/Projects/DeepSearch/ )
        item.uri = self.get_uri_from_path_without_port(item.uri) if item.uri is not None else item.uri
        return item

    async def connect(self) -> NucleusConnection:
        ow = omni_connection_wrapper(ov_server=self._ov_server, auth=self._auth, timeout=self._timeout)
        self._connection = await ow.init_connection()
        # add user agent
        if self.config.user_agent is not None:
            try:
                await self._set_user_agent(self._connection)
            except Exception as exc_info:
                logger.debug("Failed to assign user agent to connection %s", str(exc_info))
        return self.connection

    async def _set_user_agent(self, connection: NucleusConnection) -> Response:
        """Set User agent to be able to distinguish, which application is using Nucleus connection.

        Args:
            connection (NucleusConnection): Nucleus connection

        Raises:
            Exception: On unknown status

        Returns:
            Response: user connection response
        """
        logger.debug("Setting User Agent to '%s'", self.config.user_agent)
        response = await connection.conn.set_user_agent(self.config.user_agent)
        if not status_ok(response):
            if response.status == StatusType.INVALID_COMMAND:
                pass
            else:
                raise Exception(f"Set User Agent failed {response.status}")
        return response

    async def close_connection(self, conn: Optional[Union[NucleusConnection, Connection]] = None):
        if conn is None:
            if self.connection is not None:
                await close_connection(self.connection.conn)
        elif isinstance(conn, NucleusConnection):
            await close_connection(self.connection.conn)
        elif isinstance(conn, Connection):
            await close_connection(conn)
        else:
            raise ValueError(f"Unknown connection type: {type(conn)}")

    @asynccontextmanager
    async def connection_context(
        self,
        connection: Optional[NucleusConnection] = None,
        return_self: Optional[bool] = False,
    ) -> AsyncContextManager["NucleusStorageClient"]:
        if return_self:
            nucleus_storage_client = self
        else:
            nucleus_storage_client = NucleusStorageClient(config=self.config)

        if connection is None:
            try:
                await nucleus_storage_client.connect()
                yield nucleus_storage_client
            except ValidationTypeError as exc_info:
                raise ConnectionError(exc_info) from exc_info
            finally:
                await nucleus_storage_client.close_connection()
        else:
            nucleus_storage_client._connection = connection
            yield nucleus_storage_client

    def connection_getter(self) -> NucleusConnection:
        return self.connection

    async def list_items(
        self,
        path_list: Optional[List[RemoteFilePath]] = None,
        uri_list: Optional[List[RemoteFileUri]] = None,
        max_concurrent_requests: Optional[int] = MAX_CONCURRENT_REQUESTS,
        logging_timeout: Optional[float] = 10,
        listing_timeout: Optional[float] = 20,
        show_hidden: Optional[bool] = False,
        recursive: Optional[bool] = True,
        ignore_patterns: Optional[List[str]] = [".*/.thumbs/.*"],
        raise_on_error: Optional[bool] = True,
        list_type: Optional[PathType] = PathType.Asset,
        processing_fn: Optional[Union[Callable, Awaitable]] = None,
        processing_event: Optional[asyncio.Event] = None,
        max_items: Optional[int] = None,
    ) -> AsyncIterator[PathType]:
        # TODO: support max items functionality

        if uri_list is None and path_list is not None:
            uri_list = path_list

        if uri_list is None:
            uri_list = []

        path_list = [self.get_path_from_uri(uri) for uri in uri_list]

        async for item in recursive_list_gen(
            c=self.connection,
            path_list=path_list,
            max_concurrent_requests=max_concurrent_requests,
            logging_timeout=logging_timeout,
            listing_timeout=listing_timeout,
            show_hidden=show_hidden,
            recursive=recursive,
            ignore_patterns=ignore_patterns,
            raise_on_error=raise_on_error,
            list_type=list_type,
            processing_event=processing_event,
            skip_mounts=self.config.skip_mounts,
        ):
            if processing_fn is None:
                yield self._transform_nucleus_result(item)
            else:
                yield await run_callable(processing_fn, self._transform_nucleus_result(item))

    async def list_items_and_subscribe(
        self,
        uri: Optional[
            RemoteFilePath
        ] = None,  # DEPRECATED - use `path` instead; `uri` is kept for backwards compatibility but both `uri` and `path` expect a path NOT AN URI
        path: Optional[RemoteFilePath] = None,
        batch_size: Optional[int] = -1,
        max_concurrent_requests: Optional[int] = MAX_CONCURRENT_REQUESTS,
        logging_timeout: Optional[float] = 10,
        listing_timeout: Optional[float] = 20,
        show_hidden: Optional[bool] = False,
        ignore_patterns: Optional[List[str]] = None,
        raise_on_error: Optional[bool] = True,
        list_type: Optional[PathType] = PathType.Asset,
        recursive: Optional[bool] = True,
        processing_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[List[PathType]]:
        if ignore_patterns is None:
            ignore_patterns = []
        if uri and path is not None:
            raise ValueError("Setting both `uri` and `path` is not allowed")
        if uri is not None:
            path = uri
            warnings.warn(
                "`uri` parameter of NucleusStorageClient.list_items_and_subscribe is deprecated; use `path` instead",
                DeprecationWarning,
            )

        async for item in await omni_list_and_subscribe(
            self.connection,
            path=path,
            batch_size=batch_size,
            max_concurrent_requests=max_concurrent_requests,
            raise_on_error=raise_on_error,
            show_hidden=show_hidden,
            list_type=list_type,
            ignore_patterns=ignore_patterns,
            logging_timeout=logging_timeout,
            listing_timeout=listing_timeout,
            recursive=recursive,
            processing_event=processing_event,
            skip_mounts=self.config.skip_mounts,
        ):
            yield self._transform_nucleus_results_list(item)

    async def list_and_subscribe_multiple_files(
        self,
        paths: Optional[List[str]] = None,
        delay: float = 5,
        processing_event: Optional[asyncio.Event] = None,
        uris: Optional[List[RemoteFileUri]] = None,
    ) -> AsyncIterator[PathType]:
        if uris and paths is not None:
            raise ValueError("Setting both `uris` and `paths` is not allowed")
        if paths is not None:
            warnings.warn(
                "`paths` parameter of NucleusStorageClient.list_and_subscribe_multiple_files is deprecated; use `uris` instead",
                DeprecationWarning,
            )
        if uris is not None:
            paths = [self.get_path_from_uri(uri) for uri in uris]

        async for item in omni_list_and_subscribe_multiple(c=self.connection, paths=paths, delay=delay):
            yield self._transform_nucleus_result(item)

    async def check_if_exists(self, uri: str) -> Tuple[bool, Union[PathType, str]]:
        exists, result = await check_if_exists(self.connection, self.get_path_from_uri(uri))
        if exists:
            return exists, self._transform_nucleus_result(result)
        # TODO: Refactor to throw an exception instead of returning error string in the result
        return exists, result

    async def get_item(self, uri: str) -> Optional[PathType]:
        result = await get_single_item(self.connection, self.get_path_from_uri(uri))
        if result is not None:
            return self._transform_nucleus_result(result)
        return result

    async def delete_items(self, uri_list: Union[RemoteFileUri, List[RemoteFileUri]]) -> None:
        if isinstance(uri_list, Iterable) and not isinstance(uri_list, StringTypes):
            await delete_file(self.connection, [self.get_path_from_uri(uri) for uri in uri_list])
        else:
            await delete_file(self.connection, [self.get_path_from_uri(uri_list)])

    async def upload_items(
        self,
        item_dict: Dict[RemoteFileUri, LocalFilePath],
        overwrite_content: bool = True,
        overwrite_if_fn: callable = None,
    ) -> None:
        await asyncio.gather(
            *[
                upload_file(
                    self.connection,
                    local_file,
                    self.get_path_from_uri(omni_uri),
                    overwrite_content=overwrite_content,
                    overwrite_if_fn=overwrite_if_fn,
                )
                for omni_uri, local_file in item_dict.items()
            ]
        )

    async def upload_items_content(
        self,
        item_dict: Dict[RemoteFileUri, bytes],
        overwrite_content: bool = True,
    ) -> None:
        await asyncio.gather(
            *[
                upload_file_content(
                    self.connection,
                    content,
                    self.get_path_from_uri(omni_file),
                    overwrite_content=overwrite_content,
                )
                for omni_file, content in item_dict.items()
            ]
        )

    async def download_items(
        self,
        item_dict: Dict[LocalFilePath, RemoteFileUri],
        cap_size: float = -1,
    ):
        await asyncio.gather(
            *[
                download_file(
                    self.connection,
                    local_file,
                    self.get_path_from_uri(omni_uri),
                    cap_data=cap_size > 0,
                    cap_size=cap_size,
                )
                for local_file, omni_uri in item_dict.items()
            ]
        )

    async def download_file_content(self, uri: str, timeout: Optional[float] = None):
        data, _ = await download_file_content(self.connection, self.get_path_from_uri(uri), "", timeout=timeout)
        return data

    async def copy(self, source: str, target: str) -> Tuple[bool, Any]:
        return await omni_copy(
            c=self.connection,
            source=self.get_path_from_uri(source),
            target=self.get_path_from_uri(target),
        )

    async def check_connection(self, ping_timeout: Optional[float] = 20):
        return await check_connection(self.connection, ping_timeout=ping_timeout)

    async def batch_verify_access(
        self,
        uri_list: List[RemoteFileUri],
        max_nucleus_requests: Optional[int] = 512,
        batch_return: bool = True,
        return_meta: bool = False,
    ) -> AsyncIterator[List[VerifyBatchAccessResponse]]:
        async for results_batch in batch_verify_access(
            path_list=[self.get_path_from_uri(uri) for uri in uri_list],
            conn=self.connection,
            max_nucleus_requests=max_nucleus_requests,
            batch_return=batch_return,
            return_meta=return_meta,
        ):
            for result in results_batch:
                result.uri = self.get_uri_from_path(result.path)
            yield results_batch

    async def update_acl(
        self,
        path_dict: Dict[str, str],
    ):
        src_paths = []
        tgt_paths = []

        for k, v in path_dict.items():
            src_paths.append(k)
            tgt_paths.append(v)

        return await update_acl(conn=self.connection, src_paths=src_paths, tgt_paths=tgt_paths)

    async def load_thumbnail(
        self,
        uri: RemoteFileUri,
        mode: ThumbnailLoadMode = ThumbnailLoadMode.one,
        thumbs_loc: str = ".thumbs",
        res_map: Optional[List[Tuple[int, int]]] = None,
        suffixes: Optional[List[str]] = None,
        thumbnail_path_templates: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Union[List[ThumbnailItem], ThumbnailItem]:

        # get thumbnails in nucleus style
        thumbnail_uris_list = await get_thumbnails_nucleus_style(
            storage_client=self,
            uri=uri,
            thumbnail_path_templates=thumbnail_path_templates,
            thumbs_loc=thumbs_loc,
            suffixes=suffixes,
            res_map=res_map,
        )
        exist_check = await asyncio.gather(*[self.check_if_exists(f) for f in thumbnail_uris_list])

        if mode == ThumbnailLoadMode.one:
            for it, f in enumerate(thumbnail_uris_list):
                if exist_check[it][0]:
                    data, etag = await asyncio.wait_for(
                        download_file_content(self.connection, self.get_path_from_uri(f)),
                        timeout=timeout,
                    )
                    return ThumbnailItem(data=data, uri=f, etag=etag)
            # if no file found
            raise FileNotFoundError(f"Thumbnail is missing for '{uri}'")
        elif mode == ThumbnailLoadMode.all:
            thumbnails = await asyncio.gather(
                *[
                    asyncio.wait_for(
                        download_file_content(self.connection, self.get_path_from_uri(f)),
                        timeout=timeout,
                    )
                    for it, f in enumerate(thumbnail_uris_list)
                    if exist_check[it][0]
                ]
            )
            thumbnail_list = [
                ThumbnailItem(data=thumbnail[0], uri=uri, etag=thumbnail[1])
                for thumbnail, uri in zip(thumbnails, thumbnail_uris_list)
            ]
            if len(thumbnail_list) == 0:
                raise FileNotFoundError(f"Thumbnail(s) is missing for '{uri}'")

            return thumbnail_list

    @staticmethod
    def get_path_from_uri(uri: str) -> str:
        return get_path_from_uri(uri)

    def get_uri_from_path(self, path: str) -> str:
        return get_uri_from_path_without_port(self._ov_server, path)
        # return get_uri_from_path(self._ov_server, 3009, path)

    def get_uri_from_path_without_port(self, path: RemoteFilePath) -> str:
        return get_uri_from_path_without_port(self._ov_server, path)

    def is_supported_uri(self, uri: str) -> bool:
        return uri.startswith("omniverse://")

    def is_valid_uri(self, uri: str) -> bool:
        return uri.startswith(self.base_uri)

    @staticmethod
    def get_file_type(item: Any) -> FileTypeMapping:
        if item.type == PathType.Mount:
            return FileTypeMapping.mount
        elif item.type == PathType.Asset:
            return FileTypeMapping.asset
        elif item.type == PathType.Folder:
            return FileTypeMapping.folder
        else:
            return FileTypeMapping.unknown

    @staticmethod
    def get_event_type(item: Any) -> Optional[EventMapping]:
        return get_event_mapping(item)

    def status_ok(self, item: Any) -> bool:
        return status_ok(item)

    def assert_on_bad_status(self, item: Any):
        assert_on_bad_status(item)

    def set_tag_context(self, tag_context: Optional["TaggingClientContextAsync"] = None) -> None:
        self._tag_context = tag_context

    @asynccontextmanager
    async def connection_context_with_tagging(
        self,
        connection: Optional[NucleusConnection] = None,
        return_self: Optional[bool] = False,
    ) -> AsyncIterator[StorageClient]:
        client: NucleusStorageClient
        async with self.connection_context(connection=connection, return_self=return_self) as client:
            async with TaggingClientContextAsync(ov_server=self._ov_server) as context:
                client.set_tag_context(context)
                yield client
                client.set_tag_context()

    async def read_tags_all_paths(
        self,
        paths: List[str],
        batch_size: int = READ_BATCH_SIZE,
        logging_timeout: float = 10,
    ) -> List[TagResultField]:
        return self._transform_nucleus_results_list(
            await self._tag_context.read_tags_all_paths_v2(
                self,
                paths=paths,
                batch_size=batch_size,
                logging_timeout=logging_timeout,
            )
        )

    async def read_tags_from_gen(
        self,
        path_generator: AsyncIterator[str],
        batch_size: Optional[int] = READ_BATCH_SIZE,
    ) -> AsyncIterator[List[TagResultField]]:
        if batch_size is None:
            batch_size = READ_BATCH_SIZE

        async for item in self._tag_context.read_tags_all_paths_gen_from_gen(
            self, paths_gen=path_generator, batch_size=batch_size
        ):
            yield self._transform_nucleus_results_list(item)

    async def add_tags(
        self,
        paths: List[Union[RemoteFileUri, RemoteFilePath]],
        tags: Union[List[TagName], Dict[TagName, TagValue]],
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
        tag_action: TagAction = TagAction.add,
    ) -> None:
        # clean paths
        paths = [get_path_from_uri(p) for p in paths]
        # set default namespace
        if target_namespace is None:
            target_namespace = str(self.default_tag_namespace())

        if tag_type == TagType.user:
            await self._tag_context.add_user_tags(self, paths=paths, tags=list(tags), target_namespace=target_namespace)
        elif tag_type == TagType.generated:
            await self._tag_context.add_predicted_tags(
                self, paths=paths, tags_dict=tags, target_namespace=target_namespace
            )
        elif tag_type is None:
            await self._tag_context.add_tags_namespace(
                storage_client=self,
                paths=paths,
                target_namespace=target_namespace,
                tags_dict=(tags if isinstance(tags, dict) else {tag: None for tag in tags}),
                action=tag_action,
            )
        else:
            raise ValueError(f"Unknown tag type: {tag_type}")

    async def get_tags(self, path: Union[RemoteFilePath, RemoteFileUri]) -> TagResultField:
        tag_results: GetTagsResult = await self._tag_context.ts.get_tags(
            auth_token=self.connection.auth.auth_token,
            paths=[self.get_path_from_uri(path)],
        )
        # make sure status is Ok
        if tag_results.status == StatusCode.Denied:
            raise AccessDeniedError(f"{path} access denied")
        if tag_results.status == StatusCode.TokenExpired:
            raise TokenExpired("token expired")
        # make sure status is Ok
        assert_status_ok_tagging(tag_results)
        path_result = tag_results.path_result[0]
        # verify connection status
        if path_result.connection_status_string == StatusType.InvalidPath:
            raise FileNotFoundError(f"{path} does not exist")
        if path_result.connection_status_string == StatusType.Denied:
            raise AccessDeniedError(f"{path} access denied")
        if path_result.connection_status_string == StatusType.TokenExpired:
            raise TokenExpired("token expired")
        # make sure status is Ok
        assert path_result.connection_status_string == StatusType.OK, path_result
        return TagResultField(
            tags=[TagField(name=t.name, value=t.value, tag_namespace=t.tag_namespace) for t in path_result.tags],
            uri=path,
        )

    @staticmethod
    def default_tag_namespace() -> str:
        return "appearance"

    def filter_tags(
        self,
        input_: TagResultField,
        tag_type: Optional[TagType] = None,
        target_namespace: str = "appearance",
    ) -> Tuple[List[TagName], List[TagValue]]:
        if tag_type == TagType.user:
            return self._tag_context.get_user_tags_ns(input_, target_namespace=target_namespace)
        elif tag_type == TagType.generated:
            return self._tag_context.get_inferred_tags_ns(input_, target_namespace=target_namespace)
        elif tag_type == TagType.excluded:
            return self._tag_context.get_banned_tags_ns(input_, target_namespace=target_namespace)
        elif tag_type is None:
            return self._tag_context.get_ns_tags(input_, namespace=target_namespace)
        else:
            raise ValueError(f"Unknown tag type: {tag_type}")

    async def clear_tags(
        self,
        paths: List[str],
        tag_type: TagType,
        target_namespace: str = "appearance",
    ) -> None:
        if tag_type == TagType.user:
            return await self._tag_context.clear_user_tags(self, paths=paths, target_namespace=target_namespace)
        elif tag_type == TagType.generated:
            return await self._tag_context.clear_predicted_tags(self, paths=paths, target_namespace=target_namespace)
        else:
            raise ValueError(f"Unknown tag type: {tag_type}")

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
        content = await self._tag_context.query_paths(
            self,
            namespace=namespace,
            path=path,
            return_paths=return_paths,
            return_tags=return_tags,
            return_values=return_values,
            return_namespaces=return_namespaces,
            exclude_hidden=exclude_hidden,
            max_results=max_results,
        )
        return TagQueryResult(
            paths=content.paths,
            tags=content.tags,
        )

    async def tag_subscription(
        self,
        uri: str,
        subscription_ready: Optional[asyncio.Event] = None,
        connection_getter: Optional[Callable] = None,
        processing_event: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[TagResultField]:
        if connection_getter is None:
            connection = self.connection
        else:
            connection = connection_getter()

        if self._tag_context is not None:
            client_id = self._tag_context.client_id
        else:
            client_id = None

        async with TaggingClientSubContextAsync(
            auth_token=connection.auth.auth_token,
            ov_server=self._ov_server,
            path=uri,
            subscription_ready=subscription_ready,
            client_id=client_id,
        ) as context:
            self._tag_sub_context = context
            try:
                async for item in context.sub:
                    yield result_wrapper(item)
            finally:
                self._tag_sub_context = None

    async def tag_update_probe(self, probe_uri: Optional[str] = None) -> None:
        return await self._tag_context.tag_update_probe(self, auth=self.connection.auth, probe_uri=probe_uri)
