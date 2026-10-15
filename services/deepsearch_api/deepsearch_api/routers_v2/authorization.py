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

import logging
from typing import Annotated

from deepsearch_api.routers_v2 import dependencies
from deepsearch_api.routers_v2.models import VerifyAccessRequest
from deepsearch_api.routers_v2.service import check_acl
from fastapi import APIRouter, Depends

from search_utils.storage_client import StorageClient
from search_utils.url_mapping import to_public_url_list

router = APIRouter(
    prefix="/authorization",
    tags=["v2_authorization"],
)

logger = logging.getLogger(__name__)


@router.post(
    "/verify_access",
    tags=["v2_authorization"],
)
async def verify_access(
    storage_client: Annotated[StorageClient, Depends(dependencies.storage_client)],
    request: VerifyAccessRequest,
) -> list[str]:
    """
    For a given list of URLs, check if the user has access to them and return the list of URLs that the user has access to.
    """
    # The reply is a subset of the request, and a caller can only use it as one if
    # the URLs come back spelled the way they were sent. `request.urls` was
    # normalized to the internal form on the way in, so translate back out — the
    # body is a bare list, which the field-name-driven document rewriter cannot see
    # into.
    return to_public_url_list(await check_acl(request.urls, storage_client))
