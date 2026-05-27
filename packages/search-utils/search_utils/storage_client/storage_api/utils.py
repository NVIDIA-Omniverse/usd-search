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
import urllib.parse
from contextlib import asynccontextmanager
from io import SEEK_CUR, SEEK_END, SEEK_SET, BytesIO
from typing import (
    IO,
    AsyncGenerator,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Optional,
    Protocol,
    Tuple,
)

import aiohttp
from grpc import StatusCode
from grpc.aio import AioRpcError, StreamStreamCall
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_pb2 import Chunk, Header
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_service_pb2 import (
    CompletedUploadPart,
    CompleteMultipartUploadRequest,
    CompleteRedirectUploadRequest,
    CreateMultipartUploadResponse,
    DownloadPreference,
    FetchWriteTypeInfoRequest,
    FetchWriteTypeInfoResponse,
    ReadFromAddressRequest,
    ReadFromAddressResponse,
    UploadMethod,
    UploadPartRequest,
    UploadPartResponse,
    UploadPreference,
    WriteParameters,
    WriteRedirectProperties,
    WriteRequest,
    WriteResponse,
)
from nvidia.omniverse.storage.fileobject.v1alpha.fileobject_service_pb2_grpc import (
    FileObjectServiceStub,
)

logger = logging.getLogger(__name__)


MAX_INLINE_CHUNK_SIZE = 3 * (2**20)


class SupportsRead(Protocol):
    def read(self, length: int = ..., /) -> bytes: ...


class IOSlice:
    """A read-only slice of an underlying file object."""

    def __init__(self, inner: IO[bytes], first: int, last: int):
        self._inner = inner
        self._first = first
        self._last = last
        self._pos = first

    def tell(self) -> int:
        return self._pos - self._first

    def seek(self, pos: int, whence: int = SEEK_SET) -> int:
        if whence == SEEK_SET:
            next_pos = self._first + pos
        elif whence == SEEK_CUR:
            next_pos = self._pos + pos
        elif whence == SEEK_END:
            next_pos = self._last + pos
        else:
            raise ValueError("Unsupported seek method.")

        if next_pos > self._last or next_pos < self._first:
            raise ValueError("Offset is out of bounds.")

        self._pos = next_pos

        return next_pos - self._first

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        self._inner.seek(self._pos, SEEK_SET)
        if n < 0:
            data = self._inner.read(self._last - self._pos)
        else:
            data = self._inner.read(min(self._last - self._pos, n))

        self._pos += len(data)

        return data


def quote_uri(uri: str) -> str:
    """
    Quote the URI to be a valid Storage API URI.
    """
    return urllib.parse.quote(uri, safe=":/")


def unquote_uri(uri: str) -> str:
    """
    Unquote the URI to be a valid Storage API URI.
    """
    return urllib.parse.unquote(uri)


