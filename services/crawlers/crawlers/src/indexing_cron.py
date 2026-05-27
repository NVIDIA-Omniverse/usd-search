#!/usr/bin/env python3.6
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

from .base import CrawlerServiceCron
from .config import DeepSearchCrawlerConfig, DeepSearchIndexingConfig


class IndexingServiceCron(CrawlerServiceCron):
    def set_crawler_config(self, crawler_config: Optional[DeepSearchCrawlerConfig]) -> DeepSearchCrawlerConfig:
        if crawler_config is None:
            return DeepSearchIndexingConfig()
        return crawler_config


def main() -> None:
    service = IndexingServiceCron()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(service.run())


if __name__ == "__main__":
    main()
