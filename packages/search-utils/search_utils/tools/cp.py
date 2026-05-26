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
from typing import List, Optional

from fire import Fire
from tqdm.asyncio import tqdm as async_tqdm

from ..storage_client import (
    AvailableStorageClients,
    RemoteFileUri,
    StorageClient,
    get_client,
)
from ..storage_client.config import StorageConfig


async def cp(
    src_storage_client: StorageClient,
    dst_storage_client: StorageClient,
    src_path: str,
    dst_path: str,
    show_hidden: bool = True,
    ignore_patterns: List[str] = [],
    verbose: bool = False,
    dry_run: bool = False,
) -> List[RemoteFileUri]:
    src_client: StorageClient
    dst_client: StorageClient
    async with (
        src_storage_client.connection_context() as src_client,
        dst_storage_client.connection_context() as dst_client,
    ):
        async for item in async_tqdm(
            src_client.list_items(
                uri_list=[src_storage_client.get_uri_from_path(src_path)],
                show_hidden=show_hidden,
                ignore_patterns=ignore_patterns,
            ),
            desc="Copying data",
        ):

            if item.uri is not None:
                src_item_path = src_client.get_path_from_uri(item.uri)

                if src_path != "/":
                    src_item_path = src_item_path.replace(src_path, "")

                dst_item_path = os.path.join(dst_path.rstrip("/") + "/", src_item_path.lstrip("/"))
                dst_uri = dst_client.get_uri_from_path(dst_item_path)

                if verbose:
                    print(f"{item.uri} -> {dst_uri}")

                exists, _ = await dst_client.check_if_exists(dst_uri)
                if exists:
                    if verbose:
                        print(f"Skipping {dst_uri} because it already exists")
                    continue
                if verbose:
                    print(f"{item.uri} -> {dst_uri}")
                if not dry_run:
                    content = await src_client.download_file_content(uri=item.uri)
                    await dst_client.upload_items_content(item_dict={dst_uri: content})


def main(
    src_path: str,
    dst_path: str,
    src_client_type: Optional[AvailableStorageClients] = None,
    dst_client_type: Optional[AvailableStorageClients] = None,
    show_hidden: bool = True,
    ignore_patterns: List[str] = [],
    verbose: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Copy data from one storage to another.

    Args:
        src_path: Path to the source data.
        dst_path: Path to the destination data.
        src_client_type: Type of the source storage client.
        dst_client_type: Type of the destination storage client.
        show_hidden: Whether to show hidden files.
        ignore_patterns: Patterns to ignore.
        verbose: Whether to print verbose output.
        dry_run: Whether to dry run the copy.
    """

    if src_client_type is None:
        src_client_type = StorageConfig().storage_backend_type
    if dst_client_type is None:
        dst_client_type = StorageConfig().storage_backend_type

    src_storage_client: StorageClient = get_client(client_type=src_client_type)
    dst_storage_client: StorageClient = get_client(client_type=dst_client_type)

    asyncio.run(
        cp(
            src_storage_client=src_storage_client,
            dst_storage_client=dst_storage_client,
            src_path=src_path,
            dst_path=dst_path,
            show_hidden=show_hidden,
            ignore_patterns=ignore_patterns,
            verbose=verbose,
            dry_run=dry_run,
        )
    )


if __name__ == "__main__":
    Fire(main)
