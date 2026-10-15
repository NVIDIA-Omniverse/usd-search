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
from typing import Annotated

# third party modules
from fastapi import APIRouter, Request
from fastapi.params import Query

# local / proprietary modules
from search_utils.storage_client import StorageClient
from search_utils.storage_client.s3.client import S3StorageClient

from .models import StorageBackendInfo, StorageBackendItemInfo
from .utils import default_on_exception, get_storage_backend_type

router = APIRouter(prefix="/backend")


@router.get(
    "/storage",
    tags=["Storage Backend"],
    response_model=StorageBackendInfo,
    response_model_exclude_none=True,
)
async def get_storage_backend_info(
    request: Request,
    check_availability: Annotated[bool, Query(description="Check if storage backend is available")] = False,
) -> StorageBackendInfo:
    """Display some information about the storage backend(s), to which the USD Search API instance is connected to.

    A single Storage API deployment can serve several buckets / namespace roots. These are discovered via
    ``ListTopLevelAddresses`` and reported as one entry per root; backends that expose a single root (or a
    Storage API server without discovery support) report their configured ``base_uri``. When the Storage
    API backend's ``allowed_top_level_addresses`` is configured, only that subset is reported.
    """
    storage_client: StorageClient = request.app.storage_client

    backend_type = get_storage_backend_type(storage_client)
    s3_endpoint_url = storage_client.config.aws_endpoint_url if isinstance(storage_client, S3StorageClient) else None
    available = (
        await default_on_exception(storage_client.check_connection(), default=False) if check_availability else None
    )

    # Resolve the namespace roots (buckets). Falls back to base_uri when discovery is unavailable.
    addresses = await default_on_exception(storage_client.list_top_level_addresses(), default=None)
    if not addresses:
        addresses = [storage_client.base_uri]

    return StorageBackendInfo(
        backends={
            address: StorageBackendItemInfo(
                storage_backend_type=backend_type,
                base_url=address,
                available=available,
                s3_endpoint_url=s3_endpoint_url,
            )
            for address in addresses
            if address is not None
        }
    )
