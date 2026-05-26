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
import argparse
import asyncio
import os

# local/proprietary modules
from search_utils import cache_utils as cu

parser = argparse.ArgumentParser()
parser.add_argument(
    "--host",
    type=str,
    default=os.getenv("ES_HOST", "localhost"),
    help="Path in Omniverse",
)
parser.add_argument("--port", type=int, default=int(os.getenv("ES_PORT", "9200")), help="local folder")
parser.add_argument(
    "--name",
    type=str,
    default=os.getenv("ES_NAME", "siglip2-embedding"),
    help="name of ES storage",
)


def main(args):
    async def verify_storage(es_cache, dry_run: bool = True):
        return await es_cache.actualize_storage(dry_run=dry_run)

    es_cache = cu.NestedMetaESCacheDict(host=args.host, port=args.port, name=args.name)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(verify_storage(es_cache))


if __name__ == "__main__":
    args = parser.parse_args()
    main(args)
