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
import os
import shutil
from pathlib import Path

# third party modules
import torch

# local / proprietary modules
from onnx_export.export_image_processor import get_image_processor
from onnx_export.export_tokenizer import get_tokenizer
from onnx_export.modules import ImageEncoderWrapper, TextEncoderWrapper
from onnx_export.utils import convert_to_fp16, optimize_onnx_model
from onnx_export.validate import SigLIP2OnnxValidator
from PIL import Image
from transformers import AutoModel, AutoTokenizer, SiglipImageProcessor


class SigLIP2OnnxExporter:
    def __init__(
        self,
        model_name: str = "google/siglip2-giant-opt-patch16-384",
        output_dir: str = "model_repo",
        opset: int = 18,
        use_fp16: bool = False,
        normalize_embeddings: bool = True,
    ):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.model_name = model_name
        self.output_dir = output_dir
        self.opset = opset
        self.use_fp16 = use_fp16
        self.normalize_embeddings = normalize_embeddings

        self.output_path = Path(self.output_dir)
        self.output_path.mkdir(parents=True, exist_ok=True)
        self.load_processor()
        self.vision_model, self.text_model = self.load_model()

    def load_processor(self):
        print(f"Loading processor {self.model_name} …")
        self.image_processor = SiglipImageProcessor.from_pretrained(self.model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)

    def load_model(self):
        print(f"Loading model {self.model_name} …")
        with torch.no_grad():
            model = AutoModel.from_pretrained(self.model_name)
            model = model.eval().to(self.device)

            # Always export in FP32 for accuracy; mixed-precision FP16
            # conversion is applied post-export to keep sensitive ops in FP32.
            if self.use_fp16:
                print("FP16 mode: will apply mixed-precision conversion after ONNX export")

            # Store logit_scale and logit_bias for similarity computation
            self.logit_scale = model.logit_scale.exp().item()
            self.logit_bias = model.logit_bias.item() if model.logit_bias is not None else 0.0
            print(f"Logit scale: {self.logit_scale:.4f}, Logit bias: {self.logit_bias:.4f}")

            vision_model = ImageEncoderWrapper(model.vision_model, self.normalize_embeddings)
            text_model = TextEncoderWrapper(model.text_model, self.normalize_embeddings)
            return vision_model, text_model

    def export_tokenizer(self):
        tokenizer_output_path = os.path.join(
            self.output_path,
            "tokenizer",
            "1",
            "tokenizer",
        )
        if os.path.exists(tokenizer_output_path):
            print(f"Removing existing tokenizer directory: {tokenizer_output_path}")
            shutil.rmtree(tokenizer_output_path)
        print(f"Exporting tokenizer to {self.output_path} …")
        tokenizer = get_tokenizer(
            tokenizer=self.tokenizer,
            output_dir=tokenizer_output_path,
        )
        return tokenizer

    def export_image_processor(self):
        image_processor_output_path = os.path.join(
            self.output_path,
            "image_preprocessing",
            "1",
            "preprocessor_config",
        )
        if os.path.exists(image_processor_output_path):
            print(f"Removing existing image processor directory: {image_processor_output_path}")
            shutil.rmtree(image_processor_output_path)
        print(f"Exporting image processor to {self.output_path} …")
        image_processor = get_image_processor(
            image_processor=self.image_processor,
            output_dir=image_processor_output_path,
        )
        return image_processor

    def export_image_encoder(
        self,
        image_size: int = 384,
        export_name: str = "siglip2_vision_encoder_onnx",
    ):
        print(f"Using image size: {image_size}")

        img_output_path = os.path.join(
            self.output_path,
            export_name,
            "1",
            "model.onnx",
        )
        img_output_dir = os.path.dirname(img_output_path)
        if os.path.exists(img_output_dir):
            print(f"Removing existing image encoder directory: {img_output_dir}")
            shutil.rmtree(img_output_dir)
        os.makedirs(img_output_dir, exist_ok=True)
        print(f"Exporting image encoder to {img_output_path} …")

        image_encoder = self.vision_model

        dummy_image = Image.new("RGB", (image_size, image_size), color="white")
        pixel_values = self.image_processor(images=dummy_image, return_tensors="pt")["pixel_values"].to(self.device)

        print(f"Pixel values shape: {pixel_values.shape}")

        with torch.no_grad():
            torch.onnx.export(
                model=image_encoder,
                args=pixel_values,
                f=img_output_path,
                input_names=["pixel_values"],
                output_names=["image_embeds"],
                dynamic_axes={
                    "pixel_values": {0: "batch_size"},
                    "image_embeds": {0: "batch_size"},
                },
                opset_version=self.opset,
                dynamo=False,
            )
        optimize_onnx_model(img_output_path)
        if self.use_fp16:
            convert_to_fp16(img_output_path)
        return img_output_path

    def export_text_encoder(
        self,
        export_name: str = "siglip2_text_encoder_onnx",
    ):
        txt_output_path = os.path.join(self.output_path, export_name, "1", "model.onnx")
        txt_output_dir = os.path.dirname(txt_output_path)
        if os.path.exists(txt_output_dir):
            print(f"Removing existing text encoder directory: {txt_output_dir}")
            shutil.rmtree(txt_output_dir)
        os.makedirs(txt_output_dir, exist_ok=True)
        print(f"Exporting text encoder to {txt_output_path} …")

        text_inputs = self.tokenizer(
            ["dummy text"],
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=64,
        )
        text_inputs = {k: v.to(self.device) for k, v in text_inputs.items()}
        print(f"Text input keys: {list(text_inputs.keys())}")

        text_encoder = self.text_model

        with torch.no_grad():
            torch.onnx.export(
                model=text_encoder,
                args=text_inputs["input_ids"],
                f=txt_output_path,
                input_names=["input_ids"],
                output_names=["embeddings"],
                dynamic_axes={
                    "input_ids": {0: "batch_size"},
                    "embeddings": {0: "batch_size"},
                },
                opset_version=self.opset,
                dynamo=False,
            )
        optimize_onnx_model(txt_output_path)
        if self.use_fp16:
            convert_to_fp16(txt_output_path)
        return txt_output_path

    def export(self, image_size: int = 384, validate_cross_modal: bool = True):
        """
        Export all components of the SigLIP2 model.

        Args:
            image_size: Input image size for the vision encoder
            validate_cross_modal: Whether to run cross-modal similarity validation
        """
        self.export_tokenizer()
        self.export_image_processor()
        img_output_path = self.export_image_encoder(
            image_size=image_size,
        )

        validator = SigLIP2OnnxValidator(
            image_processor=self.image_processor,
            tokenizer=self.tokenizer,
            vision_model=self.vision_model,
            text_model=self.text_model,
            normalize_embeddings=self.normalize_embeddings,
            device=self.device,
            logit_scale=self.logit_scale,
            logit_bias=self.logit_bias,
        )
        validator.validate_image_encoder(img_output_path)
        txt_output_path = self.export_text_encoder()
        validator.validate_text_encoder(txt_output_path)
        if validate_cross_modal:
            validator.validate_cross_modal_similarity(img_output_path, txt_output_path)


if __name__ == "__main__":
    exporter = SigLIP2OnnxExporter(
        model_name="google/siglip2-giant-opt-patch16-384",
        output_dir="model_repo",
        opset=18,
        use_fp16=False,
        normalize_embeddings=True,
    )
    exporter.export(
        image_size=384,
        validate_cross_modal=True,
    )
