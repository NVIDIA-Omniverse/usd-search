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

# third party modules
from PIL import Image
from transformers import SiglipImageProcessor


def get_image_processor(image_processor: SiglipImageProcessor, output_dir: str):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Saving image processor to {output_path}...")
    image_processor.save_pretrained(output_path)

    print("✓ SigLIP2 image processor exported successfully!")
    print(f"  Location: {output_path.absolute()}")
    print(f"  Image processor type: {type(image_processor).__name__}")

    # Test the image processor
    test_image = Image.new("RGB", (256, 256), color="red")
    processed = image_processor(images=test_image, return_tensors="pt")
    print(f"\nTest image processing:")
    print(f"  Output keys: {list(processed.keys())}")
    if "pixel_values" in processed:
        print(f"  Pixel values shape: {processed['pixel_values'].shape}")

    return image_processor
