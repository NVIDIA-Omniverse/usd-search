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
import os

from pydantic import Field
from pydantic_settings import BaseSettings

# local / proprietary modules
from search_utils.log_utils import set_simple_logger


class FarmBaseSettings(BaseSettings):
    log_level: str = Field(default="INFO", alias="farm_utils_loglevel")
    cache_dir: str = Field(default="/tmp/farm_client_cache", alias="farm_cache_dir")
    queue_suffix: str = Field(default="/queue/management/tasks/submit", alias="farm_queue_suffix")
    queue_task_info: str = Field(default="/queue/management/tasks/info", alias="farm_queue_task_info")
    queue_task_archive: str = Field(default="/queue/management/tasks/archive", alias="farm_queue_task_archive")
    queue_task_cancel: str = Field(default="/queue/management/tasks/cancel", alias="farm_queue_task_cancel")


farm_base_settings = FarmBaseSettings()

farm_utils_logger = set_simple_logger("farm utils", farm_base_settings.log_level)

# some default settings
FARM_TASK_TYPE = os.getenv("FARM_TASK_TYPE", "multiview-batch-render")
FARM_TASK_FUNCTION = os.getenv("FARM_TASK_FUNCTION", "deepsearch.rendering.batchrender")
FARM_RENDERING_TIMEOUT = float(os.getenv("FARM_RENDERING_TIMEOUT", "900"))
FARM_STATUS_CHECK_TIMEOUT = float(os.getenv("FARM_STATUS_CHECK_TIMEOUT", "150"))
