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

# standard packages
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional, TypedDict

# third party modules
import numpy as np
from numpy.typing import NDArray
from typing_extensions import NotRequired


class ProcessedQuery(TypedDict):
    path: str
    score: float
    image_key: NotRequired[str]
    embedding: NotRequired[NDArray[np.float32]]
    source: NotRequired[dict]


@dataclass
class SearchGenResponse:
    item: ProcessedQuery
    acl: List[str]


@dataclass
class SearchConfigParams:
    source_filter: Optional[dict] = None
    return_dict: bool = True
    return_all: bool = True
    only_key: bool = False
    searchable_items_subset: Optional[list[str]] = None


class ImagePreProcessing(str, Enum):
    fit = "fit"
    resize = "resize"
    pad = "pad"


class ErrorStatus(str, Enum):
    ok = "ok"
    client_unavailable = "client_unavailable"


class BackendSearchItem(TypedDict):
    name: NotRequired[str]
    value: NotRequired[str]
    enabled: NotRequired[bool]
    image_key: NotRequired[str]
    f: NotRequired[str]
    id: NotRequired[str]
    omni_file: NotRequired[dict]
    acl: NotRequired[List[str]]
    es_score: NotRequired[float]
    render: NotRequired[Any]
    prediction: NotRequired[List[dict]]
    embed: NotRequired[NDArray[np.float32]]
