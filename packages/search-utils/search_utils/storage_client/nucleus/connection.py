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
import os
import time
from contextlib import asynccontextmanager

# standard modules
from dataclasses import dataclass
from typing import Any, AsyncGenerator, AsyncIterator, List, Optional, Tuple, Union

# third party modules
import aiohttp
from idl.connection.transport import TransportError
from omni.client import GetACLResponses  # ListIncludeOption,
from omni.client import (
    Connection,
    List2Response,
    List2ResponsePathEntry,
    Path,
    PathAtVersion,
    PathAtVersionACLPair,
    PathType,
    Stat2Result,
    StatusType,
)
from omni.discovery import DiscoverySearch
from omni.lft import LFT_THRESHOLD, FileTransfer, FileTransferException

from ... import log_utils as lu
from ...misc_utils import get_percentage_string
from .. import (
    MAX_CONCURRENT_REQUESTS,
    RemoteFilePath,
    RemoteFileUri,
    StorageConnection,
    tracer,
)
from ..data import ACL
from ..data import PathType as StorageClientPathType
from ..data import SubscriptionSource, VerifyBatchAccessResponse
from ..utils import CombinedAsyncGen, match_patterns

# local / proprietary module
from . import (
    ASSERT_ADMIN_USER,
    DEBUG_LOGGING,
    DEPLOYMENT_LOOKUP,
    NUCLEUS_REQUIRED_CAPABILITIES,
    logger,
)
from .auth import NucleusAuth, NucleusAuthEnv, NucleusAuthResponse, auth_conn
from .data import List2Response_to_PathType, OmniClientPath_to_PathType
from .exceptions import InvalidCommandException
from .utils import (
    assert_on_bad_status,
    assert_on_invalid_command,
    status_done,
    status_latest,
    status_ok,
)


@dataclass
class NucleusConnection(StorageConnection):
    conn: Connection = None
    auth: NucleusAuthResponse = None
    timeout: float = None


class omni_connection_wrapper:
    """Wrapper over omniverse connection that uses :py:mod:`AuthTokenRegistry`.
    If an existing omniverse connection is provided it will just use it and skip creation of a new one.

    Args:
        ov_server (str): omniverse server host
        ov_user (str): name of the user
        ov_pass (str): password for the user
        connection (omni_conn.OmniverseConnection, optional): omniverse connection. Defaults to ``None``.
        timeout (float): Connection timeout. Defaults to ``3600``
        create_new (bool): Trigger to initialize new connection. Defaults to ``False``.
    """

    def __init__(
        self,
        ov_server: str,
        auth: Union[NucleusAuthEnv, NucleusAuth] = None,
        connection: Optional[NucleusConnection] = None,
        timeout: float = 3600,
        create_new_connection: bool = False,
        assert_admin_access: bool = ASSERT_ADMIN_USER,
        **kwargs,
    ):
        self.connection = connection
        if self.connection is None or create_new_connection:
            logger.warning(
                ("Force creation" if create_new_connection else "Connection not provided")
                + " - creating a new connection."
            )
            self.ov_server = ov_server
            self.ov_user: Optional[str] = auth.user
            self.ov_pass: Optional[str] = auth.password
            self.ov_token: Optional[str] = auth.token
            self.timeout = timeout
            self.assert_admin_access = assert_admin_access
        # elif not check_connection(self.connection):
        #     omniverse_utils_logger.warning("Provided connection is invalid")
        #     raise ConnectionError("Connection is lost")
        else:
            logger.debug("Using provided connection")

    async def init_connection(self) -> NucleusConnection:
        """Initialize Nucleus connection."""
        # get connection
        with lu.print_wrapper("Get nucleus connection", enabled=False):
            self.c = await get_nucleus_connection(self.ov_server)
        # authenticate connection
        with lu.print_wrapper("authenticate connection", enabled=False):
            self.auth = await auth_conn(
                self.c,
                self.ov_server,
                auth=NucleusAuth.model_construct(
                    user=self.ov_user,
                    password=self.ov_pass,
                    token=self.ov_token,
                    assert_admin_user=self.assert_admin_access,
                ),
                omni_connection_timeout=self.timeout,
            )
        return NucleusConnection(conn=self.c, auth=self.auth, timeout=self.timeout)

    async def __aenter__(self) -> NucleusConnection:
        if self.connection is not None:
            return self.connection
        else:
            return await self.init_connection()

    async def __aexit__(self, *args, **kwargs):
        if self.connection is not None:
            logger.debug("wrapper was using existing connection. Nothing to be done here")
        else:
            await close_connection(self.c)