async def download(
    stub: FileObjectServiceStub,
    resource_address: str,
    download_preference: DownloadPreference,
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> bytearray:
    try:
        data = bytearray()
        reply: ReadFromAddressResponse
        async for reply in stub.ReadFromAddress(
            ReadFromAddressRequest(
                resource_address=resource_address,
                download_preference=download_preference,
            ),
            metadata=metadata,
        ):
            if reply.HasField("resource_info"):
                logger.debug(
                    f"Found {resource_address}, downloading {reply.resource_info.metadata.data_object_size} bytes"
                )
            elif reply.HasField("chunk"):
                data += reply.chunk.chunk
            elif reply.HasField("redirect"):
                async with aiohttp.ClientSession() as session:
                    async with session.get(reply.redirect.redirect_target_url) as redirected_response:
                        async for chunk in redirected_response.content:
                            data += chunk
                logger.debug("Download finished")
            else:
                raise Exception(f"Unexpected reply {reply}")
        logger.debug("Download finished")
        return data
    except AioRpcError as e:
        logger.error(f"Failure to download {resource_address}: {str(e)}")
        raise e from e


# start example
async def upload(
    stub: FileObjectServiceStub,
    address: str,
    upload_preference: str | None,
    content: IO[bytes],
    metadata: Optional[List[Tuple[str, str]]] = None,
):
    """Upload the contents of a file object at the specified address."""
    if metadata is None:
        metadata = []

    content_length = get_content_length(content)
    if upload_preference:
        chosen_upload_preference = _string_to_upload_preference(upload_preference)
    else:
        chosen_upload_preference = await _get_upload_preference(stub, address, content_length, metadata)

    request_messages: asyncio.Queue[WriteRequest | None]
    async with _write_message_queue() as (request_messages, request_messages_iterator):
        await request_messages.put(
            WriteRequest(
                params=WriteParameters(
                    destination_resource_address=address,
                    data_object_size=content_length,
                    upload_preference=chosen_upload_preference,
                ),
            ),
        )

        write_responses: StreamStreamCall[WriteRequest, WriteResponse] = stub.Write(
            request_messages_iterator, metadata=metadata
        )

        write_responses_iterator = aiter(write_responses)

        # Get the first response using async for
        flow_control_message = await anext(write_responses_iterator)
        # A service may immediately respond with a "resource info" message, meaning that a 0-byte object write has
        # been performed immediately without the need for any further actions on the client end.
        if flow_control_message.HasField("resource_info"):
            return

        # If we receive a "write chunks accepted" message, stream the chunks and finally await for a "resource info"
        # response message.
        if flow_control_message.HasField("write_chunks_accepted"):
            for chunk in _slice_content(content):
                await request_messages.put(WriteRequest(chunk=chunk))

            # End chunk transmission.
            await request_messages.put(None)

            # Get the final resource info response
            async for resource_info_response in write_responses_iterator:
                if not resource_info_response.HasField("resource_info"):
                    raise Exception("Resource info message is expected.")

        # Write redirect and multipart upload methods don't operate over the same stream of Write requests
        if flow_control_message.HasField("write_redirect"):
            await _write_via_redirect(stub, address, flow_control_message.write_redirect, content)
            return

        if flow_control_message.HasField("multipart_upload"):
            await _write_via_multipart(stub, address, flow_control_message.multipart_upload, content)
            return

        # raise Exception("Unexpected flow control message.")


# end example


def _slice_content(content: IO[bytes], max_inline_chunk_size: int = MAX_INLINE_CHUNK_SIZE) -> Iterable[Chunk]:
    """Slice the contents of a file into a series of Chunk messages."""

    while True:
        chunk = content.read(max_inline_chunk_size)
        if not chunk:
            break

        yield Chunk(chunk=chunk)


@asynccontextmanager
async def _write_message_queue(
    max_messages: int = 5,
) -> AsyncGenerator[tuple[asyncio.Queue[WriteRequest | None], AsyncIterator[WriteRequest]], None]:
    # Limit the number of messages in the queue so we don't accidentally load the whole file into memory.
    request_messages: asyncio.Queue[WriteRequest | None] = asyncio.Queue(max_messages)

    async def yield_request_messages() -> AsyncIterator[WriteRequest]:
        while True:
            message = await request_messages.get()
            if message is None:
                break
            yield message

    try:
        yield request_messages, yield_request_messages()
    finally:
        await request_messages.put(None)


# start redirect write example
async def _write_via_redirect(
    service: FileObjectServiceStub,
    address: str,
    parameters: WriteRedirectProperties,
    content: IO[bytes],
):
    async with aiohttp.ClientSession() as session:
        async with session.request(
            method=_upload_method_to_string(parameters.method),
            url=parameters.redirect_target_url,
            data=content,
            headers={header.name: header.value for header in parameters.additional_headers},
        ) as response:
            response.raise_for_status()

            # Optionally, obtain the resource information of the just uploaded file object
            # This is not required to store the data, but helpful to keep the reference to the stored object.
            requested_headers = set(parameters.completion_header_names)

    # Optionally, obtain the resource information of the just uploaded file object
    # This is not required to store the data, but helpful to keep the reference to the stored object.
    requested_headers = set(parameters.completion_header_names)
    await service.CompleteRedirectUpload(
        CompleteRedirectUploadRequest(
            destination_resource_address=address,
            additional_headers=[
                Header(name=x, value=response.headers[x])
                for x in filter(lambda key: key in requested_headers, response.headers.keys())
            ],
        )
    )


# end redirect write example


# start multipart write example
async def _write_via_multipart(
    stub: FileObjectServiceStub,
    address: str,
    parameters: CreateMultipartUploadResponse,
    content: IO[bytes],
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> None:
    # Build a list of redirect URLs to upload the parts to. The first we got from the CreateMultipartUploadResponse
    redirects = [parameters.first_part_write_redirect]

    # Calculate the number of parts, and retrieve the pre-signed URLs from the service to use for individual part upload
    total_part_count, part_size, content_length = part_count_for_multipart_upload(
        content, parameters.minimum_size_per_part, parameters.maximum_size_per_part
    )
    if total_part_count > 1:
        response: UploadPartResponse = await stub.UploadPart(
            UploadPartRequest(
                upload_id=parameters.upload_id,
                destination_resource_address=address,
                part_number=1,  # Part number 0 has already been delivered by the first CreateMultipartUploadReponse
                part_count=total_part_count - 1,
            ),
            metadata=metadata,
        )
        redirects.extend(response.part_write_redirects)

    completed_parts = []
    for part_number, part in enumerate(
        split_contents_for_multipart_upload(
            content,
            min_part_size=parameters.minimum_size_per_part,
            max_part_size=parameters.maximum_size_per_part,
            max_parts=parameters.maximum_parts_number,
        ),
        metadata=metadata,
    ):
        completed_parts.append(await _write_part(redirects[part_number], part_number, part, metadata))

    stub.CompleteMultipartUpload(
        CompleteMultipartUploadRequest(
            upload_id=parameters.upload_id,
            destination_resource_address=address,
            parts=completed_parts,
        ),
        metadata=metadata,
    )


async def _write_part(
    redirect: WriteRedirectProperties,
    part: int,
    content: SupportsRead,
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> CompletedUploadPart:
    return CompletedUploadPart(
        part_number=part,
        headers=[
            Header(name=name, value=value)
            for name, value in await upload_part(
                url=redirect.redirect_target_url,
                method=_upload_method_to_string(redirect.method),
                upload_headers=dict([(header.name, header.value) for header in redirect.additional_headers]),
                return_headers=[name for name in redirect.completion_header_names],
                content=content,
                metadata=metadata,
            )
        ],
    )


async def upload_part(
    url: str,
    method: str,
    content: SupportsRead,
    upload_headers: Dict[str, str],
    return_headers: list[str],
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> list[tuple[str, str]]:
    """Upload a part returning selected response headers."""

    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, data=BytesIO(content.read()), headers=upload_headers) as response:
            response.raise_for_status()
            return [(header, response.headers[header]) for header in return_headers]


async def _get_upload_preference(
    stub: FileObjectServiceStub,
    resource_address: str,
    size: int,
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> UploadPreference:
    """
    Get upload preference for a given resource address and size.
    """
    if metadata is None:
        metadata = []

    response: FetchWriteTypeInfoResponse = await stub.FetchWriteTypeInfo(
        FetchWriteTypeInfoRequest(destination_resource_address=resource_address),
        metadata=metadata,
    )

    for interval in response.write_type_intervals:
        if interval.minimum_data_object_size and interval.minimum_data_object_size > size:
            continue

        if interval.maximum_data_object_size and interval.maximum_data_object_size < size:
            continue

        return interval.preferred_upload_method

    return UploadPreference.UPLOAD_PREFERENCE_UNSPECIFIED


def _string_to_upload_preference(value: str | None) -> UploadPreference:
    """
    Convert string to UploadPreference.
    """
    if not value:
        return UploadPreference.UPLOAD_PREFERENCE_UNSPECIFIED
    if value == "body":
        return UploadPreference.UPLOAD_PREFERENCE_BODY
    if value == "redirect":
        return UploadPreference.UPLOAD_PREFERENCE_REDIRECT
    if value == "multipart":
        return UploadPreference.UPLOAD_PREFERENCE_MULTIPART

    raise ValueError(f"Unknown upload preference {value!r}.")


def _upload_method_to_string(value: UploadMethod) -> str:
    """
    Convert UploadMethod to string.
    """
    if value == UploadMethod.UPLOAD_METHOD_POST:
        return "POST"
    elif value == UploadMethod.UPLOAD_METHOD_PUT:
        return "PUT"
    raise ValueError(f"Unsupported upload method {value!r}.")


def get_content_length(content: IO[bytes]) -> int:
    """Return the length of a file content."""

    first_pos = content.tell()
    content.seek(0, SEEK_END)
    last_pos = content.tell()
    content.seek(first_pos)

    return last_pos - first_pos


def part_count_for_multipart_upload(
    content: IO[bytes],
    min_part_size: int | None,
    max_part_size: int | None,
) -> tuple[int, int, int]:
    content_length = get_content_length(content)
    part_size = _get_part_size(content_length, min_part_size, max_part_size)
    return content_length // part_size, part_size, content_length


def _get_part_size(content_length: int, min_part_size: int | None, max_part_size: int | None) -> int:
    if max_part_size:
        if min_part_size:
            if min_part_size * 2 > max_part_size:
                raise Exception("The maximum size of a part is expected to be at least twice as large as the minimum.")

            return max(min_part_size, content_length // 2)
        else:
            return min(max_part_size // 2, content_length // 2)
    else:
        if min_part_size:
            return max(min_part_size, content_length // 2)
        else:
            return content_length // 2


def split_contents_for_multipart_upload(
    content: IO[bytes],
    min_part_size: int | None,
    max_part_size: int | None,
    max_parts: int | None,
) -> Iterable[SupportsRead]:
    """Split contents of a single file into multiple chunks, fitting the multipart upload constraints."""

    parts, part_size, content_length = part_count_for_multipart_upload(content, min_part_size, max_part_size)
    if max_parts and parts > max_parts:
        raise Exception("The maximum number of parts exceeded.")

    extra = content_length % part_size
    extra_per_part = (extra + parts - 1) // parts

    first = 0
    for _ in range(parts):
        last = first + part_size
        if extra:
            current_part_extra = min(extra, extra_per_part)
            last += current_part_extra
            extra -= current_part_extra

        yield IOSlice(content, first, last)

        first = last

    assert last == content_length


async def check_connection_alive(
    stub: FileObjectServiceStub,
    timeout: float = 5.0,
    metadata: Optional[List[Tuple[str, str]]] = None,
) -> bool:
    """Check if the gRPC connection is alive by making a simple RPC call.

    Args:
        stub: The gRPC service stub to check
        timeout: Timeout in seconds for the connection check

    Returns:
        bool: True if connection is alive, False otherwise
    """
    if metadata is None:
        metadata = []

    try:
        # Use FetchWriteTypeInfo as a lightweight RPC call to check connection
        # This is a good choice because:
        # 1. It's a simple unary call (not streaming)
        # 2. It's part of the core service
        # 3. It's lightweight and doesn't require any complex parameters
        await asyncio.wait_for(
            stub.FetchWriteTypeInfo(
                FetchWriteTypeInfoRequest(destination_resource_address="dummy"),
                metadata=metadata,
            ),
            timeout=timeout,
        )
        return True
    except AioRpcError as e:
        if e.code() in (StatusCode.UNAVAILABLE, StatusCode.DEADLINE_EXCEEDED):
            logger.warning(f"Connection check failed: {e.code()}")
            return False
        # For other RPC errors, we might want to log but still consider the connection alive
        # since the server responded (even if with an error)
        logger.warning(f"Connection check got unexpected error: {e.code()}")
        return True
    except asyncio.TimeoutError:
        logger.warning("Connection check timed out")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during connection check: {str(e)}")
        return False
