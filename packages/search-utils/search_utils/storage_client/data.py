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

from abc import ABC

# standard modules
from datetime import datetime
from enum import Enum
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    List,
    NewType,
    Optional,
    TypedDict,
    Union,
)

# third party modules
from pydantic import Field
from pydantic.config import ConfigDict
from pydantic.main import BaseModel

from ..hashing_utils import get_hash

# TODO: Remove after fixing imports in ngsearch
from .config import AvailableStorageClients  # noqa: F401

__all__ = ["AvailableStorageClients"]

RemoteFilePath = NewType("RemoteFilePath", str)
"""
Path of a remote file

E.g. "/file.usd" or "/Projects/DeepSearch/"
"""

RemoteFileUri = NewType("RemoteFileUri", str)
"""
A full URI of a remote file

E.g. "s3://deepsearch-test-bucket/file.usd" or "omniverse://rc-r15.ov.nvidia.com/Projects/DeepSearch/"
"""


LocalFilePath = NewType("LocalFilePath", str)
"""
Path of a local file

E.g. "C:\\some_file" or "/home/user/some_file"
"""


class SubscriptionSource(str, Enum):
    recursive_list = "recursive_list"
    subscription = "subscription"


class TagAction(str, Enum):
    add = "add"
    reset = "reset"
    set = "set"
    remove = "remove"


class FileTypeMapping(str, Enum):
    asset = "asset"
    folder = "folder"
    mount = "mount"
    unknown = "unknown"


class ACL(str, Enum):
    read = "read"
    write = "write"
    admin = "admin"


class CopyResult(TypedDict):
    pass


class ThumbnailLoadMode(str, Enum):
    one = "one"
    all = "all"


class ThumbnailItem(BaseModel):
    uri: RemoteFileUri = Field(description="Full asset URI")
    data: bytes = Field(description="Thumbnail data")
    etag: Optional[str] = Field(default=None, description="unique asset ID")


class VerifyBatchAccessResponse(BaseModel):
    uri: RemoteFileUri = Field(description="Full asset URI")
    path: Optional[RemoteFilePath] = Field(default=None, description="Remote asset path")
    exists: bool = Field(..., description="True if file exists on the server, False otherwise")
    acl: Optional[List[ACL]] = Field(default=None, description="User access permissions")
    meta: Optional[Any] = Field(
        default=None,
        description="Any additional asset information that may be required",
    )


class EventMapping(str, Enum):
    acl_change = "acl_change"
    delete = "delete"
    checkpoints_changed = "checkpoints_changed"
    create = "create"
    unknown = "unknown"


class PathType(BaseModel):
    """
    This class is used to store the information about the path of the asset.
    """

    uri: Optional[RemoteFileUri] = Field(default=None, description="Full asset URI")
    etag: Optional[str] = Field(default=None, description="unique asset ID")

    status: Optional[str] = Field(default=None, description="status of the operation")
    event: Optional[Union[EventMapping, str]] = Field(default=None, description="event type")
    type: Optional[str] = Field(default=None, description="type of the asset")
    ts: Optional[Dict[str, int]] = Field(default=None, description="server timestamp")
    transaction_id: Optional[Union[str, int]] = Field(default=None, description="transaction ID")
    acl: Optional[List[str]] = Field(default=None, description="ACL list")
    empty: Optional[Union[bool, str]] = Field(default=None, description="flag to show if the object is empty")
    mounted: Optional[Union[bool, str]] = Field(default=None, description="flag to show if the object is on the mount")
    size: Optional[int] = Field(default=None, description="Size of the object in bytes")

    created_by: Optional[str] = Field(default=None, description="user ID who created the object")
    created_date_seconds: Optional[Union[int, float]] = Field(default=None, description="creation time (seconds)")
    modified_by: Optional[str] = Field(default=None, description="user ID who last modified the object")
    modified_date_seconds: Optional[Union[int, float]] = Field(
        default=None, description="last modification time (seconds)"
    )
    hash_type: Optional[Union[str, List[str]]] = Field(default=None, description="type of hashing function")
    hash_value: Optional[str] = Field(default=None, description="hash value (can be None for files on mounts)")
    hash_bsize: Optional[int] = Field(default=None, description="Hash block size")

    is_deleted: Optional[bool] = Field(default=None, description="flag to show that a file was deleted")
    deleted_by: Optional[str] = Field(default=None, description="user ID who last deleted the asset")
    deleted_date_seconds: Optional[Union[int, float]] = Field(
        default=None, description="time when the object was last deleted"
    )
    source: Optional[Union[SubscriptionSource, str]] = Field(
        default=None,
        description="source where the object is coming from (resursive list or subscription)",
    )
    model_config = ConfigDict(extra="allow")

    @property
    def modified(self):
        if self.modified_date_seconds:
            return datetime.fromtimestamp(self.modified_date_seconds).strftime("%a %b %d %H:%M:%S %Y")
        return None

    def get_hash(self) -> str:
        if self.hash_value is None:
            return f"{self.uri}/{self.modified_date_seconds}"
        else:
            return self.hash_value

    def get_hashed_hash_value(self) -> str:
        return get_hash(self.get_hash())


class DataClassGetter(ABC):
    def __getitem__(self, key: str):
        return getattr(self, key)


class TagName(str):
    pass


class TagValue(str):
    pass


class SubscriptionArgs(BaseModel):
    arbitrary_types_allowed: ClassVar[bool] = True
    uri: str = Field(default=None, description="Path on the Storage backend")
    paths: List[str] = Field(default=[], description="List of paths")
    recursive: bool = Field(default=True, description="trigger to subscribe to events recursively")
    batch_size: int = Field(default=-1, description="process subscription elements in batches")
    list_type: Optional[str] = Field(default="asset", description="asset type")
    show_hidden: bool = Field(default=False, description="if True - show hidden items")
    delay: float = Field(default=None, description="delay for file check")
    subscription_ready: Optional[Any] = Field(
        default=None, description="trigger event to notify that subscription is ready"
    )
    connection_getter: Optional[Callable] = Field(default=None, description="connection getter")


class TagResults(BaseModel):
    tag: Optional[List[str]] = Field(default=None, description="list of tags")
    value: Optional[List[str]] = Field(default=None, description="list of tag values")
    namespace: Optional[List[str]] = Field(default=None, description="list of tag namespaces")
    path: Optional[str] = Field(default=None, description="path to which tags belong")
    op: Union[str, int] = Field(default=None, description="type of the operation that is applied")


class TagField(BaseModel):
    name: Optional[str] = Field(..., description="tag")
    value: Optional[str] = Field(default=None, description="tag value")
    tag_namespace: Optional[str] = Field(default=None, description="tag namespace")


class TagResultField(BaseModel):
    tags: List[TagField] = Field(..., description="list of tags")
    uri: Optional[str] = Field(..., description="path to which tags belong")
    op: Optional[Union[str, int]] = Field(default=None, description="tagging operation")


class TagType(str, Enum):
    user = "user"
    generated = "generated"
    excluded = "excluded"


class TagQueryResult(BaseModel):
    paths: List[str] = Field(..., description="query paths")
    tags: List[TagField] = Field(default=[], description="list of tags")
