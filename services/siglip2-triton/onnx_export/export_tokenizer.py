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
from transformers import PreTrainedTokenizerBase


def get_tokenizer(tokenizer: PreTrainedTokenizerBase, output_dir: str):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Saving tokenizer to {output_path}...")
    tokenizer.save_pretrained(output_path)

    # Remove files not needed at runtime (only tokenizer.json is used)
    for f in [
        "chat_template.jinja",
        "special_tokens_map.json",
        "tokenizer_config.json",
    ]:
        p = output_path / f
        if p.exists():
            p.unlink()

    print("✓ SigLIP2 tokenizer exported successfully!")
    print(f"  Location: {output_path.absolute()}")
    print(f"  Tokenizer type: {type(tokenizer).__name__}")
    print(f"  Vocab size: {tokenizer.vocab_size}")

    # Check model_max_length
    if hasattr(tokenizer, "model_max_length"):
        max_len = tokenizer.model_max_length
        if max_len != float("inf"):
            print(f"  Model max length: {max_len}")
        else:
            print(f"  Model max length: unlimited")

    # Test the tokenizer
    test_text = "a photo of a cat"
    tokens = tokenizer(test_text, return_tensors="pt", padding=True, truncation=True)
    print(f"\nTest tokenization of '{test_text}':")
    print(f"  tokens: {tokens}")

    return tokenizer
