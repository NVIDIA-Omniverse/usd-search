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

# third party modules
import torch

# local / proprietary modules
from onnx_export.utils import l2_normalize


class ImageEncoderWrapper(torch.nn.Module):
    def __init__(self, vision_model, normalize: bool = True):
        super().__init__()
        self.vision_model = vision_model
        self.normalize = normalize

    def forward(self, pixel_values):
        outputs = self.vision_model(pixel_values=pixel_values)
        embeddings = outputs.pooler_output
        if self.normalize:
            embeddings = l2_normalize(embeddings)
        return embeddings


class TextEncoderWrapper(torch.nn.Module):
    def __init__(self, text_model, normalize: bool = True):
        super().__init__()
        self.text_model = text_model
        self.normalize = normalize

    def forward(self, input_ids):
        outputs = self.text_model(input_ids=input_ids)
        embeddings = outputs.pooler_output
        if self.normalize:
            embeddings = l2_normalize(embeddings)
        return embeddings
