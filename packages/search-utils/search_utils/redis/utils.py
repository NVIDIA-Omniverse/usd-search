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
import os
from time import sleep
from typing import Optional

from redis import Redis
from redis.exceptions import RedisError

from ..log_utils import set_simple_logger

logger = logging.getLogger(__name__)


def redis_wait_ready(url: Optional[str] = os.getenv("REDIS_URL")) -> bool:
    if url is None:
        raise ValueError("REDIS_URL is not set")

    client = Redis.from_url(url)

    while True:
        try:
            client.ping()
            logger.info("Redis available at: %s", url)
            return True
        except RedisError as exc_info:
            logger.warning("Redis backend unavailable", exc_info=exc_info)
            sleep(1)