async def close_connection(c: Connection):
    await c.transport.close()


async def get_nucleus_connection(ov_server: str, deployment_lookup: str = DEPLOYMENT_LOOKUP) -> Connection:
    """Get Nucleus connection from discovery service.

    Args:
        ov_server (str): Nucleus server URL
        deployment_lookup (str, optional): Deployment look-up that need to be used by the service (typically external). Defaults to DEPLOYMENT_LOOKUP.

    Returns:
        Connection: connection to the Nucleus server
    """
    async with DiscoverySearch(ov_server) as discovery:
        return await discovery.find(
            Connection,
            {"deployment": deployment_lookup},
            capabilities=NUCLEUS_REQUIRED_CAPABILITIES,
        )


async def deletion_callback(c, f):
    logger.debug(f"Removing file: {f}")
    async for r in c.delete(f):
        if r.status not in [StatusType.OK, StatusType.Done]:
            logger.warning(f"Deletion status '{r.status}' for {f}")
        break


async def check_if_exists(conn: NucleusConnection, path: str):
    """Check that the omniverse file exists.

    Args:
        conn: omniverse connection
        path: path to an asset in omniverse
    """
    if DEBUG_LOGGING:
        logger.debug("checking if %s exists", path)
    res: Stat2Result = await conn.conn.stat2(PathAtVersion(path=path))
    if status_ok(res):
        return True, res
    return False, "error"


async def get_single_item(c: NucleusConnection, path: str) -> Stat2Result:
    """Get single item from omniverse

    Args:
        c: omniverse connection
        path (str): path to the file in omniverse

    Returns:
        item from omniverse
    """
    file_exists, file = await check_if_exists(c, path)

    if file_exists:
        return file
    else:
        return None


async def delete_file(
    c: NucleusConnection,
    omni_paths: Union[str, List[str]],
    verify: callable = None,
    **kwargs,
):
    """Delete a list of files from omniverse.

    Args:
        c: omniverse connection
        omni_paths (list, str): list of files that need to be deleted
        verify (callable): function that receives file handle and returns bool for files that need to be deleted

    Raises:
        ValueError: if input type is not ``list`` of ``str``
    """

    if isinstance(omni_paths, str):
        omni_paths = [omni_paths]
    elif not isinstance(omni_paths, list):
        raise ValueError(f"unknown input format: expected (str, list), got {type(omni_paths)}")

    async def deletion_task(uri: str):
        # delete file is needed
        if verify is None:
            await deletion_callback(c.conn, uri)
        else:
            file = await get_single_item(c.conn, uri)
            if file is not None and verify(file):
                await deletion_callback(c.conn, uri)

    await asyncio.gather(*[deletion_task(f) for f in omni_paths])


async def upload_file(
    c: NucleusConnection,
    local_file: str,
    omni_f: str,
    overwrite_content: bool = True,
    overwrite_if_fn: callable = None,
    **kwargs,
):
    """Reads the local file and uses :func:`upload_file_content` to upload local file to omniverse.

    Args:
        c: omniverse connection
        config: service configuration from :mod:`config.AssetDBConfig`
        str local_file: path to the local file that needs to be uploaded
        str omni_f: path to the location in omniverse, where the file needs to be uploaded
        **kwargs: additional arguments that are passed to :func:`upload_file_content`
    """

    if overwrite_if_fn is not None:
        logger.debug("'overwrite_if_fn' is set. Ignoring 'overwrite_content' variable")
        file = await get_single_item(c, omni_f)
        overwrite_content = overwrite_if_fn(file)

    # reading the content
    if os.path.exists(local_file):
        with open(local_file, "rb") as f:
            content = f.read()
        # uploading the content
        await upload_file_content(
            c,
            content,
            omni_f,
            overwrite_content=overwrite_content,
        )
    else:
        logger.warning(f"File {local_file} does not exist. ")
        if not overwrite_content:
            logger.warning(
                f"Upload to {omni_f} failed: 'overwrite_content' is set to True, but the file does not exist"
            )


