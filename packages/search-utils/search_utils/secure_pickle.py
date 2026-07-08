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

# pickle is not secure, but this whole file is a wrapper to reduce the risk
# of code injection via pickle by enforcing a per-call import allowlist.
#
# This module lives in search-utils (the most upstream package) so that every
# downstream package can route its pickle reads through the same allowlist
# unpickler. deepsearch_utils.secure_pickle re-exports the primitive from here.
import io
import pickle  # nosec B403
from typing import Any, Dict, List, Optional

# Approved imports for the generic cache / farm payloads handled by search-utils
# (Redis cache dicts, RedisQueue, and the zlib-compressed farm render payloads
# decoded by decompress_data).
#
# These caches hold plain data containers and numpy arrays — never callables.
# Restricting find_class to these data-only types blocks the pickle RCE gadgets
# (os.system, subprocess.Popen, builtins.eval, posix.*, ...) while still allowing
# legitimate cache reads. A legitimate-but-unlisted class surfaces as a loud
# ValueError at read time rather than silent data loss — widen deliberately.
CACHE_APPROVED_CLASSES: Dict[str, List[str]] = {
    "builtins": [
        "dict",
        "list",
        "tuple",
        "set",
        "frozenset",
        "str",
        "bytes",
        "bytearray",
        "int",
        "float",
        "complex",
        "bool",
        "NoneType",
        "range",
        "slice",
    ],
    "collections": ["OrderedDict", "defaultdict", "Counter"],
    "datetime": ["datetime", "date", "time", "timedelta", "timezone"],
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


def _register_class(approved: Dict[str, List[str]], obj: Any) -> None:
    name = getattr(obj, "__qualname__", None) or obj.__name__
    module = pickle.whichmodule(obj, name)
    approved.setdefault(module, []).append(name)


class RestrictedUnpickler(pickle.Unpickler):
    def __init__(
        self,
        file: Any,
        *,
        fix_imports: bool = True,
        encoding: str = "ASCII",
        errors: str = "strict",
        buffers: Optional[Any] = None,
        approved_imports: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        super().__init__(
            file,
            fix_imports=fix_imports,
            encoding=encoding,
            errors=errors,
            buffers=buffers,
        )
        self.approved_imports: Dict[str, List[str]] = approved_imports or {}

    def find_class(self, module: str, name: str) -> Any:
        if name not in self.approved_imports.get(module, []):
            raise ValueError(f"Import {module} | {name} is not allowed")
        return super().find_class(module, name)


def dump(
    obj: Any,
    file: Any,
    *,
    fix_imports: bool = True,
    buffer_callback: Optional[Any] = None,
) -> None:
    pickle.dump(
        obj,
        file,
        protocol=pickle.HIGHEST_PROTOCOL,
        fix_imports=fix_imports,
        buffer_callback=buffer_callback,
    )  # nosec B301


def dumps(obj: Any, *, fix_imports: bool = True, buffer_callback: Optional[Any] = None) -> bytes:
    return pickle.dumps(
        obj,
        protocol=pickle.HIGHEST_PROTOCOL,
        fix_imports=fix_imports,
        buffer_callback=buffer_callback,
    )  # nosec B301


def load(
    file: Any,
    *,
    fix_imports: bool = True,
    encoding: str = "ASCII",
    errors: str = "strict",
    buffers: Optional[Any] = None,
    approved_imports: Optional[Dict[str, List[str]]] = None,
) -> Any:
    return RestrictedUnpickler(
        file,
        fix_imports=fix_imports,
        encoding=encoding,
        errors=errors,
        buffers=buffers,
        approved_imports=approved_imports,
    ).load()


def loads(
    s: bytes,
    /,
    *,
    fix_imports: bool = True,
    encoding: str = "ASCII",
    errors: str = "strict",
    buffers: Optional[Any] = None,
    approved_imports: Optional[Dict[str, List[str]]] = None,
) -> Any:
    if isinstance(s, str):
        raise TypeError("Can't load pickle from unicode string")
    return RestrictedUnpickler(
        io.BytesIO(s),
        fix_imports=fix_imports,
        encoding=encoding,
        errors=errors,
        buffers=buffers,
        approved_imports=approved_imports,
    ).load()
