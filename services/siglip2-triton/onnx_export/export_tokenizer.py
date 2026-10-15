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
from tokenizers import Tokenizer, normalizers
from transformers import PreTrainedTokenizerBase


def _ensure_lowercase_normalizer(tokenizer_json: Path) -> None:
    """Prepend a ``Lowercase`` normalizer if absent — older ``transformers`` omit it here."""
    tok = Tokenizer.from_file(str(tokenizer_json))
    normalizer = json.loads(tok.to_str()).get("normalizer")

    def _has_lowercase(node) -> bool:
        if not isinstance(node, dict):
            return False
        if node.get("type") == "Lowercase":
            return True
        return any(_has_lowercase(child) for child in node.get("normalizers", []))

    if _has_lowercase(normalizer):
        print("  Lowercase normalizer: already present")
        return

    tok.normalizer = (
        normalizers.Sequence([normalizers.Lowercase(), tok.normalizer])
        if tok.normalizer is not None
        else normalizers.Lowercase()
    )
    tok.save(str(tokenizer_json), pretty=True)
    print("  Lowercase normalizer: added (SigLIP2 reference preprocessing)")


def get_tokenizer(tokenizer: PreTrainedTokenizerBase, output_dir: str):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    print(f"Saving tokenizer to {output_path}...")
    tokenizer.save_pretrained(output_path)
    _ensure_lowercase_normalizer(output_path / "tokenizer.json")

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
            print("  Model max length: unlimited")

    # Test the tokenizer
    test_text = "a photo of a cat"
    tokens = tokenizer(test_text, return_tensors="pt", padding=True, truncation=True)
    print(f"\nTest tokenization of '{test_text}':")
    print(f"  tokens: {tokens}")

    return tokenizer