async def upload_file_content(
    c: NucleusConnection,
    content,
    omni_f: str,
    overwrite_content: bool = True,
):
    """Write file content to an omniverse file.

    Args:
        c: omniverse connection
        config: service configuration from :mod:`config.AssetDBConfig`
        bytes content: file content that needs to be written to omniverse
        str omni_f: path to the location in omniverse, where the file needs to be uploaded
        logger: logging function
        service_channel: service message channel that is used for sending omniverse messages if not ``None``. Default: ``None``
        bool overwrite_content: if ``True`` the content of the file in omniverse will be overwritten if existed.
    """
    # check the omniverse path
    if not overwrite_content:
        file_exists, _ = await check_if_exists(c, omni_f)
    else:
        file_exists = False

    if overwrite_content or not file_exists:
        # make sure that the file content is not None
        assert content is not None, "File content is empty, check if it exists"
        # upload file to omniverse
        logger.debug(f"File {omni_f} will be overwritten or created.")
        logger.debug(f"uploading {omni_f}")
        async with file_transfer(c) as ft:
            async with await ft.create(
                overwrite=True,
                path=omni_f,
                total_bytes=len(content),
                timeout=c.timeout,
            ) as uploader:
                await uploader.upload(content)


@asynccontextmanager
async def file_transfer(conn: NucleusConnection):
    """File upload context for uploading data to Nucleus (through LFT)"""
    async with FileTransfer(
        lft=conn.auth.auth.lft_address,
        connection=conn.conn,
        token=conn.auth.auth.token,
        connection_id=conn.auth.auth.connection_id,
        connection_id_signature=conn.auth.auth.connection_id_signature,
        lft_threshold=LFT_THRESHOLD,
    ) as ft:
        try:
            yield ft
        except FileTransferException as e:
            if e.code == StatusType.Denied:
                logger.debug("Writing to read-only directory")
            elif e.code == StatusType.MountExistsUnderPath:
                logger.debug("Writing to a mount, which is read-only directory")
            else:
                raise e


async def download_file_content(
    c: NucleusConnection, uri: str, etag: str = "", timeout: float = -1
) -> Tuple[bytearray, str]:
    """Download the file from omniverse.

    Args:
        conn: omniverse connection
        str uri: path to a file location in omniverse
        str etag: unique ID of the file. Can be set to ``""``. Default: ``""``
        float timeout: timeout for the download operation
    """

    # make sure timeout is int
    if timeout is None:
        timeout = -1

    file_exists, file = await check_if_exists(c, uri)

    if not file_exists:
        raise FileNotFoundError(f"File {uri} does not exist on the omniverse server")

    logger.debug(f"downloading {uri}")

    async with file_transfer(c) as ft:
        downloaded = False
        while not downloaded:
            try:
                data = bytearray()
                async with await ft.download(path=uri, etag=etag, timeout=timeout) as downloader:
                    async for content in downloader.download():
                        data += content
                    downloaded = True
            except aiohttp.client_exceptions.ClientPayloadError:
                logger.warn("Client Payload Error, trying again.. ")

    return data, file.etag


async def download_file(
    c: NucleusConnection,
    local_file: str,
    omni_f: str,
    cap_data: bool = False,
    cap_size: float = -1,
    missing_ok: bool = False,
    timeout: float = None,
) -> bool:
    """Downloads the file from omniverse using :func:`download_file` and saves the file locally.

    Args:
        c: omniverse connection
        config: service configuration from :mod:`config.AssetDBConfig`
        local_file (str): path to the local file, where the omniverse file need to be downloaded
        omni_f (str): path to the location in omniverse, which needs to be downloaded
        cap_data (bool, optional): if `True` caps the data to a given size. Defaults to False.
        create_folder (bool, optional): [description]. Defaults to True.

    Returns:
        bool: ``True`` if data was capped and ``False`` otherwise.
    """

    try:
        data, _ = await download_file_content(c, omni_f, "", timeout=timeout)
    except Exception as e:
        if missing_ok:
            return
        else:
            raise (e)

    if cap_data:
        capped_data, was_capped = get_capped_data(data, cap_size=cap_size, return_status=True)
    else:
        was_capped = False
        capped_data = bytes(data)

    # create destination folder if it does not exist
    os.makedirs(os.path.dirname(local_file), exist_ok=True)

    with open(local_file, "wb") as fl:
        fl.write(capped_data)

    logger.debug(f"{omni_f} downloaded to {local_file}")
    return was_capped


