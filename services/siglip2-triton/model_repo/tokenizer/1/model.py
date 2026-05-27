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
from pathlib import Path

# third party modules
import numpy as np
import triton_python_backend_utils as pb_utils
from tokenizers import Tokenizer


class TritonPythonModel:
    """Triton Python backend model for SigLIP2 tokenizer."""

    def initialize(self, args):
        model_config = json.loads(args["model_config"])

        current_dir = Path(__file__).parent
        tokenizer_file = current_dir / "tokenizer" / "tokenizer.json"

        # Load tokenizer directly from tokenizer.json using tokenizers library
        self.tokenizer = Tokenizer.from_file(str(tokenizer_file))

        # Enable padding and truncation
        self.tokenizer.enable_padding(length=64, pad_id=0, pad_token="<pad>")
        self.tokenizer.enable_truncation(max_length=64)

        # Resolve output dtypes from model config
        self.output_dtypes = {}
        for output_config in model_config["output"]:
            name = output_config["name"]
            data_type = output_config["data_type"]
            self.output_dtypes[name] = pb_utils.triton_string_to_numpy(data_type)

    def execute(self, requests: list) -> list:
        responses = []
        for request in requests:
            # Get input text
            text_tensor = pb_utils.get_input_tensor_by_name(request, "text")
            text_data = text_tensor.as_numpy()

            # Decode bytes to strings if necessary
            if text_data.dtype == np.object_:
                texts = [t.decode("utf-8") if isinstance(t, bytes) else t for t in text_data.flatten()]
            else:
                texts = text_data.flatten().tolist()

            # Tokenize using tokenizers library
            encoded = self.tokenizer.encode_batch(texts)

            # Extract input IDs from encodings
            input_ids_dtype = self.output_dtypes.get("input_ids", np.int64)
            input_ids = np.array([enc.ids for enc in encoded], dtype=input_ids_dtype)

            # Create output tensors
            input_ids_tensor = pb_utils.Tensor("input_ids", input_ids)

            # Create response
            inference_response = pb_utils.InferenceResponse(output_tensors=[input_ids_tensor])
            responses.append(inference_response)

        return responses

    def finalize(self):
        """Clean up resources."""
        print("Cleaning up tokenizer...")
