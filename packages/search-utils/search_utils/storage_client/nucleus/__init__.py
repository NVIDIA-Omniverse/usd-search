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
import logging
import os
from typing import Dict

# local / proprietary modules
from ...misc_utils import str2bool

# from omni.client import Connection

logger = logging.getLogger(__name__)

DEBUG_LOGGING = logger.isEnabledFor(logging.DEBUG)

# define some constants
# > make sure service user has admin access
ASSERT_ADMIN_USER = str2bool(os.getenv("ASSERT_ADMIN_USER", "True"))

# > default deployment look up set-up
DEPLOYMENT_LOOKUP = os.getenv("NUCLEUS_DEPLOYMENT_LOOKUP", "external")

# > number of paths that are processed by tagging service in one batch
READ_BATCH_SIZE = int(os.getenv("TAG_UTILS_READ_BATCHSIZE", "256"))


# TODO: this is required to be able to implement a fallback solution
#  for the server subscription
NUCLEUS_REQUIRED_CAPABILITIES: Dict[str, int] = {}
# NUCLEUS_REQUIRED_CAPABILITIES = getattr(Connection, "__interface_capabilities__", None)
# if "service_subscribe_list" in NUCLEUS_REQUIRED_CAPABILITIES:
#     logger.warning(
#         "Removing 'service_subscribe_list' from capabilities to support previous version of omniverse connection"
#     )
#     del NUCLEUS_REQUIRED_CAPABILITIES["service_subscribe_list"]
#     NUCLEUS_REQUIRED_CAPABILITIES["read"] = 0
#     NUCLEUS_REQUIRED_CAPABILITIES["subscribe_read_asset"] = 0
#     NUCLEUS_REQUIRED_CAPABILITIES["subscribe_read_object"] = 1
#     NUCLEUS_REQUIRED_CAPABILITIES["subscribe_list"] = 1
