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

# The pickle-hardening primitive now lives in search-utils (the most upstream
# package) so every downstream consumer can share one allowlist unpickler.
# This module re-exports it and keeps the deepsearch-side domain allowlists.
from typing import Any, Dict, List

from search_utils.secure_pickle import (  # noqa: F401
    RestrictedUnpickler,
    _register_class,
    dump,
    dumps,
    load,
    loads,
)

# Approved imports for Redis-based plugin cache operations.
# Covers PluginItemStatus / PluginItemStatusHistory stored by the cache service.
CACHE_CLASSES: Dict[str, List[str]] = {
    "cache.src": ["PluginItemStatus", "PluginItemStatusHistory"],
}

# Approved imports for loading legacy test fixture .pkl files, which may
# contain numpy arrays (embeddings) in addition to cache model types.
FIXTURE_CLASSES: Dict[str, List[str]] = {
    **CACHE_CLASSES,
    "numpy": ["ndarray", "dtype"],
    # Both old and new internal numpy module paths for cross-version compatibility
    # (numpy >= 2.0 renamed numpy.core -> numpy._core). At HIGHEST_PROTOCOL,
    # contiguous arrays reconstruct via numpy(._)core.numeric._frombuffer.
    "numpy.core.multiarray": ["_reconstruct", "scalar"],
    "numpy._core.multiarray": ["_reconstruct", "scalar"],
    "numpy.core._multiarray_umath": ["_reconstruct"],
    "numpy.core.numeric": ["_frombuffer"],
    "numpy._core.numeric": ["_frombuffer"],
}


def register_approved_class(obj: Any) -> None:
    """Register a class as safe to deserialize in CACHE_CLASSES."""
    _register_class(CACHE_CLASSES, obj)
