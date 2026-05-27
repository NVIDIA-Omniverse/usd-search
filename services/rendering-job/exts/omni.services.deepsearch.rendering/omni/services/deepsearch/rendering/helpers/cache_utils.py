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
import time
from typing import MutableMapping


class InMemoryCache(dict):
    def __init__(self, limit: int = -1):
        self.limit = limit
        if self.limit > 0:
            self.last_accessed = {k: 0.0 for k in self.keys()}
            # make sure that limit is respected
            self.check_limit()

    def __setitem__(self, k, v) -> None:
        super().__setitem__(k, v)
        if self.limit > 0:
            self.last_accessed[k] = time.time()
            # make sure limit is respected
            self.check_limit()

    def update(self, input: MutableMapping):
        super().update(input)
        if self.limit > 0:
            for k in input:
                self.last_accessed[k] = time.time()
            # make sure limit is respected
            self.check_limit()

    def check_limit(
        self,
    ):
        """Make sure the cache size is less or equals to the limit."""
        if self.limit > 0:
            s = sorted(self.last_accessed.items(), key=lambda item: item[1])[::-1]
            keys_to_del = [it[0] for it in s[self.limit :]]

            for k in keys_to_del:
                del self[k]
                del self.last_accessed[k]

    def clean_cache(self):
        keys_to_del = list(self.keys())
        for k in keys_to_del:
            del self[k]
        self.last_accessed = {}
