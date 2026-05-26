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

import fire
from deepsearch_rendering_job.models import RenderingRequest
from deepsearch_rendering_job.render import batch_rendering

SENTRY_DSN = os.getenv("SENTRY_DSN")

if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
    )


def main(*args: str) -> None:
    if len(args) > 0:
        request = RenderingRequest(url_list=args)
    else:
        request = RenderingRequest()

    loop = asyncio.get_event_loop()
    # get asset data
    loop.run_until_complete(batch_rendering(request=request))


if __name__ == "__main__":
    fire.Fire(main)
