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

from .data import Sensors

# import various exception classes
from .exceptions import (
    DataExtractionFailed,
    DataRetrievalError,
    EmptyResponse,
    FailedCreatingStage,
    IncompleteData,
    LoadError,
    SceneInLiveMode,
    SyntheticDataStepTimeout,
)

# import logger
from .log_utils import set_simple_logger

__all__ = [
    "EmptyResponse",
    "SceneInLiveMode",
    "FailedCreatingStage",
    "DataExtractionFailed",
    "LoadError",
    "IncompleteData",
    "DataRetrievalError",
    "SyntheticDataStepTimeout",
]

# define some constants
AZIMUTHS = [45, 135, 225, 315]
ELEVATIONS = [60, 45]
SEMANTIC_LABEL = "object"

DEFAULT_SENSOR_SET = set(
    [
        Sensors.rgb.value,
        Sensors.camera_params.value,
    ]
)


# setup logger
logger = set_simple_logger(
    "omni.services.deepsearch.rendering",
    loglevel=os.getenv("OMNI_SERVICES_DEEPSEARCH_RENDERING_LOG_LEVEL", "INFO"),
)
