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

# standard modules
from omni.client import List2ResponsePathEntry, ServiceSubscribeListResponse

# local / proprietary modules
from ..data import PathType


def OmniClientPath_to_PathType(response: ServiceSubscribeListResponse) -> PathType:
    """Conversion from the new format of data to the previous one."""
    result = PathType.model_construct(status=response.status, ts=response.ts, event=response.get("event"))
    # if
    if hasattr(response, "entry") and response.entry is not None:
        result.uri = response.entry.get("path")
        result.etag = response.entry.get("etag")
        result.created_date_seconds = response.entry.get("created_timestamp")
        result.modified_date_seconds = response.entry.get("modified_timestamp")
        result.deleted_date_seconds = response.entry.get("deleted_timestamp")
        result.type = response.entry.get("path_type")
        for attr in [
            "size",
            "mounted",
            "created_by",
            "modified_by",
            "hash_type",
            "hash_value",
            "hash_bsize",
            "transaction_id",
            "acl",
            "empty",
            # "destination",
            # "locked_by",
            # "lock_time",
            # "lock_owner",
            # "lock_duration",
            # "lock_etag",
            "is_deleted",
            "deleted_by",
            # "deleted_date_seconds",
        ]:
            setattr(result, attr, response.entry.get(attr))

    return result


def List2Response_to_PathType(item: List2ResponsePathEntry) -> PathType:
    return PathType.model_construct(
        uri=item.path,
        type=item.path_type,
        acl=item.acl,
        created_date_seconds=item.created_timestamp,
        modified_date_seconds=item.modified_timestamp,
        created_by=item.created_by,
        modified_by=item.modified_by,
        mounted=item.mounted,
        size=item.size,
        empty=item.empty,
        is_deleted=item.get("is_deleted"),
        deleted_by=item.get("deleted_by"),
        deleted_date_seconds=item.get("deleted_timestamp"),
        hash_type=item.hash_type,
        hash_value=item.hash_value,
        hash_bsize=item.hash_bsize,
        etag=item.etag,
    )
