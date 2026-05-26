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
from datetime import datetime
from typing import Tuple

from search_utils.storage_client import FileTypeMapping, PathType, RemoteFilePath


async def path_type_from_s3_object_summary(object_summary) -> PathType:
    try:
        object_owner = await object_summary.owner
    except AttributeError:
        object_owner = None

    response: Tuple[datetime, str, str, int] = await asyncio.gather(
        object_summary.last_modified,
        object_summary.e_tag,
        object_summary.checksum_algorithm,
        object_summary.size,
    )

    last_modified, e_tag, checksum_algorithm, size = response
    created_by = object_owner["ID"] if object_owner is not None else None

    object_path: RemoteFilePath = object_summary.key
    # NOTE: this fix is required for S3Proxy that returns keys with `/``
    if object_path.startswith("/"):
        object_path = object_path[1:]

    return PathType.model_construct(
        uri=f"s3://{object_summary.bucket_name}/{object_path}",
        etag=e_tag,
        hash_value=e_tag,
        hash_type=checksum_algorithm,
        type=FileTypeMapping.asset,
        size=size,
        modified_date_seconds=last_modified.timestamp(),
        created_date_seconds=last_modified.timestamp(),
        created_by=created_by,
        modified_by=created_by,
    )
