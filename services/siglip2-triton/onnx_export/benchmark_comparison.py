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

"""
Benchmark comparing PyTorch vs ONNX inference performance.

Usage:
    python -m onnx_export.benchmark_comparison
    python -m onnx_export.benchmark_comparison --model_name google/siglip2-base-patch16-224
    python -m onnx_export.benchmark_comparison --num_iterations 100
"""

# standard modules
import sys
import time
from pathlib import Path
from typing import Optional

# third party modules
import numpy as np
import onnxruntime as ort
import torch

# local / proprietary modules
from onnx_export.utils import get_onnx_runtime_providers
from PIL import Image
from transformers import AutoModel, AutoTokenizer, SiglipImageProcessor


class BenchmarkRunner:
    """Run benchmarks comparing PyTorch vs ONNX for SigLIP2 models."""

    def __init__(
        self,
        model_name: str = "google/siglip2-giant-opt-patch16-384",
        model_repo: str = "model_repo",
        num_warmup: int = 5,
        num_iterations: int = 50,
        image_size: int = 384,
    ):
        self.model_name = model_name
        self.model_repo = Path(model_repo)
        self.num_warmup = num_warmup
        self.num_iterations = num_iterations
        self.image_size = image_size

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")

        print("Loading processor...")
        self.processor = SiglipImageProcessor.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        self._prepare_test_data()

    def _prepare_test_data(self):
        """Prepare test images and texts."""
        print("Preparing test data...")

        self.test_image = Image.new("RGB", (self.image_size, self.image_size), color="white")
        self.test_text = "a test image"

        img_inputs = self.processor(images=self.test_image, return_tensors="pt")
        txt_inputs = self.tokenizer(
            [self.test_text],
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=64,
        )

        self.pixel_values = img_inputs["pixel_values"]
        self.input_ids = txt_inputs["input_ids"]
        self.attention_mask = txt_inputs.get("attention_mask", torch.ones_like(self.input_ids))

    def benchmark_pytorch(self, use_fp16: bool = False) -> dict[str, float]:
        """Benchmark PyTorch model."""
        print(f"\nBenchmarking PyTorch ({'FP16' if use_fp16 else 'FP32'})...")

        with torch.no_grad():
            model = AutoModel.from_pretrained(self.model_name).eval().to(self.device)

            if use_fp16 and self.device.type == "cuda":
                model = model.half()

        pixel_values = self.pixel_values.to(self.device)
        input_ids = self.input_ids.to(self.device)
        attention_mask = self.attention_mask.to(self.device)

        if use_fp16 and self.device.type == "cuda":
            pixel_values = pixel_values.half()

        # Warmup
        print(f"  Warming up ({self.num_warmup} iterations)...")
        for _ in range(self.num_warmup):
            with torch.no_grad():
                _ = model.get_image_features(pixel_values=pixel_values)
                _ = model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)

        # Benchmark image encoder
        print(f"  Benchmarking image encoder ({self.num_iterations} iterations)...")
        if self.device.type == "cuda":
            torch.cuda.synchronize()

        start_time = time.time()
        for _ in range(self.num_iterations):
            with torch.no_grad():
                _ = model.get_image_features(pixel_values=pixel_values)
                if self.device.type == "cuda":
                    torch.cuda.synchronize()
        img_time = (time.time() - start_time) / self.num_iterations * 1000

        # Benchmark text encoder
        print(f"  Benchmarking text encoder ({self.num_iterations} iterations)...")
        if self.device.type == "cuda":
            torch.cuda.synchronize()

        start_time = time.time()
        for _ in range(self.num_iterations):
            with torch.no_grad():
                _ = model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)
                if self.device.type == "cuda":
                    torch.cuda.synchronize()
        txt_time = (time.time() - start_time) / self.num_iterations * 1000

        model_size = sum(p.numel() * p.element_size() for p in model.parameters()) / (1024**2)

        return {
            "image_time_ms": img_time,
            "text_time_ms": txt_time,
            "total_time_ms": img_time + txt_time,
            "model_size_mb": model_size,
        }

    def _get_onnx_model_size(self, model_dir: Path) -> float:
        """Get total size of ONNX model including external data files in MB."""
        total = 0
        for f in model_dir.iterdir():
            if f.is_file():
                total += f.stat().st_size
        return total / (1024**2)

    def benchmark_onnx(self) -> Optional[dict[str, float]]:
        """Benchmark ONNX models from the model repository."""
        img_model_dir = self.model_repo / "siglip2_vision_encoder_onnx" / "1"
        txt_model_dir = self.model_repo / "siglip2_text_encoder_onnx" / "1"
        img_path = img_model_dir / "model.onnx"
        txt_path = txt_model_dir / "model.onnx"

        if not img_path.exists() or not txt_path.exists():
            print(f"  ONNX models not found in {self.model_repo}, skipping...")
            return None

        print("\nBenchmarking ONNX Runtime...")

        providers = get_onnx_runtime_providers()

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
        sess_options.enable_mem_pattern = True
        sess_options.enable_mem_reuse = True

        img_sess = ort.InferenceSession(str(img_path), sess_options=sess_options, providers=providers)
        txt_sess = ort.InferenceSession(str(txt_path), sess_options=sess_options, providers=providers)

        print(f"  Using provider: {img_sess.get_providers()[0]}")

        pixel_values_np = self.pixel_values.numpy()
        input_ids_np = self.input_ids.numpy()
        attention_mask_np = self.attention_mask.numpy()

        # Warmup
        print(f"  Warming up ({self.num_warmup} iterations)...")
        for _ in range(self.num_warmup):
            _ = img_sess.run(None, {"pixel_values": pixel_values_np})
            _ = txt_sess.run(None, {"input_ids": input_ids_np, "attention_mask": attention_mask_np})

        # Benchmark image encoder
        print(f"  Benchmarking image encoder ({self.num_iterations} iterations)...")
        start_time = time.time()
        for _ in range(self.num_iterations):
            _ = img_sess.run(None, {"pixel_values": pixel_values_np})
        img_time = (time.time() - start_time) / self.num_iterations * 1000

        # Benchmark text encoder
        print(f"  Benchmarking text encoder ({self.num_iterations} iterations)...")
        start_time = time.time()
        for _ in range(self.num_iterations):
            _ = txt_sess.run(None, {"input_ids": input_ids_np, "attention_mask": attention_mask_np})
        txt_time = (time.time() - start_time) / self.num_iterations * 1000

        img_size = self._get_onnx_model_size(img_model_dir)
        txt_size = self._get_onnx_model_size(txt_model_dir)

        return {
            "image_time_ms": img_time,
            "text_time_ms": txt_time,
            "total_time_ms": img_time + txt_time,
            "model_size_mb": img_size + txt_size,
        }

    def run_all_benchmarks(self) -> dict[str, dict[str, float]]:
        """Run all benchmark configurations."""
        results = {}

        try:
            results["PyTorch (FP32)"] = self.benchmark_pytorch(use_fp16=False)
        except Exception as e:
            print(f"PyTorch FP32 benchmark failed: {e}")

        if self.device.type == "cuda":
            try:
                results["PyTorch (FP16)"] = self.benchmark_pytorch(use_fp16=True)
            except Exception as e:
                print(f"PyTorch FP16 benchmark failed: {e}")

        try:
            result = self.benchmark_onnx()
            if result:
                results["ONNX Runtime"] = result
        except Exception as e:
            print(f"ONNX benchmark failed: {e}")

        return results

    def print_results(self, results: dict[str, dict[str, float]]):
        """Print benchmark results in a table."""
        if not results:
            print("\nNo results to display")
            return

        print("\n" + "=" * 80)
        print("BENCHMARK RESULTS")
        print("=" * 80)

        print(
            f"\n{'Configuration':<25} {'Image (ms)':<12} {'Text (ms)':<12} {'Total (ms)':<12} {'Size (MB)':<12} {'Speedup':<10}"
        )
        print("-" * 80)

        baseline_time = None
        if "PyTorch (FP32)" in results:
            baseline_time = results["PyTorch (FP32)"]["total_time_ms"]

        for config, metrics in results.items():
            img_time = metrics["image_time_ms"]
            txt_time = metrics["text_time_ms"]
            total_time = metrics["total_time_ms"]
            size = metrics["model_size_mb"]

            speedup = ""
            if baseline_time and baseline_time > 0:
                speedup = f"{baseline_time / total_time:.2f}x"

            print(
                f"{config:<25} {img_time:>10.2f}  {txt_time:>10.2f}  {total_time:>10.2f}  {size:>10.1f}  {speedup:>10}"
            )

        print("-" * 80)

        if len(results) > 1 and baseline_time:
            best_config = min(results.items(), key=lambda x: x[1]["total_time_ms"])
            best_time = best_config[1]["total_time_ms"]
            improvement = (baseline_time - best_time) / baseline_time * 100

            print(f"\nBest configuration: {best_config[0]}")
            print(f"Performance improvement: {improvement:.1f}% faster than PyTorch FP32")
            print(f"Throughput improvement: {baseline_time / best_time:.2f}x")


