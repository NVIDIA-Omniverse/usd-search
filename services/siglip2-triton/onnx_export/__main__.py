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
import fire

# local / proprietary modules
from onnx_export.export_siglip2 import SigLIP2OnnxExporter


def main(
    model_name: str = "google/siglip2-giant-opt-patch16-384",
    output_dir: str = "model_repo",
    opset: int = 18,
    fp16: bool = False,
    normalize: bool = True,
    image_size: int = 384,
    validate: bool = True,
):
    """Export SigLIP2 model to ONNX format for Triton Inference Server.

    Args:
        model_name: HuggingFace model name or path.
        output_dir: Output directory for the Triton model repository.
        opset: ONNX opset version.
        fp16: Apply mixed-precision FP16 conversion after export
              (keeps LayerNorm/Softmax in FP32).
        normalize: Apply L2 normalization on output embeddings.
        image_size: Input image size for the vision encoder.
        validate: Run cross-modal similarity validation after export.
    """
    exporter = SigLIP2OnnxExporter(
        model_name=model_name,
        output_dir=output_dir,
        opset=opset,
        use_fp16=fp16,
        normalize_embeddings=normalize,
    )
    exporter.export(
        image_size=image_size,
        validate_cross_modal=validate,
    )


if __name__ == "__main__":
    fire.Fire(main)
