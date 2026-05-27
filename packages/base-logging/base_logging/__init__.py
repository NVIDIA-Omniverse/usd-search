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
from typing import Any, Dict

import yaml


def get_logging_config() -> Dict[str, Any]:
    """Load logging configuration from the YAML file at $LOGGING_CONFIG (default: /logging.yml)."""
    with open(os.getenv("LOGGING_CONFIG", "/logging.yml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def setup_logging() -> None:
    """Apply YAML logging config, resetting any env-var-configured loggers first."""
    for log in [logging.getLogger(name) for name in logging.root.manager.loggerDict]:
        log.propagate = True
        log.level = 0
    try:
        logging.config.dictConfig(get_logging_config())
    except FileNotFoundError as exc:
        logging.getLogger(__name__).warning("Logging config file not found: %s", exc)
