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
import json
import os
from pathlib import Path

# third party modules
import numpy as np
import triton_python_backend_utils as pb_utils
from PIL import Image

# PIL resampling enum values
_RESAMPLE_MAP = {
    0: Image.NEAREST,
    1: Image.LANCZOS,
    2: Image.BILINEAR,
    3: Image.BICUBIC,
}


class TritonPythonModel:
    """Image preprocessor using PIL resize + vectorized numpy rescale/normalize.

    Uses direct PIL + numpy operations to avoid torch dependency in the
    Triton server container (CPU-only torch conflicts with ONNX Runtime CUDA).
    """

    def initialize(self, args: dict) -> None:
        model_config = json.loads(args["model_config"])

        current_dir = Path(__file__).parent
        preprocessor_config_path = os.path.join(current_dir, "preprocessor_config", "preprocessor_config.json")
        with open(preprocessor_config_path, "r") as f:
            config = json.load(f)

        self.height = config["size"]["height"]
        self.width = config["size"]["width"]
        self.rescale_factor = np.float32(config.get("rescale_factor", 1.0 / 255.0))
        self.image_mean = np.array(config.get("image_mean", [0.5, 0.5, 0.5]), dtype=np.float32).reshape(3, 1, 1)
        self.image_std = np.array(config.get("image_std", [0.5, 0.5, 0.5]), dtype=np.float32).reshape(3, 1, 1)
        self.do_resize = config.get("do_resize", True)
        self.do_rescale = config.get("do_rescale", True)
        self.do_normalize = config.get("do_normalize", True)
        self.resample = _RESAMPLE_MAP.get(config.get("resample", 2), Image.BILINEAR)

        data_type = model_config["output"][0]["data_type"]
        self.output_dtype = pb_utils.triton_string_to_numpy(data_type)

    def _process_single(self, img_hwc: np.ndarray) -> np.ndarray:
        """Process a single HWC uint8 image to CHW float32."""
        if self.do_resize:
            pil_img = Image.fromarray(img_hwc)
            pil_img = pil_img.resize((self.width, self.height), self.resample)
            img_hwc = np.asarray(pil_img)

        # HWC -> CHW
        img = img_hwc.transpose(2, 0, 1).astype(np.float32)

        if self.do_rescale:
            img *= self.rescale_factor

        if self.do_normalize:
            img = (img - self.image_mean) / self.image_std

        return img

    def execute(self, requests: list) -> list:
        responses = []
        for request in requests:
            image_tensor = pb_utils.get_input_tensor_by_name(request, "raw_image")
            images = image_tensor.as_numpy()

            batch_size = images.shape[0]
            pixel_values = np.empty((batch_size, 3, self.height, self.width), dtype=self.output_dtype)

            for i in range(batch_size):
                pixel_values[i] = self._process_single(images[i])

            inference_response = pb_utils.InferenceResponse(
                output_tensors=[pb_utils.Tensor("pixel_values", pixel_values)]
            )
            responses.append(inference_response)

        return responses

    def finalize(self) -> None:
        print("Cleaning up image preprocessor...")
