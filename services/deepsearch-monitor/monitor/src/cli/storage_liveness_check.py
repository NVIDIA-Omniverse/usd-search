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
from typing import Optional

from storage.src.client import NGSearchStorageClient
from storage.src.services.config import NGSearchStorageSearchBackendConfig

from .. import logger


async def check_storage_readiness(
    search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
) -> True:
    while True:
        try:
            async with await asyncio.wait_for(
                NGSearchStorageClient.get_service(search_backend_config=search_backend_config),
                timeout=30,
            ) as client:
                response = await client.readyz()
                if response.ready is True:
                    return True
        except Exception as exc_info:
            logger.exception("Connection to Search Backend failed", exc_info=exc_info)
        finally:
            logger.warning("Search Backend unavailable")
            await asyncio.sleep(2)


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(check_storage_readiness())
