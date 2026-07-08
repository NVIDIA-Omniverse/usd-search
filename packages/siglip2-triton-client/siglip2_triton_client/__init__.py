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

# local / proprietary modules
from .async_client import (
    AsyncTritonEnsembleImageClient,
    AsyncTritonEnsembleTextClient,
    AsyncTritonImageClient,
    AsyncTritonTextClient,
)
from .client import (
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
    TritonImageClient,
    TritonTextClient,
)
from .config import TritonClientSettings
from .text_tokenizer import TextTokenizer

# Lazy imports for classes that require optional dependencies (transformers, pillow).
# These are only loaded when accessed, so core functionality works without them.
_LAZY_IMPORTS = {
    "ImagePreprocessor": ".image_preprocessing",
    "TritonPreprocessedImageClient": ".client",
    "TritonPreprocessedTextClient": ".client",
    "AsyncTritonPreprocessedImageClient": ".async_client",
    "AsyncTritonPreprocessedTextClient": ".async_client",
    # High-level SigLIP2 embedding wrapper (needs pillow + transformers via the
    # preprocessed clients) — moved here from the retired vision_endpoint package.
    "SigLIP2": ".clip",
    "SigLIP2Config": ".clip",
    "BaseCLIP": ".clip",
    "CLIPConfig": ".clip",
    "CLIPService": ".clip",
    "CLIPException": ".clip",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        # standard modules
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AsyncTritonImageClient",
    "AsyncTritonTextClient",
    "AsyncTritonPreprocessedImageClient",
    "AsyncTritonPreprocessedTextClient",
    "AsyncTritonEnsembleTextClient",
    "AsyncTritonEnsembleImageClient",
    "ImagePreprocessor",
    "TextTokenizer",
    "TritonImageClient",
    "TritonTextClient",
    "TritonPreprocessedImageClient",
    "TritonPreprocessedTextClient",
    "TritonEnsembleTextClient",
    "TritonEnsembleImageClient",
    "TritonClientSettings",
    "SigLIP2",
    "SigLIP2Config",
    "BaseCLIP",
    "CLIPConfig",
    "CLIPService",
    "CLIPException",
]
