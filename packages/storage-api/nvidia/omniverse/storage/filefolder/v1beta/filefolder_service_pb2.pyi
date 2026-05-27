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

from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf.internal import containers as _containers
from nvidia.omniverse.storage.fileobject.v1beta import fileobject_pb2 as _fileobject_pb2

DESCRIPTOR: _descriptor.FileDescriptor

class ListRequest(_message.Message):
    __slots__ = ("folder",)
    FOLDER_FIELD_NUMBER: _ClassVar[int]
    folder: FolderAddress
    def __init__(self, folder: _Optional[_Union[FolderAddress, _Mapping]] = ...) -> None: ...

class ListResponse(_message.Message):
    __slots__ = ("subfolder_addresses", "sub_resource_addresses")
    SUBFOLDER_ADDRESSES_FIELD_NUMBER: _ClassVar[int]
    SUB_RESOURCE_ADDRESSES_FIELD_NUMBER: _ClassVar[int]
    subfolder_addresses: _containers.RepeatedCompositeFieldContainer[FolderAddress]
    sub_resource_addresses: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self,
        subfolder_addresses: _Optional[_Iterable[_Union[FolderAddress, _Mapping]]] = ...,
        sub_resource_addresses: _Optional[_Iterable[str]] = ...,
    ) -> None: ...

class ListStatRequest(_message.Message):
    __slots__ = ("folder",)
    FOLDER_FIELD_NUMBER: _ClassVar[int]
    folder: FolderAddress
    def __init__(self, folder: _Optional[_Union[FolderAddress, _Mapping]] = ...) -> None: ...

class ListStatResponse(_message.Message):
    __slots__ = ("subfolder_addresses", "entries")
    SUBFOLDER_ADDRESSES_FIELD_NUMBER: _ClassVar[int]
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    subfolder_addresses: _containers.RepeatedCompositeFieldContainer[FolderAddress]
    entries: _containers.RepeatedCompositeFieldContainer[ListItem]
    def __init__(
        self,
        subfolder_addresses: _Optional[_Iterable[_Union[FolderAddress, _Mapping]]] = ...,
        entries: _Optional[_Iterable[_Union[ListItem, _Mapping]]] = ...,
    ) -> None: ...

class DeleteFolderRequest(_message.Message):
    __slots__ = ("folder",)
    FOLDER_FIELD_NUMBER: _ClassVar[int]
    folder: FolderAddress
    def __init__(self, folder: _Optional[_Union[FolderAddress, _Mapping]] = ...) -> None: ...

class DeleteFolderResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListItem(_message.Message):
    __slots__ = ("resource_address", "resource_info")
    RESOURCE_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_INFO_FIELD_NUMBER: _ClassVar[int]
    resource_address: str
    resource_info: _fileobject_pb2.ResourceInfo
    def __init__(
        self,
        resource_address: _Optional[str] = ...,
        resource_info: _Optional[_Union[_fileobject_pb2.ResourceInfo, _Mapping]] = ...,
    ) -> None: ...

class FolderAddress(_message.Message):
    __slots__ = ("uri",)
    URI_FIELD_NUMBER: _ClassVar[int]
    uri: str
    def __init__(self, uri: _Optional[str] = ...) -> None: ...
