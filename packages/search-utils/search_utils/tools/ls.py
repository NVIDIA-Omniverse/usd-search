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
from typing import List, Optional

from fire import Fire
from humanize import naturalsize

from ..datetime_utils import date_from_timestamp
from ..storage_client import (
    AvailableStorageClients,
    RemoteFileUri,
    StorageClient,
    get_client,
)
from ..storage_client.config import StorageConfig


async def ls(
    storage_client: StorageClient,
    path: str,
    show_hidden: bool = True,
    ignore_patterns: List[str] = [],
    verbose: bool = False,
) -> List[RemoteFileUri]:
    uri_list: List[RemoteFileUri] = []
    client: StorageClient
    async with storage_client.connection_context() as client:
        async for item in client.list_items(
            uri_list=[storage_client.get_uri_from_path(path)],
            show_hidden=show_hidden,
            ignore_patterns=ignore_patterns,
        ):
            output = ""
            if verbose:
                output = f"{date_from_timestamp(item.created_date_seconds)} {naturalsize(item.size)} \t"

            output += item.uri
            print(output)
            uri_list.append(item.uri)

    return uri_list


def main(
    path: str,
    client_type: Optional[AvailableStorageClients] = None,
    long_listing_format: bool = False,
) -> None:
    if client_type is None:
        client_type = StorageConfig().storage_backend_type

    storage_client: StorageClient = get_client(client_type=client_type)

    asyncio.run(ls(storage_client=storage_client, path=path, verbose=long_listing_format))


if __name__ == "__main__":
    Fire(main)
