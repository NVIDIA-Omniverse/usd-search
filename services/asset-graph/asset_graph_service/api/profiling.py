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

import datetime
import logging
import os
from typing import Callable

from asgi_correlation_id import correlation_id
from starlette.requests import Request

PROFILING_ENABLED = os.getenv("PROFILING_ENABLED", "False").lower() == "true"
PROFILE_ALL_REQUESTS = os.getenv("PROFILE_ALL_REQUESTS", "False").lower() == "true"

logger = logging.getLogger(__name__)


def get_profiling_middleware():
    if PROFILING_ENABLED:
        logger.info(
            "Profiling enabled. Set query param `profile=true` to profile a request or set the env variable `PROFILE_ALL_REQUESTS=True` to profile all requests"
        )
        from pyinstrument import Profiler
        from pyinstrument.renderers.html import HTMLRenderer
        from pyinstrument.renderers.speedscope import SpeedscopeRenderer

        async def profile_request(request: Request, call_next: Callable):
            """Profile the current request

            Taken from https://github.com/brouberol/5esheets/blob/main/dnd5esheets/middlewares.py

            """
            # if the `profile=true` HTTP query argument is passed, we profile the request
            if request.query_params.get("profile", False) or PROFILE_ALL_REQUESTS:
                # we profile the request along with all additional middlewares, by interrupting
                # the program every 1ms1 and records the entire stack at that point
                with Profiler(interval=0.001, async_mode="enabled") as profiler:
                    response = await call_next(request)

                with open(
                    f"profiler/profile_{correlation_id.get()}_{datetime.datetime.now().astimezone().isoformat()}.speedscope.json",
                    "w",
                ) as out:
                    out.write(profiler.output(renderer=SpeedscopeRenderer()))
                with open(
                    f"profiler/profile_{correlation_id.get()}_{datetime.datetime.now().astimezone().isoformat()}.html",
                    "w",
                ) as out:
                    out.write(profiler.output(renderer=HTMLRenderer()))
                return response

            # Proceed without profiling
            return await call_next(request)

        return profile_request
    else:
        logger.info("Profiling disabled. Set PROFILING_ENABLED=True to enable")

        async def profile_request_stub(request: Request, call_next: Callable):
            return await call_next(request)

        return profile_request_stub
