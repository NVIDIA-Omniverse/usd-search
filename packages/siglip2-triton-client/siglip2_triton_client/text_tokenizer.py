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
from pathlib import Path
from typing import Union

# third party modules
import numpy as np
from numpy.typing import NDArray
from tokenizers import Tokenizer

_TOKENIZER_PATH = Path(__file__).parent / "tokenizer" / "tokenizer.json"


class TextTokenizer:
    def __init__(self, max_length: int = 64):
        self.tokenizer = Tokenizer.from_file(str(_TOKENIZER_PATH))
        self.tokenizer.enable_padding(length=max_length, pad_id=0, pad_token="<pad>")
        self.tokenizer.enable_truncation(max_length=max_length)
        self.max_length = max_length

    def __call__(self, texts: Union[str, list[str]]) -> NDArray[np.int64]:
        if isinstance(texts, str):
            texts = [texts]
        encoded = self.tokenizer.encode_batch(texts)
        return np.array([enc.ids for enc in encoded], dtype=np.int64)

    def batch_iter(self, texts: list[str], batch_size: int = 32):
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            yield self(batch)