def get_capped_data(inData, cap_size: float = -1, return_status: bool = False):
    """Cape the data if the file is too large.

    Args:
        bytes inData: byte string that need to be capped (typically corresponds to an omniverse asset)
        config: configuration of the service from :mod:`config.AssetDBConfig`

    Returns:
        bytes: capped byte string
    """
    data_size = len(inData)
    if cap_size > 0:
        prefetch_size = int(min(cap_size * 1024 * 1024, data_size))
        data_is_capped = prefetch_size < data_size
    else:
        prefetch_size = data_size
        data_is_capped = False

    capped_data = bytes(inData[0:prefetch_size])
    if not return_status:
        return capped_data
    else:
        return capped_data, data_is_capped


async def recursive_list(*args, processing_fn: callable = None, **kwargs):
    paths = []
    async for item in recursive_list_gen(*args, **kwargs):
        if processing_fn is not None:
            await processing_fn(item)
        else:
            paths.append(item)

    return paths


async def recursive_list_gen(
    c: NucleusConnection,
    path_list: List[str],
    max_concurrent_requests: Optional[int] = MAX_CONCURRENT_REQUESTS,
    logging_timeout: Optional[float] = 10,
    listing_timeout: Optional[float] = 20,
    show_hidden: Optional[bool] = False,
    recursive: Optional[bool] = True,
    ignore_patterns: Optional[List[str]] = [".*/.thumbs/.*"],
    raise_on_error: Optional[bool] = True,
    list_type: Optional[PathType] = PathType.Asset,
    msg: Optional[str] = "",
    processing_event: Optional[asyncio.Event] = None,
    skip_mounts: bool = False,
) -> AsyncIterator[StorageClientPathType]:
    """Recursively list the contents of the folder and get all the files stored there.

    Args:
        c: omniverse connection
        list path_list: list of paths that need to be checked
        int max_concurrent_requests: maximum number of concurrent request to the nucleus server
        float logging_timeout: logging timeout in seconds
        list ignore_patterns: list of file path patterns that need to be ignored in the search
        bool raise_on_error: if True an exception will be raised on invalid path
        PathType list_type: filters output list results by path type on the nucleus side. If None - returns all of them.
        callable processing_fn: awaitable function that can replace accumulation of items in memory
        asyncio.Event processing_event: if cleared the recursive listing is paused
    """

    # account for the fact that there might be folders
    path_list += [p.rstrip("/") + "/" for p in path_list]
    # make sure only unique files are present
    path_list = list(set(path_list))

    # path check
    existence_list = await asyncio.gather(*[check_if_exists(c, p) for p in path_list])
    # paths = []
    folder_list: List[str] = []

    for p, content in zip(path_list, existence_list):
        exists, item = content
        if exists and not match_patterns(p, patterns=ignore_patterns):
            if item.type == PathType.Mount:
                if not skip_mounts:
                    folder_list.append(p)
                else:
                    logger.info(f"Skipping mount: {p}")

            elif item.type == PathType.Folder:
                folder_list.append(p)

            if (list_type is None or item.type == list_type) and not (item.type == PathType.Mount and skip_mounts):
                yield StorageClientPathType(**item, source=SubscriptionSource.recursive_list.value)

    list_runner = 0
    bg = time.time()
    # filter out those items that do not end up with "/"
    folder_list = [f for f in folder_list if f.endswith("/")]
    # max_concurrent_requests = 10
    while len(folder_list[list_runner:]) > 0:
        if processing_event is not None:
            await processing_event.wait()
        if max_concurrent_requests > 0:
            max_runner = list_runner + max_concurrent_requests
        else:
            max_runner = None

        # create list of concurrent request to the server
        #
        awaitables = [
            conn_list2_to_list(
                list2(
                    conn=c.conn,
                    path=p,
                    show_hidden=show_hidden,
                    # include_option=ListIncludeOption.IncludeDeleted,
                ),
            )
            for p in folder_list[list_runner:max_runner]
            if not match_patterns(p, patterns=ignore_patterns)
        ]
        # list_runner += len(awaitables)
        list_runner += len(folder_list[list_runner:max_runner])
        # omniverse_utils_logger.info("here")
        items_list: List[List[List2ResponsePathEntry]] = await asyncio.gather(*awaitables)
        logger.debug("item list: %s", str(len([it for it in items_list if len(it) > 0])))

        # go through all the item lists from concurrent requests
        for items in items_list:
            # go through all the files
            for item in items:
                # make sure that item status is Ok
                if hasattr(item, "status") and not status_ok(item):
                    continue
                # ignore file patterns
                if match_patterns(item.path, patterns=ignore_patterns):
                    continue

                # if the file is a folder - add it to the folder list
                #  otherwise add to the output list
                if recursive:
                    if item.path_type == PathType.Mount:
                        if not skip_mounts:
                            folder_list.append(item.path)
                        else:
                            logger.info(f"Skipping mount: {item.path}")

                    if item.path_type == PathType.Folder:
                        folder_list.append(item.path)

                if (list_type is None or item.path_type == list_type) and not (
                    item.path_type == PathType.Mount and skip_mounts
                ):
                    try:
                        reponse_item = List2Response_to_PathType(item)
                        reponse_item.source = SubscriptionSource.recursive_list.value
                        yield reponse_item
                    except Exception as e:
                        logger.warning("List2Response to Path conversion Error: %s", str(e))

        # log with certain frequency.
        if time.time() - bg > logging_timeout:
            logger.info(
                "%s recursive omniverse listing: %s",
                "",
                get_percentage_string(list_runner, len(folder_list)),
            )
            bg = time.time()


