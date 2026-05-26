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

from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1000)
def change_of_basis_matrix(new_basis: tuple[float]) -> np.array:
    assert len(new_basis) == 3
    # Gram-Schmidt process
    Q, _ = np.linalg.qr(new_basis)

    # Transformation matrix
    transformation_matrix = np.linalg.inv(Q)

    return transformation_matrix


def get_vector(from_vector: list[float], to_vector: list[float]):
    assert len(from_vector) == 3
    assert len(to_vector) == 3
    return [
        to_vector[0] - from_vector[0],
        to_vector[1] - from_vector[1],
        to_vector[2] - from_vector[2],
    ]


def get_transformed_vector(
    from_vector: list[float],
    to_vector: list[float],
    transformation_matrix: list[list[float]],
):
    assert len(transformation_matrix) == 3
    assert all(len(row) == 3 for row in transformation_matrix)
    return np.dot(transformation_matrix, get_vector(from_vector, to_vector))