def main(
    model_name: str = "google/siglip2-giant-opt-patch16-384",
    model_repo: str = "model_repo",
    num_warmup: int = 5,
    num_iterations: int = 50,
    image_size: int = 384,
):
    """Run benchmark comparison.

    Args:
        model_name: HuggingFace model name.
        model_repo: Path to the Triton model repository with exported ONNX models.
        num_warmup: Number of warmup iterations.
        num_iterations: Number of benchmark iterations.
        image_size: Input image size.
    """
    print("SigLIP2 Model Benchmark: PyTorch vs ONNX Runtime")
    print("=" * 80)

    model_repo_path = Path(model_repo)
    onnx_img = model_repo_path / "siglip2_vision_encoder_onnx" / "1" / "model.onnx"
    onnx_txt = model_repo_path / "siglip2_text_encoder_onnx" / "1" / "model.onnx"

    if not onnx_img.exists() or not onnx_txt.exists():
        print(f"\nError: ONNX models not found in {model_repo}")
        print("Please export models first:")
        print("  python -m onnx_export")
        sys.exit(1)

    runner = BenchmarkRunner(
        model_name=model_name,
        model_repo=model_repo,
        num_warmup=num_warmup,
        num_iterations=num_iterations,
        image_size=image_size,
    )
    results = runner.run_all_benchmarks()
    runner.print_results(results)


if __name__ == "__main__":
    # third party modules
    import fire

    fire.Fire(main)
