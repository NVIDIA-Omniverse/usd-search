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

from typing import List

from humanize import naturalsize
from tqdm.asyncio import tqdm_asyncio

from search_utils.datetime_utils import date_from_timestamp
from search_utils.storage_client import RemoteFileUri, StorageClient


async def ls(
    storage_client: StorageClient,
    path: str,
    show_hidden: bool = True,
    ignore_patterns: List[str] = [],
    long_listing_format: bool = False,
    verbose: bool = False,
) -> List[RemoteFileUri]:
    uri_list: List[RemoteFileUri] = []
    client: StorageClient
    async with storage_client.connection_context() as client:
        if not storage_client.is_valid_uri(path):
            path = storage_client.get_uri_from_path(path)
        async for item in tqdm_asyncio(
            client.list_items(
                uri_list=[path],
                show_hidden=show_hidden,
                ignore_patterns=ignore_patterns,
            ),
            desc="Listing items",
            unit="items",
        ):
            output = ""
            if long_listing_format:
                output = f"{date_from_timestamp(item.created_date_seconds)} {naturalsize(item.size)} \t"

            output += item.uri
            if verbose:
                print(output)
            uri_list.append(item.uri)

    print(f"Found {len(uri_list)} items")

    return uri_list
