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

from abc import ABC


class NotFoundError(Exception, ABC):
    @classmethod
    @property
    def object_type(cls):
        raise NotImplementedError

    @property
    def _message(self):
        return f"{self.object_type} {self.target} not found"

    def __init__(self, target: str | None) -> None:
        self.target = target
        super().__init__(self._message)


class SceneNotFoundError(NotFoundError):
    object_type = "Scene"

    @property
    def _message(self):
        return f"{self.object_type} {self.target} not found. Either the scene does not exist, you do not have permission to view it, or it has not been indexed."


class AssetNotFoundError(NotFoundError):
    object_type = "Asset"

    @property
    def _message(self):
        return f"{self.object_type} {self.target} not found. Either the asset does not exist, you do not have permission to view it, or it has not been indexed."


class PrimNotFoundError(NotFoundError):
    object_type = "Prim"

    @property
    def _message(self):
        return f"{self.object_type} {self.target} not found. Either the prim does not exist, you do not have permission to view it, or it has not been indexed."
