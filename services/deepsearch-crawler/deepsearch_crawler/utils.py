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
import re

# standard modules
from typing import Optional

# local / proprietary modules
from search_utils.storage_client.data import PathType

from .config import ExtraCrawlerConfig

logger = logging.getLogger(__name__)


def exclude_items(  # type: ignore[no-any-unimported]  # missing stubs
    item: PathType, extra_config: Optional[ExtraCrawlerConfig]
) -> bool:
    """Given the item path - if the item needs to be excluded - return True

    Args:
        item (PathType): item

    Returns:
        bool: True if item needs to be excluded
    """
    # if extra config is not set - do not exclude anything
    if extra_config is None:
        return False

    if (
        extra_config.exclude_patterns is not None
        and item.uri is not None
        and any(re.match(pattern, item.uri) is not None for pattern in extra_config.exclude_patterns)
    ):
        logger.debug(
            "Asset %s is excluded as it matches exclude patterns: %s",
            str(item.uri),
            str(extra_config.exclude_patterns),
        )
        return True

    if (
        extra_config.include_patterns is not None
        and item.uri is not None
        and all(re.match(pattern, item.uri) is None for pattern in extra_config.include_patterns)
    ):
        logger.debug(
            "Asset %s is excluded as it does not match include patterns: %s",
            str(item.uri),
            str(extra_config.include_patterns),
        )
        return True

    return False
