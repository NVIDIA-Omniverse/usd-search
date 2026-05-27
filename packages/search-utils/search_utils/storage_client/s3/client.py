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
import warnings
from collections.abc import Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)
from xml.dom.minicompat import StringTypes

import aioboto3
import botocore.exceptions
from aioboto3.session import ResourceCreatorContext
from botocore.handlers import disable_signing

from ...misc_utils import str2bool
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
from ..data import ACL, SubscriptionSource, ThumbnailItem, ThumbnailLoadMode
from ..exceptions import AccessDeniedError
from ..utils import get_thumbnails_nucleus_style, match_patterns, run_callable
from .config import S3StorageClientConfig
from .data import path_type_from_s3_object_summary
from .exceptions import S3ObjectNotFound

logger = logging.getLogger(__name__)


class InvalidURL(ValueError):  # noqa: E701
    ...


class S3StorageClient(StorageClient):
    def __init__(self, config: S3StorageClientConfig):
        logger.debug("Initializing S3 client with config %s", config)
        self.config = config
        self.session = aioboto3.Session(
            aws_access_key_id=self.config.aws_access_key_id,
            aws_secret_access_key=self.config.aws_secret_access_key,
            region_name=self.config.region_name,
        )
        self._s3: Optional[ResourceCreatorContext] = None
        self._bucket = None
        self._listing_finished = asyncio.Event()

    @property
    def base_uri(self) -> str:
        return f"s3://{self.config.bucket_name}"

    @property
    def connection_info(self) -> str:
        return f"s3://{self.config.bucket_name}/"

    @property
    def bucket(self):
        return self._bucket

    @property
    def s3(self) -> Optional[ResourceCreatorContext]:
        return self._s3

    @property
    def allow_non_system_writes(self) -> bool:
        return str2bool(self.config.allow_non_system_writes)

    @property
    def allow_system_writes(self) -> bool:
        return str2bool(self.config.allow_system_writes)

    @property
    def system_path_prefix(self) -> str:
        return self.config.system_path_prefix

    @property
    def connection(self) -> StorageConnection:
        # For compatibility with the interface of Nucleus storage client
        return StorageConnection()

    @property
    def listing_finished(self) -> asyncio.Event:
        return self._listing_finished

    def _key_from_uri(self, uri: str) -> RemoteFilePath:
        url_prefix = f"s3://{self.config.bucket_name}/"
        if uri.startswith(url_prefix):
            return RemoteFilePath(uri[len(url_prefix) :])
        raise InvalidURL(f"{uri} is not a valid S3 URL")

    def s3_uri_to_https_uri(self, uri: str) -> str:
        key = self._key_from_uri(uri)
        if self.config.aws_endpoint_url is None:
            return f"https://{self.config.bucket_name}.s3.{self.config.region_name}.amazonaws.com/{key}"
        else:
            return f"https://{self.config.aws_endpoint_url}/{self.config.bucket_name}/{key}"

    def https_uri_to_s3_uri(self, uri: RemoteFileUri) -> RemoteFileUri:
        if self.config.aws_endpoint_url is None:
            url_prefix: str = f"https://{self.config.bucket_name}.s3.{self.config.region_name}.amazonaws.com"
        else:
            url_prefix: str = f"https://{self.config.aws_endpoint_url}/{self.config.bucket_name}"
        if uri.startswith(url_prefix.rstrip("/")):
            return RemoteFileUri(f"s3://{self.config.bucket_name}/{uri[len(url_prefix) :]}")
        raise ValueError(f"{uri} is not a valid HTTPS S3 URL")

    def get_backend_from_uri(self, uri: RemoteFileUri) -> Optional["S3StorageClient"]:
        return self

    async def get_connection(self) -> StorageConnection:
        return self.connection

    async def authenticate_connection(
        self, c: StorageConnection, token: str, timeout: Optional[float] = None
    ) -> StorageConnection:
        return self.connection

    async def connect(self) -> StorageConnection:
        return self.connection

    @asynccontextmanager
    async def connection_context(
        self,
        connection: Optional[StorageConnection] = None,
        return_self: Optional[bool] = True,
    ) -> AsyncIterator["S3StorageClient"]:
        # TODO: Support re-using the connection from args
        try:
            s3: ResourceCreatorContext
            async with self.session.resource("s3", endpoint_url=self.config.aws_endpoint_url) as s3:
                if self.config.aws_access_key_id is None:
                    s3.meta.client.meta.events.register("choose-signer.s3.*", disable_signing)
                self._s3 = s3
                if self.s3 is None:
                    raise ValueError("Incorrect s3 session")
                self._bucket = await self.s3.Bucket(self.config.bucket_name)
                yield self
        finally:
            await self.close_connection()

    async def close_connection(self, conn: Optional[StorageConnection] = None) -> None:
        pass
        # self._s3 = None
        # self._bucket = None

    def connection_getter(self) -> StorageConnection:
        return self.connection

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
        """
        List the contents of an S3 bucket

        Args:
            path_list: A list of path (not URI) prefixes to scan.
            max_concurrent_requests: n/a
            logging_timeout: n/a
            listing_timeout: n/a
            show_hidden: n/a
            recursive: n/a
            ignore_patterns: n/a
            raise_on_error: n/a
            list_type: n/a
            processing_fn: Optional function used to process the results. DEPRECATED - only for compatibility with the Nucleus client
            max_items: Maximum number of results to return for every path in `path_list`

        """
        if uri_list is None and path_list is not None:
            logger.warning("path_list is deprecated - use uri_list instead")
            uri_list = path_list

        if uri_list is None:
            uri_list = []

        path_list = [self.get_path_from_uri(uri) for uri in uri_list]

        # Mark that listing of items has started
        self._listing_finished.clear()

        # prepare paths
        prepared_paths = [path[1:] if path.startswith("/") else path for path in path_list]

        if len(path_list) == 0 or any([path == "" for path in prepared_paths]):
            obj_list_iterators = [self.bucket.objects.all().limit(max_items)]
        else:
            obj_list_iterators = [self.bucket.objects.filter(Prefix=path).limit(max_items) for path in prepared_paths]

        for obj_list_iterator in obj_list_iterators:
            async for s3_object in obj_list_iterator:
                if s3_object.key[-1] == "/":
                    continue
                if match_patterns(s3_object.key, patterns=ignore_patterns):
                    continue
                if processing_fn is None:
                    item = await path_type_from_s3_object_summary(s3_object)
                    item.source = SubscriptionSource.recursive_list.value
                    yield item
                else:
                    item = await path_type_from_s3_object_summary(s3_object)
                    item.source = SubscriptionSource.recursive_list.value
                    yield await run_callable(processing_fn, item)
        logger.debug("S3 listing complete")
        # Mark that listing of items has finished
        self._listing_finished.set()

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
        # NOTE: currently the Azure backend does not support subscriptions, so
        #  the client would re-scan the whole backend with a given frequency
        if uri and path is not None:
            raise ValueError("Setting both `uri` and `path` is not allowed")
        if uri is not None:
            path = uri
            warnings.warn(
                "`uri` parameter of NucleusStorageClient.list_items_and_subscribe is deprecated; use `path` instead",
                DeprecationWarning,
            )

        if ignore_patterns is None:
            ignore_patterns = []
        while True:
            logger.info("Scanning S3 bucket %s for path=%s...", self.config.bucket_name, path)
            n_items = 0
            async for item in self.list_items(
                uri_list=([RemoteFileUri(path)] if path is not None and path != "/" else []),
                logging_timeout=logging_timeout,
                show_hidden=show_hidden,
                ignore_patterns=ignore_patterns,
                raise_on_error=raise_on_error,
                recursive=recursive,
                list_type=list_type,
            ):
                n_items += 1
                logger.debug("Found item %s", item.uri)
                yield [item]

            logger.info(
                "Scan of S3 bucket %s for path=%s finished, found %s items",
                self.config.bucket_name,
                path,
                n_items,
            )

            if self.config.re_scan_timeout is None or self.config.re_scan_timeout <= 0:
                logger.info("Re-scanning is disabled")
                await asyncio.sleep(float("inf"))
            else:
                logger.info("Re-scanning in %ss", self.config.re_scan_timeout)
                await asyncio.sleep(self.config.re_scan_timeout)

    async def list_and_subscribe_multiple_files(
        self,
        paths: Optional[List[str]] = None,
        delay: float = 5,
        processing_event: Optional[asyncio.Event] = None,
        uris: Optional[List[RemoteFileUri]] = None,
    ) -> AsyncIterator[PathType]:
        raise NotImplementedError

    async def check_if_exists(self, uri: str) -> Tuple[bool, Optional[PathType]]:
        try:
            exists_response = await (await self.s3.Object(self.config.bucket_name, self._key_from_uri(uri))).load()
            logger.debug("File uri=%s head response: %s", uri, exists_response)
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] == "404":
                return False, None
            raise exc
        except InvalidURL:
            return False, None
        return True, PathType(uri=uri)

    async def get_item(self, uri: Union[RemoteFileUri, RemoteFilePath]) -> Optional[PathType]:
        """Get single asset metadata from the storage backend

        Args:
            uri (str): Asset URI

        Returns:
            Optional[PathType]: Asset metadata if it exists and None otherwise.
        """
        async for item in self.list_items(uri_list=[self._key_from_uri(uri)], max_items=1):
            return item
        return None

    async def upload_items(
        self,
        item_dict: Dict[RemoteFileUri, LocalFilePath],
        overwrite_content: bool = True,
        overwrite_if_fn: Optional[Callable[[PathType], bool]] = None,
    ) -> None:
        logger.debug("Uploading a batch of %s files", len(item_dict))
        await asyncio.gather(
            *[self._upload_file(local_file_path, self._key_from_uri(uri)) for uri, local_file_path in item_dict.items()]
        )

    def _verify_modification_permissions(self, key: str) -> bool:
        """Check if it is allowed for the client to write data to S3.

        Args:
            key (str): location, where data needs to be written

        Returns:
            bool: ``True`` if it is allowed to wite in that provided location
        """

        if key.startswith(self.system_path_prefix):
            if not self.allow_system_writes:
                logger.warning(
                    "Writing to a system folder is not allowed (key=%s, system_folder_prefix=%s)",
                    key,
                    self.system_path_prefix,
                )
                return False
        else:
            if not self.allow_non_system_writes:
                logger.warning(
                    "Writing to a non-system folder is not allowed (key=%s, system_folder_prefix=%s)",
                    key,
                    self.system_path_prefix,
                )
                return False

        return True

    @staticmethod
    def _is_access_denied(exc: botocore.exceptions.ClientError) -> bool:
        error = exc.response.get("Error", {}) if hasattr(exc, "response") else {}
        code = str(error.get("Code", ""))
        status = error.get("HTTPStatusCode") or exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return code in ("AccessDenied", "403", "AllAccessDisabled", "Forbidden") or status == 403

    async def _upload_file(self, local_file_path: str, key: str) -> None:
        if key.startswith("/"):
            key = key[1:]
        logger.debug("Uploading file key=%s", key)
        t_start = datetime.now()

        if not self._verify_modification_permissions(key):
            raise AccessDeniedError(f"No permission for modifying '{key}'")

        try:
            await self.bucket.upload_file(local_file_path, key)
        except botocore.exceptions.ClientError as exc:
            if self._is_access_denied(exc):
                raise AccessDeniedError(f"Access denied uploading to '{key}': {exc}") from exc
            raise

        duration_seconds = (datetime.now() - t_start).total_seconds()
        logger.debug("Uploading file key=%s done in %ss", key, duration_seconds)

    async def _upload_file_contents(self, file_contents: bytes, key: str) -> None:
        if key.startswith("/"):
            key = key[1:]
        logger.debug("Uploading file key=%s", key)
        t_start = datetime.now()

        if not self._verify_modification_permissions(key):
            raise AccessDeniedError(f"No permission for modifying '{key}'")

        try:
            await self.bucket.put_object(Body=file_contents, Key=key)
        except botocore.exceptions.ClientError as exc:
            if self._is_access_denied(exc):
                raise AccessDeniedError(f"Access denied uploading to '{key}': {exc}") from exc
            raise

        duration_seconds = (datetime.now() - t_start).total_seconds()
        logger.debug("Uploading file key=%s done in %ss", key, duration_seconds)

    async def upload_items_content(
        self,
        item_dict: Dict[RemoteFileUri, bytes],
        overwrite_content: bool = True,
        # overwrite_if_fn: Optional[Callable] = None,
    ) -> None:
        logger.debug("Uploading a batch of %s files", len(item_dict))
        await asyncio.gather(
            *[self._upload_file_contents(content, self._key_from_uri(uri)) for uri, content in item_dict.items()]
        )

    async def delete_items(self, uri_list: Union[RemoteFileUri, List[RemoteFileUri]]) -> None:
        logger.debug("Deleting item_list=%s", uri_list)

        # TODO: Split into batches when len(item_list) > 1000
        # if provided item is not iterable - make it a list
        if not (isinstance(uri_list, Iterable) and not isinstance(uri_list, StringTypes)):
            uri_list = [uri_list]

        objects = [
            {"Key": self._key_from_uri(uri)}
            for uri in uri_list
            if self._verify_modification_permissions(self._key_from_uri(uri))
        ]

        if len(objects) > 0:
            await self.bucket.delete_objects(
                Delete={
                    "Objects": objects,
                },
            )

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

    async def download_file_content(self, uri: str, timeout: Optional[float] = None) -> bytes:
        # TODO: Consider saving the file to disk
        # TODO: support timeout param
        key = self._key_from_uri(uri)
        logger.debug("Downloading uri=%s", uri)
        try:
            response = await (await self.bucket.Object(key)).get()
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                logger.debug("File uri=%s not found", uri)
                raise S3ObjectNotFound from exc
            raise exc
        return bytes(await response["Body"].read())

    async def copy(self, source: str, target: str) -> Tuple[bool, CopyResult]:
        raise NotImplementedError

    async def check_connection(self, ping_timeout: Optional[float] = None) -> bool:
        async with self.session.resource("s3", endpoint_url=self.config.aws_endpoint_url) as s3:
            try:
                if self.config.aws_access_key_id is None:
                    s3.meta.client.meta.events.register("choose-signer.s3.*", disable_signing)
                await s3.meta.client.head_bucket(Bucket=self.config.bucket_name)
                return True
            except botocore.exceptions.ClientError as exc:
                logger.error("S3 bucket unavailable: %s", exc)
                return False

    @property
    def _default_acl(self) -> Set[ACL]:
        return {ACL.admin, ACL.write, ACL.read}

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

    async def update_acl(self, path_dict: Dict[str, str]) -> None:
        raise NotImplementedError

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

        # get thumbnails in nucleus style
        thumbnail_uris_list = await get_thumbnails_nucleus_style(
            storage_client=self,
            uri=uri,
            thumbnail_path_templates=thumbnail_path_templates,
            thumbs_loc=thumbs_loc,
            suffixes=suffixes,
            res_map=res_map,
        )

        thumbnail_list = []

        for thumbnail_uri in thumbnail_uris_list:
            try:
                s3_object = await self.get_item(thumbnail_uri)
                if s3_object is not None:
                    if mode == ThumbnailLoadMode.one:
                        return ThumbnailItem(
                            data=await asyncio.wait_for(
                                self.download_file_content(thumbnail_uri),
                                timeout=timeout,
                            ),
                            uri=thumbnail_uri,
                            etag=s3_object.etag,
                        )
                    elif mode == ThumbnailLoadMode.all:
                        thumbnail_list.append(
                            ThumbnailItem(
                                data=await asyncio.wait_for(
                                    self.download_file_content(thumbnail_uri),
                                    timeout=timeout,
                                ),
                                uri=thumbnail_uri,
                                etag=s3_object.etag,
                            )
                        )
                    else:
                        raise ValueError(f"thumbnail mode is incorrectly set: {mode}")
            except FileNotFoundError:
                logger.debug("Thumbnail thumbnail_uri=%s not found", thumbnail_uri)
        if len(thumbnail_list) == 0:
            # if no file found
            logger.debug("Thumbnail is missing for asset uri=%s", uri)
            raise S3ObjectNotFound(f"Thumbnail is missing for asset {uri=}")

        return thumbnail_list

    def get_path_from_uri(self, uri: str) -> RemoteFilePath:
        try:
            return RemoteFilePath("/" + self._key_from_uri(uri))
        except ValueError:
            return RemoteFilePath(uri)

    def get_uri_from_path(self, path: Union[RemoteFileUri, RemoteFilePath]) -> RemoteFileUri:
        if path.startswith("/"):
            path = RemoteFilePath(path[1:])
        return RemoteFileUri(f"s3://{self.config.bucket_name}/{path}")

    def is_supported_uri(self, uri: str) -> bool:
        return uri.startswith("s3://")

    def is_valid_uri(self, uri: str) -> bool:
        return uri.startswith(self.base_uri)

    def get_file_type(self, item: PathType) -> FileTypeMapping:
        # TODO
        return FileTypeMapping.asset

    def get_event_type(self, item: PathType) -> Optional[EventMapping]:
        pass

    def status_ok(self, item: PathType) -> bool:
        return True

    def assert_on_bad_status(self, item: PathType) -> None:
        pass

    async def add_tags(
        self,
        paths: List[Union[RemoteFilePath, RemoteFileUri]],
        tags: Union[List[TagName], Dict[TagName, TagValue]],
        tag_type: Optional[TagType] = None,
        target_namespace: Optional[str] = None,
        tag_action: TagAction = TagAction.add,
    ) -> None:
        raise NotImplementedError

    async def get_tags(self, path: Union[RemoteFilePath, RemoteFileUri]) -> TagResultField:
        raise NotImplementedError

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
