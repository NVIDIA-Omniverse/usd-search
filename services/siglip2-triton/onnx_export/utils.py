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
import torch


def get_onnx_runtime_providers():
    # third party modules
    import onnxruntime as ort

    available_providers = ort.get_available_providers()
    priority_providers = [
        "CUDAExecutionProvider",
        "DmlExecutionProvider",
        "CoreMLExecutionProvider",
        "CPUExecutionProvider",
    ]
    providers = [p for p in priority_providers if p in available_providers]
    if not providers:
        providers = ["CPUExecutionProvider"]
    print(f"Using ONNX Runtime providers: {providers}")
    return providers


def _get_total_model_size(model_path: Path) -> float:
    """Get total model size including external data in MB."""
    parent = model_path.parent
    total_size = 0
    for f in parent.iterdir():
        if f.is_file():
            total_size += f.stat().st_size
    return total_size / (1024**2)


def optimize_onnx_model(model_path: Path, optimization_level: str = "basic"):
    """
    Apply ONNX Runtime offline graph optimizations via CUDA EP.

    The 1/ directory is wiped before each export by export_siglip2.py.
    The optimized model is saved in-place alongside its external data files.

    Args:
        model_path: Path to the ONNX model file
        optimization_level: One of "disable", "basic", "extended", "all"
            - "basic": constant folding, redundant node elimination
            - "extended": + complex node fusions (MatMul+Add, Reshape, etc.)
            - "all": all optimizations including layout transformations
    """
    # third party modules
    import onnxruntime as ort

    if not isinstance(model_path, Path):
        model_path = Path(model_path)

    total_size_mb = _get_total_model_size(model_path)
    print(f"  Model size: {total_size_mb:.0f} MB")

    if optimization_level == "disable":
        return model_path

    level_map = {
        "basic": ort.GraphOptimizationLevel.ORT_ENABLE_BASIC,
        "extended": ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED,
        "all": ort.GraphOptimizationLevel.ORT_ENABLE_ALL,
    }
    opt_level = level_map.get(optimization_level, ort.GraphOptimizationLevel.ORT_ENABLE_BASIC)

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = opt_level

    # Save optimized model alongside the original (same directory so
    # external data file references stay valid)
    model_dir = model_path.parent
    optimized_path = model_dir / f"{model_path.stem}_optimized.onnx"
    sess_options.optimized_model_filepath = str(optimized_path)

    providers = get_onnx_runtime_providers()
    print(f"  Applying ORT {optimization_level} optimizations ({providers[0]})...")
    _ = ort.InferenceSession(str(model_path), sess_options, providers=providers)

    if optimized_path.exists():
        # Replace original .onnx with optimized version.
        # External data files are unchanged (ORT graph optimizer only
        # rewrites the graph proto, not the weight tensors).
        model_path.unlink()
        optimized_path.rename(model_path)
        print(f"  ✓ Applied ORT graph optimizations (level: {optimization_level})")
    else:
        print(f"  Note: Optimized model not created, keeping original.")

    return model_path


def convert_to_fp16(model_path: Path, op_block_list: list[str] = None):
    """
    Convert an ONNX model to mixed-precision FP16, keeping numerically
    sensitive operations in FP32.

    Args:
        model_path: Path to the ONNX model file
        op_block_list: Op types that must stay FP32. Defaults to
            LayerNormalization, Softmax, ReduceMean (norm/attention
            accumulation ops that are unstable in FP16).
    """
    try:
        # third party modules
        import onnx
        from onnxruntime.transformers import float16
    except ImportError:
        print("  Note: onnxruntime.transformers.float16 not available, skipping FP16 conversion.")
        return model_path

    if not isinstance(model_path, Path):
        model_path = Path(model_path)

    if op_block_list is None:
        op_block_list = [
            "LayerNormalization",
            "SkipLayerNormalization",
            "Softmax",
            "ReduceMean",
        ]

    print(f"  Converting to mixed-precision FP16 (keeping {op_block_list} in FP32)...")
    model = onnx.load(str(model_path), load_external_data=True)

    model_fp16 = float16.convert_float_to_float16(
        model,
        keep_io_types=True,
        op_block_list=op_block_list,
    )

    # Wipe directory and re-save (avoids stale external data files)
    model_dir = model_path.parent
    for f in model_dir.iterdir():
        if f.is_file():
            f.unlink()

    # Save with external data for large models, inline for small ones
    model_size = model_fp16.ByteSize()
    if model_size > 2 * 1024 * 1024 * 1024:  # > 2GB needs external data
        data_file = model_path.stem + ".onnx.data"
        onnx.save_model(
            model_fp16,
            str(model_path),
            save_as_external_data=True,
            all_tensors_to_one_file=True,
            location=data_file,
            size_threshold=1024,
        )
    else:
        onnx.save(model_fp16, str(model_path))

    print(f"  ✓ Converted to mixed-precision FP16")
    return model_path


def l2_normalize(x: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
    """
    Numerically stable L2 normalization.

    Uses FP32 accumulation for the norm computation even when input is FP16,
    which prevents underflow/overflow in the squared sum and improves stability.

    Args:
        x: Input tensor of shape (batch_size, embedding_dim)
        eps: Small constant to prevent division by zero

    Returns:
        L2-normalized tensor with unit norm along the last dimension
    """
    # Cast to FP32 for stable norm computation, then cast back
    x_fp32 = x.float()
    norm = torch.norm(x_fp32, p=2, dim=-1, keepdim=True)
    # Clamp norm to prevent division by very small numbers
    norm = torch.clamp(norm, min=eps)
    normalized = x_fp32 / norm
    return normalized.to(x.dtype)
