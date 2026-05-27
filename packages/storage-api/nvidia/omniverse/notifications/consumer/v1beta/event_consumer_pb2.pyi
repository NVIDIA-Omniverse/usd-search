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

import datetime
from collections.abc import Iterable as _Iterable
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar
from typing import Optional as _Optional
from typing import Union as _Union

from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper

DESCRIPTOR: _descriptor.FileDescriptor

class ConsumeDurableEventsResponse(_message.Message):
    __slots__ = ("events",)
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    events: _containers.RepeatedCompositeFieldContainer[Event]
    def __init__(self, events: _Optional[_Iterable[_Union[Event, _Mapping]]] = ...) -> None: ...

class ConsumeNonDurableEventsResponse(_message.Message):
    __slots__ = ("events", "reconnect_token")
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    RECONNECT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    events: _containers.RepeatedCompositeFieldContainer[Event]
    reconnect_token: str
    def __init__(
        self,
        events: _Optional[_Iterable[_Union[Event, _Mapping]]] = ...,
        reconnect_token: _Optional[str] = ...,
    ) -> None: ...

class ConsumeDurableEventsRequest(_message.Message):
    __slots__ = ("queue_id",)
    QUEUE_ID_FIELD_NUMBER: _ClassVar[int]
    queue_id: str
    def __init__(self, queue_id: _Optional[str] = ...) -> None: ...

class ConsumeNonDurableEventsRequest(_message.Message):
    __slots__ = ("filter_groups", "reconnect_token", "previous_filter_groups")
    FILTER_GROUPS_FIELD_NUMBER: _ClassVar[int]
    RECONNECT_TOKEN_FIELD_NUMBER: _ClassVar[int]
    PREVIOUS_FILTER_GROUPS_FIELD_NUMBER: _ClassVar[int]
    filter_groups: _containers.RepeatedCompositeFieldContainer[FilterGroup]
    reconnect_token: str
    previous_filter_groups: _containers.RepeatedCompositeFieldContainer[FilterGroup]
    def __init__(
        self,
        filter_groups: _Optional[_Iterable[_Union[FilterGroup, _Mapping]]] = ...,
        reconnect_token: _Optional[str] = ...,
        previous_filter_groups: _Optional[_Iterable[_Union[FilterGroup, _Mapping]]] = ...,
    ) -> None: ...

class CreateDurableQueueRequest(_message.Message):
    __slots__ = ("filter_groups",)
    FILTER_GROUPS_FIELD_NUMBER: _ClassVar[int]
    filter_groups: _containers.RepeatedCompositeFieldContainer[FilterGroup]
    def __init__(self, filter_groups: _Optional[_Iterable[_Union[FilterGroup, _Mapping]]] = ...) -> None: ...

class CreateDurableQueueResponse(_message.Message):
    __slots__ = ("queue_id",)
    QUEUE_ID_FIELD_NUMBER: _ClassVar[int]
    queue_id: str
    def __init__(self, queue_id: _Optional[str] = ...) -> None: ...

class DeleteDurableQueueRequest(_message.Message):
    __slots__ = ("queue_id",)
    QUEUE_ID_FIELD_NUMBER: _ClassVar[int]
    queue_id: str
    def __init__(self, queue_id: _Optional[str] = ...) -> None: ...

class UpdateDurableQueueRequest(_message.Message):
    __slots__ = ("queue_id", "current_filter_groups", "new_filter_groups")
    QUEUE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_FILTER_GROUPS_FIELD_NUMBER: _ClassVar[int]
    NEW_FILTER_GROUPS_FIELD_NUMBER: _ClassVar[int]
    queue_id: str
    current_filter_groups: _containers.RepeatedCompositeFieldContainer[FilterGroup]
    new_filter_groups: _containers.RepeatedCompositeFieldContainer[FilterGroup]
    def __init__(
        self,
        queue_id: _Optional[str] = ...,
        current_filter_groups: _Optional[_Iterable[_Union[FilterGroup, _Mapping]]] = ...,
        new_filter_groups: _Optional[_Iterable[_Union[FilterGroup, _Mapping]]] = ...,
    ) -> None: ...

class DeleteDurableQueueResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UpdateDurableQueueResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Event(_message.Message):
    __slots__ = (
        "event_type",
        "principal_identity",
        "occurred_at",
        "published_at",
        "message",
    )
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    PRINCIPAL_IDENTITY_FIELD_NUMBER: _ClassVar[int]
    OCCURRED_AT_FIELD_NUMBER: _ClassVar[int]
    PUBLISHED_AT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    event_type: str
    principal_identity: str
    occurred_at: _timestamp_pb2.Timestamp
    published_at: _timestamp_pb2.Timestamp
    message: _struct_pb2.Struct
    def __init__(
        self,
        event_type: _Optional[str] = ...,
        principal_identity: _Optional[str] = ...,
        occurred_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...,
        published_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...,
        message: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...,
    ) -> None: ...

class FilterGroup(_message.Message):
    __slots__ = ("event_type", "filters")
    EVENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    event_type: str
    filters: _containers.RepeatedCompositeFieldContainer[ResourceFilter]
    def __init__(
        self,
        event_type: _Optional[str] = ...,
        filters: _Optional[_Iterable[_Union[ResourceFilter, _Mapping]]] = ...,
    ) -> None: ...

class ResourceFilter(_message.Message):
    __slots__ = ("filter_type", "resource_id")

    class FilterType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        FILTER_TYPE_UNSPECIFIED: _ClassVar[ResourceFilter.FilterType]
        FILTER_TYPE_EQ: _ClassVar[ResourceFilter.FilterType]
        FILTER_TYPE_STARTS_WITH_LAZY: _ClassVar[ResourceFilter.FilterType]
        FILTER_TYPE_STARTS_WITH_GREEDY: _ClassVar[ResourceFilter.FilterType]

    FILTER_TYPE_UNSPECIFIED: ResourceFilter.FilterType
    FILTER_TYPE_EQ: ResourceFilter.FilterType
    FILTER_TYPE_STARTS_WITH_LAZY: ResourceFilter.FilterType
    FILTER_TYPE_STARTS_WITH_GREEDY: ResourceFilter.FilterType
    FILTER_TYPE_FIELD_NUMBER: _ClassVar[int]
    RESOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    filter_type: ResourceFilter.FilterType
    resource_id: str
    def __init__(
        self,
        filter_type: _Optional[_Union[ResourceFilter.FilterType, str]] = ...,
        resource_id: _Optional[str] = ...,
    ) -> None: ...
