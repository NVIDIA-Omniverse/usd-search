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

"""Secure pickle wrapper following NVIDIA Product Security guidelines.

Provides a restricted Unpickler that enforces an allowlist of permitted
module/class pairs, mitigating arbitrary code execution during deserialization.

Usage (drop-in replacement for pickle.loads / pickle.load):

    from deepsearch_rendering_job.secure_pickle import loads, RENDERING_APPROVED_CLASSES

    data = loads(raw_bytes, approved_imports=RENDERING_APPROVED_CLASSES)

To extend the allowlist for a new flow, define a new dict following the same
pattern as RENDERING_APPROVED_CLASSES and pass it to loads()/load().
"""

# pickle is not secure, but this whole file is a wrapper to make it
# possible to reduce the risk of code injection via pickle.
import io
import pickle  # nosec B403
from functools import partial
from typing import IO, Dict, List, Optional, cast

# ---------------------------------------------------------------------------
# Approved-class registries
# ---------------------------------------------------------------------------

# Classes required to deserialize Kit worker rendering payloads:
#   {"images": numpy.ndarray (N, H, W, C) uint8, "camera_metadata": list[dict]}
# If a new numpy version introduces a different reconstruction path, add it here
# and verify by re-running the unit tests (look for "Import ... is not allowed"
# errors from RestrictedUnpickler.find_class).
RENDERING_APPROVED_CLASSES: Dict[str, List[str]] = {
    "numpy": ["ndarray", "dtype"],
    "numpy.core.multiarray": ["_reconstruct", "scalar"],
    "numpy._core.multiarray": ["_reconstruct", "scalar"],  # numpy >= 2.0
    "numpy.core.numeric": ["_frombuffer"],
    "numpy._core.numeric": ["_frombuffer"],  # numpy >= 2.0
}


# ---------------------------------------------------------------------------
# Restricted unpickler
# ---------------------------------------------------------------------------


class RestrictedUnpickler(pickle.Unpickler):
    """Unpickler that restricts deserialization to an explicit allowlist.

    Any attempt to deserialize a class not present in approved_imports raises
    ValueError, preventing execution of arbitrary callables embedded in the
    pickle stream.
    """

    def __init__(
        self,
        file: IO[bytes],
        *,
        fix_imports: bool = True,
        encoding: str = "ASCII",
        errors: str = "strict",
        approved_imports: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        super().__init__(file, fix_imports=fix_imports, encoding=encoding, errors=errors)
        self.approved_imports: Dict[str, List[str]] = approved_imports if approved_imports is not None else {}

    def find_class(self, module: str, name: str) -> type:
        if name not in self.approved_imports.get(module, []):
            raise ValueError(f"Import {module} | {name} is not allowed")
        return cast(type, super().find_class(module, name))


# ---------------------------------------------------------------------------
# Public API — mirrors pickle.dump/dumps/load/loads
# ---------------------------------------------------------------------------

dump = partial(pickle.dump, protocol=pickle.HIGHEST_PROTOCOL)  # nosec B301
dumps = partial(pickle.dumps, protocol=pickle.HIGHEST_PROTOCOL)  # nosec B301


def load(
    file: IO[bytes],
    *,
    fix_imports: bool = True,
    encoding: str = "ASCII",
    errors: str = "strict",
    approved_imports: Optional[Dict[str, List[str]]] = None,
) -> object:
    return RestrictedUnpickler(  # type: ignore[return-value]
        file,
        fix_imports=fix_imports,
        encoding=encoding,
        errors=errors,
        approved_imports=approved_imports,
    ).load()


def loads(
    s: bytes,
    *,
    fix_imports: bool = True,
    encoding: str = "ASCII",
    errors: str = "strict",
    approved_imports: Optional[Dict[str, List[str]]] = None,
) -> object:
    if isinstance(s, str):
        raise TypeError("Can't load pickle from unicode string")
    return RestrictedUnpickler(  # type: ignore[return-value]
        io.BytesIO(s),
        fix_imports=fix_imports,
        encoding=encoding,
        errors=errors,
        approved_imports=approved_imports,
    ).load()
