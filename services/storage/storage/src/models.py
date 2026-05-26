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

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

Capabilities = Dict[str, int]


class InputSpaceMetric(str, Enum):
    cosine = "cosine"
    euclidean = "euclidean"


class ProjectionMethod(str, Enum):
    umap = "umap"


class Status(str, Enum):
    ok = "ok"
    error = "error"
    key_missing = "key_missing"
    backend_unavailable = "backend_unavailable"
    reducer_unavailable = "reducer_unavailable"
    invalid_item_key = "invalid_item_key"
    type_error = "type_error"
    requested_backend_unavailable = "requested_backend_unavailable"
    backend_is_not_provided = "backend_is_not_provided"


class ModelHashes(BaseModel):
    status: Status
    content: List[str]


class Projection(BaseModel):
    method: ProjectionMethod
    model_hash: str
    max_samples: Optional[float] = None
    target_dim: Optional[float] = None
    metric: Optional[InputSpaceMetric] = None


class ProjectionInput(BaseModel):
    projection: Projection
    content: str


class ReadyzResponse(BaseModel):
    ready: bool


class LivezResponse(BaseModel):
    live: bool


class SizeResponse(BaseModel):
    status: Status
    size: float


class ExistsStatus(BaseModel):
    status: Status
    exists: Optional[List[bool]] = None


class Result(BaseModel):
    status: Status
    data: Optional[Any] = None


class DataContent(BaseModel):
    data: str


class NgsearchStorageDemoTestArgs(BaseModel):
    input: Optional[str] = None


class NgsearchStorageAddItemArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageRemoveItemArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageUpdateArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageUpdateItemArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageUpdateItemsArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageUpdateMetaArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetItemArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetMetaArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetKeysArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetKeysIterArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetKeysForDatatypeArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageGetKeysForDatatypeIterArgs(BaseModel):
    input: str
    compression: Optional[str] = None
    backend_name: Optional[str] = None


class NgsearchStorageExistsArgs(BaseModel):
    keys: List[str]
    backend_name: Optional[str] = None


class NgsearchStorageSizeArgs(BaseModel):
    pass


class NgsearchStorageLivezArgs(BaseModel):
    pass


class NgsearchStorageReadyzArgs(BaseModel):
    pass
