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

DESCRIPTOR: _descriptor.FileDescriptor

class ListServicesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListServicesResponse(_message.Message):
    __slots__ = ("services",)
    SERVICES_FIELD_NUMBER: _ClassVar[int]
    services: _containers.RepeatedCompositeFieldContainer[ServiceEntry]
    def __init__(self, services: _Optional[_Iterable[_Union[ServiceEntry, _Mapping]]] = ...) -> None: ...

class ServiceEntry(_message.Message):
    __slots__ = ("service_name", "service_versions")
    SERVICE_NAME_FIELD_NUMBER: _ClassVar[int]
    SERVICE_VERSIONS_FIELD_NUMBER: _ClassVar[int]
    service_name: str
    service_versions: _containers.RepeatedScalarFieldContainer[str]
    def __init__(
        self, service_name: _Optional[str] = ..., service_versions: _Optional[_Iterable[str]] = ...
    ) -> None: ...

class ListTopLevelAddressesRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ListTopLevelAddressesResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[TopLevelAddressEntry]
    def __init__(self, items: _Optional[_Iterable[_Union[TopLevelAddressEntry, _Mapping]]] = ...) -> None: ...

class TopLevelAddressEntry(_message.Message):
    __slots__ = ("top_level_address",)
    TOP_LEVEL_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    top_level_address: str
    def __init__(self, top_level_address: _Optional[str] = ...) -> None: ...
