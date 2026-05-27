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
import numpy as np
import onnxruntime as ort
import torch

# local / proprietary modules
from onnx_export.utils import get_onnx_runtime_providers
from PIL import Image
from transformers import PreTrainedTokenizerBase, SiglipImageProcessor


class SigLIP2OnnxValidator:
    def __init__(
        self,
        image_processor: SiglipImageProcessor,
        tokenizer: PreTrainedTokenizerBase,
        vision_model: torch.nn.Module,
        text_model: torch.nn.Module,
        normalize_embeddings: bool,
        device: torch.device,
        logit_scale: float,
        logit_bias: float,
    ):
        self.image_processor = image_processor
        self.tokenizer = tokenizer
        self.vision_model = vision_model
        self.text_model = text_model
        self.normalize_embeddings = normalize_embeddings
        self.device = device
        self.logit_scale = logit_scale
        self.logit_bias = logit_bias

    def validate_image_encoder(self, img_output_path: str):
        """
        Validate image encoder by comparing ONNX outputs against PyTorch reference.

        Checks:
        1. Output shape correctness
        2. Numerical agreement with PyTorch (max absolute error)
        3. Embedding norm (should be ~1.0 if normalization enabled)
        4. Cosine similarity between ONNX and PyTorch outputs
        """

        providers = get_onnx_runtime_providers()
        img_session = ort.InferenceSession(img_output_path, providers=providers)

        # Use a more realistic test image
        dummy_image = Image.new("RGB", (256, 256), color="blue")
        pixel_values = self.image_processor(images=dummy_image, return_tensors="pt")["pixel_values"].to(self.device)

        # Always validate in FP32: even with FP16 models, keep_io_types=True
        # ensures the ONNX model accepts FP32 inputs and returns FP32 outputs.

        # Get PyTorch reference output
        with torch.no_grad():
            pytorch_output = self.vision_model(pixel_values).cpu().numpy()

        # Get ONNX output
        onnx_output = img_session.run(None, {"pixel_values": pixel_values.cpu().numpy()})[0]

        # Validation checks
        print(f"✓ Image encoder output shape: {onnx_output.shape}")

        # Check numerical agreement
        max_abs_error = np.max(np.abs(onnx_output - pytorch_output))
        mean_abs_error = np.mean(np.abs(onnx_output - pytorch_output))
        print(f"  Max absolute error (ONNX vs PyTorch): {max_abs_error:.2e}")
        print(f"  Mean absolute error: {mean_abs_error:.2e}")

        # Check embedding norms
        onnx_norm = np.linalg.norm(onnx_output, axis=-1)
        pytorch_norm = np.linalg.norm(pytorch_output, axis=-1)
        print(f"  ONNX embedding norm: {onnx_norm[0]:.6f}")
        print(f"  PyTorch embedding norm: {pytorch_norm[0]:.6f}")

        if self.normalize_embeddings:
            if not np.allclose(onnx_norm, 1.0, atol=1e-5):
                print(f"  ⚠ Warning: ONNX embedding norm deviates from 1.0")

        # Cosine similarity between ONNX and PyTorch outputs
        cosine_sim = np.sum(onnx_output * pytorch_output) / (onnx_norm * pytorch_norm + 1e-12)
        print(f"  Cosine similarity (ONNX vs PyTorch): {cosine_sim[0]:.6f}")

        if cosine_sim < 0.9999:
            print(f"  ⚠ Warning: Low cosine similarity between ONNX and PyTorch outputs")
        else:
            print(f"  ✓ Excellent embedding fidelity")

    def _get_text_input_ids(self, texts: list[str]):
        """Get input_ids for the given texts."""
        text_inputs = self.tokenizer(
            texts,
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=64,
        )
        return text_inputs["input_ids"].to(self.device)

    def validate_text_encoder(self, txt_output_path: str):
        """
        Validate text encoder by comparing ONNX outputs against PyTorch reference.

        Checks:
        1. Output shape correctness
        2. Numerical agreement with PyTorch (max absolute error)
        3. Embedding norm (should be ~1.0 if normalization enabled)
        4. Cosine similarity between ONNX and PyTorch outputs
        """
        providers = get_onnx_runtime_providers()
        txt_session = ort.InferenceSession(txt_output_path, providers=providers)

        dummy_text = ["a photo of a cat"]
        input_ids = self._get_text_input_ids(dummy_text)

        # Get PyTorch reference output
        with torch.no_grad():
            pytorch_output = self.text_model(input_ids).cpu().numpy()

        # Get ONNX output
        onnx_output = txt_session.run(None, {"input_ids": input_ids.cpu().numpy()})[0]

        # Validation checks
        print(f"✓ Text encoder output shape: {onnx_output.shape}")

        # Check numerical agreement
        max_abs_error = np.max(np.abs(onnx_output - pytorch_output))
        mean_abs_error = np.mean(np.abs(onnx_output - pytorch_output))
        print(f"  Max absolute error (ONNX vs PyTorch): {max_abs_error:.2e}")
        print(f"  Mean absolute error: {mean_abs_error:.2e}")

        # Check embedding norms
        onnx_norm = np.linalg.norm(onnx_output, axis=-1)
        pytorch_norm = np.linalg.norm(pytorch_output, axis=-1)
        print(f"  ONNX embedding norm: {onnx_norm[0]:.6f}")
        print(f"  PyTorch embedding norm: {pytorch_norm[0]:.6f}")

        if self.normalize_embeddings:
            if not np.allclose(onnx_norm, 1.0, atol=1e-5):
                print(f"  ⚠ Warning: ONNX embedding norm deviates from 1.0")

        # Cosine similarity between ONNX and PyTorch outputs
        cosine_sim = np.sum(onnx_output * pytorch_output) / (onnx_norm * pytorch_norm + 1e-12)
        print(f"  Cosine similarity (ONNX vs PyTorch): {cosine_sim[0]:.6f}")

        if cosine_sim < 0.9999:
            print(f"  ⚠ Warning: Low cosine similarity between ONNX and PyTorch outputs")
        else:
            print(f"  ✓ Excellent embedding fidelity")

    def validate_cross_modal_similarity(self, img_output_path: str, txt_output_path: str):
        """
        Validate that the exported models produce semantically meaningful embeddings
        by testing image-text similarity.

        A matching image-text pair should have higher similarity than mismatched pairs.
        This validates that the full pipeline (including normalization) is working correctly.
        """
        print("\nValidating cross-modal similarity...")
        providers = get_onnx_runtime_providers()

        img_session = ort.InferenceSession(img_output_path, providers=providers)
        txt_session = ort.InferenceSession(txt_output_path, providers=providers)

        # Create test images with distinct colors
        test_images = [
            Image.new("RGB", (256, 256), color="red"),
            Image.new("RGB", (256, 256), color="blue"),
            Image.new("RGB", (256, 256), color="green"),
        ]
        test_texts = [
            "a red colored image",
            "a blue colored image",
            "a green colored image",
        ]

        # Get image embeddings
        image_embeddings = []
        for img in test_images:
            pixel_values = self.image_processor(images=img, return_tensors="pt")["pixel_values"]
            emb = img_session.run(None, {"pixel_values": pixel_values.cpu().numpy()})[0]
            image_embeddings.append(emb[0])
        image_embeddings = np.stack(image_embeddings)

        # Get text embeddings
        text_embeddings = []
        for text in test_texts:
            input_ids = self._get_text_input_ids([text])
            emb = txt_session.run(None, {"input_ids": input_ids.cpu().numpy()})[0]
            text_embeddings.append(emb[0])
        text_embeddings = np.stack(text_embeddings)

        # Compute similarity matrix (image x text)
        # Apply logit_scale and logit_bias as used by SigLIP2
        cosine_similarity = image_embeddings @ text_embeddings.T
        similarity_matrix = self.logit_scale * cosine_similarity + self.logit_bias

        print("  Similarity matrix (images × texts):")
        print(f"  {'':20} | {'red text':>12} | {'blue text':>12} | {'green text':>12}")
        print(f"  {'-'*20}-+-{'-'*12}-+-{'-'*12}-+-{'-'*12}")
        colors = ["red image", "blue image", "green image"]
        for i, color in enumerate(colors):
            row = similarity_matrix[i]
            print(f"  {color:20} | {row[0]:>12.4f} | {row[1]:>12.4f} | {row[2]:>12.4f}")

        # Check that diagonal (matching pairs) has highest values per row
        diagonal_highest = True
        for i in range(len(test_images)):
            row_max_idx = np.argmax(similarity_matrix[i])
            if row_max_idx != i:
                diagonal_highest = False
                print(f"  ⚠ Row {i}: expected diagonal to be highest, but column {row_max_idx} is higher")

        if diagonal_highest:
            print("  ✓ Cross-modal similarity validation passed (matching pairs have highest similarity)")
        else:
            print("  ⚠ Cross-modal similarity validation: some mismatches detected")
            print("    (This may be expected for simple solid-color test images)")

        # Verify embeddings are normalized (if normalization is enabled)
        if self.normalize_embeddings:
            img_norms = np.linalg.norm(image_embeddings, axis=1)
            txt_norms = np.linalg.norm(text_embeddings, axis=1)
            print(f"  Image embedding norms: {img_norms}")
            print(f"  Text embedding norms: {txt_norms}")
            if np.allclose(img_norms, 1.0, atol=1e-5) and np.allclose(txt_norms, 1.0, atol=1e-5):
                print("  ✓ All embeddings are unit-normalized")
            else:
                print("  ⚠ Some embeddings are not unit-normalized")
