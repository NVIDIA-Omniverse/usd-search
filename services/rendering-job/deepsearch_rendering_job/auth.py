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

from typing import Optional

from authlib.integrations.httpx_client import AsyncOAuth2Client

from .models import Authentication


async def get_openid_token(auth: Authentication, token: Optional[str] = None) -> Optional[str]:
    if auth.storage_api_openid_client_id is not None and auth.storage_api_openid_client_secret is not None:
        client = AsyncOAuth2Client(
            client_id=auth.storage_api_openid_client_id,
            client_secret=auth.storage_api_openid_client_secret,
            scope=auth.storage_api_openid_scope,
            token_endpoint=auth.storage_api_openid_token_url,
            grant_type=auth.storage_api_openid_grant_type,
        )
        if token is None:
            token = await client.fetch_token()
        else:
            token = await client.ensure_active_token(token)
        return token["access_token"]
    return None
