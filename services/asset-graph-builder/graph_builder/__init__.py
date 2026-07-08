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
import logging.config
import os
from pathlib import Path
from typing import Any, Dict

import yaml

bin_path = Path(__file__).parent

logger = logging.getLogger(__name__)


def get_logging_config() -> Dict[str, Any]:  # type: ignore[misc]
    with open(
        os.getenv("LOGGING_CONFIG", bin_path.joinpath("logging.yml").as_posix()),
        "r",
        encoding="utf-8",
    ) as logging_config:
        return yaml.load(logging_config, Loader=yaml.FullLoader)  # type: ignore[no-any-return]


def setup_logging() -> None:
    try:
        logging.config.dictConfig(get_logging_config())
    except FileNotFoundError as exc_info:
        logger.warning("logging configuration file not found: %s", str(exc_info))


setup_logging()
