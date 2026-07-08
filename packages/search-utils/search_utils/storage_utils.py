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

from io import BytesIO

# standard imports
from typing import Union

# third party imports
import numpy as np
from numpy.typing import NDArray


def compress_np_data(np_array: NDArray[Union[np.int64, np.float32]]) -> str:
    with BytesIO() as stream:
        np.savez_compressed(stream, x=np_array)
        stream.seek(0)
        out = stream.read()
    return out.decode("latin1")


def decompress_np_data(encoding: Union[str, bytes], field: str = "x") -> NDArray[Union[np.int64, np.float32]]:
    if isinstance(encoding, str):
        encoding = encoding.encode("latin1")
    # decoding the
    with BytesIO(encoding) as stream:
        # compress_np_data only ever writes a plain numeric array (savez x=…),
        # so object-array unpickling is never needed — keep it disabled to avoid
        # the np.load pickle RCE path.
        data: NDArray[Union[np.int64, np.float32]] = np.load(stream, allow_pickle=False)[field]
    return data