async def gen_list_wrapper(
    list_gen: AsyncGenerator[Union[StorageClientPathType, Path], None],
    raise_on_error: bool = False,
    only_list: bool = False,
    batch_size: int = -1,
    ignore_patterns: list = ["/.system/"],
    timeout: float = 30,
) -> List[Union[StorageClientPathType, Path]]:
    res: List[Union[StorageClientPathType, Path]] = []
    counter = 0

    buffer_queue: "asyncio.Queue[Union[StorageClientPathType, Path]]" = asyncio.Queue()
    terminated = asyncio.Event()

    async def gen_queue_exporter():
        async for it in list_gen:
            buffer_queue.put_nowait(it)
        logger.info("List subscription terminated")
        terminated.set()

    # init exporter task that will push all items from the generator to the buffer queue
    list_task = asyncio.create_task(gen_queue_exporter())

    try:
        while not (terminated.is_set() and buffer_queue.empty()):
            try:
                p = await asyncio.wait_for(buffer_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug("++ No updates: waiting..")
                counter = 0
                yield res
                res = []
                continue

            except RuntimeError as exc_info:
                logger.error("Runtime Error: %s", str(exc_info))
            except StopAsyncIteration:
                logger.info("List subscription terminated")
                return

            if p is None or (
                hasattr(p, "uri") and p.uri is not None and match_patterns(p.uri, patterns=ignore_patterns)
            ):
                continue

            counter += 1
            res.append(p)
            if status_latest(p) or (batch_size > 0 and counter >= batch_size):
                yield res
                res = []
                counter = 0
                if only_list:
                    break

    finally:
        list_task.cancel()


async def omni_list_and_subscribe(
    c: NucleusConnection,
    path: str,
    batch_size: Optional[int] = -1,
    max_concurrent_requests: Optional[int] = MAX_CONCURRENT_REQUESTS,
    raise_on_error: Optional[bool] = True,
    recursive: Optional[bool] = True,
    show_hidden: Optional[bool] = False,
    ignore_patterns: list = [".*/.thumbs/.*"],
    logging_timeout: Optional[float] = 10,
    listing_timeout: Optional[float] = 20,
    list_type: Optional[PathType] = PathType.Asset,
    processing_event: Optional[asyncio.Event] = None,
    skip_mounts: bool = False,
    **kwargs,
):
    """Wrapper around the omniverse connection list and subscribe function,
    where omniverse connection is passed as a parameter.

    Args:
        c: Nucleus Connection
    """

    try:
        # check if command is available
        # TODO: check if there is a better way of doing it
        async for event in c.conn.service_subscribe_list():
            assert_on_invalid_command(event)
            break

        return gen_list_wrapper(
            client_list_and_subscribe_gen(
                c,
                path=path,
                max_concurrent_requests=max_concurrent_requests,
                show_hidden=show_hidden,
                list_type=list_type,
                ignore_patterns=ignore_patterns,
                logging_timeout=logging_timeout,
                listing_timeout=listing_timeout,
                processing_event=processing_event,
                skip_mounts=skip_mounts,
            ),
            raise_on_error=raise_on_error,
            batch_size=batch_size,
            timeout=listing_timeout,
        )
    except InvalidCommandException:
        logger.warning("'service_subscribe_list' is not available. Falling back to recursive list")
        return gen_list_wrapper(
            c.conn.list(uri=path, recursive=recursive, show_hidden=show_hidden, **kwargs),
            raise_on_error=raise_on_error,
            batch_size=batch_size,
            timeout=listing_timeout,
        )


async def client_list_and_subscribe_gen(
    c: NucleusConnection,
    path: str,
    max_concurrent_requests: Optional[int] = MAX_CONCURRENT_REQUESTS,
    show_hidden: Optional[bool] = False,
    ignore_patterns: Optional[List[str]] = [".*/.thumbs/.*"],
    raise_on_error: Optional[bool] = True,
    logging_timeout: Optional[float] = 10,
    listing_timeout: Optional[float] = 10,
    list_type: Optional[PathType] = PathType.Asset,
    processing_event: Optional[asyncio.Event] = None,
    skip_mounts: bool = False,
) -> StorageClientPathType:
    # make sure path is valid
    if path.endswith("*"):
        path = path[:-1]

    async def event_subscription():
        try:
            async for item in c.conn.service_subscribe_list():
                path_type_item: StorageClientPathType = OmniClientPath_to_PathType(item)
                path_type_item.source = SubscriptionSource.subscription.value
                if path_type_item.uri is not None:
                    if not path_type_item.uri.startswith(path):
                        continue
                yield path_type_item
        except Exception as exc_info:
            logger.exception("Event subscription error: %s", str(exc_info))

    async with CombinedAsyncGen(
        {
            "service event subscription": event_subscription(),
            "client-side recursive listing": recursive_list_gen(
                c,
                path_list=[path],
                max_concurrent_requests=max_concurrent_requests,
                show_hidden=show_hidden,
                ignore_patterns=ignore_patterns,
                raise_on_error=raise_on_error,
                list_type=list_type,
                logging_timeout=logging_timeout,
                listing_timeout=listing_timeout,
                processing_event=processing_event,
                skip_mounts=skip_mounts,
            ),
        }
    ) as combined_generator:
        async for item in combined_generator:
            yield item


async def check_connection(conn: NucleusConnection, ping_timeout: float = None) -> bool:
    """Check that connection is alive.

    Args:
        conn (omni_conn.OmniverseConnection): omniverse connection

    Returns:
        bool: if connection is alive
    """
    if conn is None:
        logger.warning("Connection is 'None'")
        return False
    elif not (await ping_connection(conn, ping_timeout)):
        lu.prepare_message(
            msg="Connection lost",
            item_list=[f"connection: {conn}"],
            logger=logger.debug,
        )
        return False
    else:
        return True


async def ping_connection(conn: NucleusConnection, ping_timeout: float = None) -> bool:
    try:
        await asyncio.wait_for(conn.conn.ping(), timeout=ping_timeout)
        return True
    except TransportError as e:
        if str(e).find("Connection is already closed") >= 0:
            logger.warning(f"Connection: {conn.conn} is closed")
        else:
            logger.warning(f"Transport error: {str(e)}: [{conn.conn}]")
    except Exception as e:
        logger.exception(f"Ping error: {str(e)}")
    return False


def get_final_acl(path: str, response: dict) -> List[ACL]:
    """Extract the ACL information from the list of resolved ACLs returned by Nucleus"""
    if status_ok(response):
        final_acl = set([])
        for v in response["acl"].values():
            if v["path"] == path:
                final_acl = final_acl | set(v["acl"])
        return list(final_acl)
    else:
        return []


async def batch_verify_access(
    path_list: list,
    conn: NucleusConnection,
    max_nucleus_requests: int = 512,
    batch_return: bool = True,
    return_meta: bool = False,
) -> Union[
    AsyncGenerator[List[VerifyBatchAccessResponse], None],
    AsyncGenerator[VerifyBatchAccessResponse, None],
]:
    """For each input path - contact nucleus and check if this file exists / user has access to it.

    Args:
        path_list (list): list of paths that need to be checked
        conn (dict): omniverse connection dictionary
        max_nucleus_requests (int, optional): maximum number of parallel nucleus requests. Defaults to 512.
        batch_return (bool, optional): if `True` yield in batches, else, yield one by one. Defaults to True.

    Yields:
        list: list of paths that have been verified
    """

    async def get_acl_resolved(paths):
        with tracer.start_as_current_span("omni_command_get_acl_resolved"):
            return await conn.conn.get_acl_resolved([PathAtVersion(path=p) for p in paths])

    async def stat2(path, exists):
        if not exists:
            return None
        else:
            with tracer.start_as_current_span("omni_command_stat2") as span:
                span.set_attribute("path", path)
                return await conn.conn.stat2(PathAtVersion(path=path))

    for it in range(0, len(path_list), max_nucleus_requests):
        paths = path_list[it : it + max_nucleus_requests]
        res = await get_acl_resolved(paths)
        # make sure status or overall response is correct
        assert_on_bad_status(res)

        exists_status = [status_ok(r) for r in res.responses]
        acls = [get_final_acl(p, r) for p, r in zip(paths, res.responses)]
        if return_meta:
            file_meta = await asyncio.gather(*[stat2(r, exists) for r, exists in zip(paths, exists_status)])
        else:
            file_meta = [None] * len(exists_status)

        results: List[VerifyBatchAccessResponse] = []
        for path, exists, acl, file_meta in zip(paths, exists_status, acls, file_meta):
            results.append(VerifyBatchAccessResponse.model_construct(path=path, exists=exists, acl=acl, meta=file_meta))

        if batch_return:
            yield results
        else:
            for r in results:
                yield r


# def status_ok(result) -> bool:
#     return result.get("status") == StatusType.OK


async def update_acl(conn: NucleusConnection, src_paths: List[str], tgt_paths: List[str]) -> None:
    src_exists = await asyncio.gather(
        *[check_if_exists(conn, p) for p in src_paths],
    )
    tgt_exists = await asyncio.gather(
        *[check_if_exists(conn, p) for p in tgt_paths],
    )

    filtered_src_paths = []
    filtered_tgt_paths = []

    for sp, tp, se, te in zip(src_paths, tgt_paths, src_exists, tgt_exists):
        if se[0]:
            if te[0]:
                filtered_tgt_paths.append(tp)
                filtered_src_paths.append(sp)
            else:
                logger.debug("target file '%s' is missing", tp)
        else:
            logger.debug("source file '%s' is missing", sp)

    if len(filtered_src_paths) > 0:
        # get source file ACL
        acls: GetACLResponses = await conn["conn"].get_acl_v2(
            paths=[PathAtVersion(path=uri) for uri in filtered_src_paths]
        )
        # verify status
        status_ok(acls)

        assert len(filtered_tgt_paths) == len(acls.responses)

        path_and_acls = []
        for src_uri, tgt_uri, r in zip(filtered_src_paths, filtered_tgt_paths, acls.responses):
            if r.status != StatusType.OK:
                logger.warning("Not OK (%s) ACL get status for %s, skipping", r.status, src_uri)
            elif r.acl is None:
                logger.warning("ACL for %s is missing, skipping", src_uri)
            else:
                path_and_acls.append(PathAtVersionACLPair(path_at_version=PathAtVersion(path=tgt_uri), acl=r.acl))

        # update ACLs in taget location
        lu.prepare_message(
            msg="updating ACLs",
            item_list=path_and_acls,
            logger=logger.debug,
        )

        response = await conn.conn.set_acl_v2(path_and_acls)

        # verify status
        status_ok(response)
        # verify status of ACL update for each path
        for path_acl_pair, status in zip(path_and_acls, response.pathStatuses):
            if status != StatusType.OK:
                logger.warning(
                    "Not OK (%s) ACL set status for %s, skipping",
                    status,
                    path_acl_pair.path_at_version,
                )


def get_path_from_uri(
    omni_path: Union[RemoteFileUri, RemoteFilePath],
) -> RemoteFilePath:
    if omni_path.startswith("omniverse://"):
        omni_path = omni_path[12:]
    ind = omni_path.find("/")
    return omni_path[ind:]


def get_uri_from_path(omni_server: str, omni_port: int, path: RemoteFilePath) -> RemoteFileUri:
    # TODO: Port here is provided for legacy reasons
    #  In practice this port-based access is long deprecated.
    return f"omniverse://{omni_server}:{omni_port}{path}"


def get_uri_from_path_without_port(omni_server: str, path: RemoteFilePath) -> RemoteFileUri:
    return f"omniverse://{omni_server}{path}"


async def omni_copy(c: NucleusConnection, source: str, target: str) -> Tuple[bool, Any]:
    """Copy result from one omniverse location to another one"""
    copy_result = await c.conn.copy(source, target, transaction_id="0")
    return True, copy_result


async def omni_list_and_subscribe_multiple(c, paths: List[str] = [], delay: float = 5) -> AsyncGenerator:
    """Wrapper around the omniverse connection list and subscribe function,
    where omniverse connection is passed as a parameter.

    Args:
        c: Omniverse connection
    """

    async def file_checker(p: str) -> Stat2Result:
        # check if file exists
        file_exists, file = await check_if_exists(c, p)
        # check if file exists, if not - recreate connection
        if not file_exists:
            logger.error(f"File does not exist: {p}")
            raise ConnectionError(f"File not found: {p} - likely connection error")

        return file

    async def gen() -> AsyncIterator[Stat2Result]:
        # create a list of tasks for listening file subscriptions
        while True:
            # get all the files from the list
            files = await asyncio.gather(*[file_checker(p) for p in paths])
            for f in files:
                yield f
            # wait for a bit before sending the next request
            await asyncio.sleep(delay)

    async for item in gen():
        yield item


# define a list2 function that works with multiple Nucleus versions
async def list2(conn: Connection, **kwargs) -> List2Response:
    """Function that filters applies the correct listing functionality depending on the Nucleus server version.

    Args:
        conn (Connection): Nucleus connection

    Yields:
        List2Response: response coming from the Nucleus server
    """

    # this functionality is supported only since Nucleus R14
    #  for older versions - InvalidParameters status will be thrown
    # remove_include_option = False
    # async for it in conn.list2(**kwargs):
    #     # account for older servers
    #     if it.status == StatusType.InvalidParameters:
    #         remove_include_option = True
    #         break
    #     yield it

    # if remove_include_option:
    #     del kwargs["include_option"]
    async for it in conn.list2(**kwargs):
        yield it


async def conn_list2_to_list(
    gen: AsyncGenerator[List2Response, None],
) -> List[List2ResponsePathEntry]:
    """Convert List of responses to a list of path entries

    Args:
        gen (AsyncGenerator[List2Response, None]): List of responses generator

    Returns:
        List[List2ResponsePathEntry]: list of path entries
    """
    res: List[List2ResponsePathEntry] = []
    async for folder in gen:
        if status_done(folder):
            break
        elif folder.entries is not None:
            res.extend(folder.entries)
        else:
            logger.warning(f"folder.entries is None: {folder}")
            break
    return res
