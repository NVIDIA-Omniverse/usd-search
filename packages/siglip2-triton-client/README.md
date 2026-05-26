# SigLIP2 ONNX Export & Triton Deployment

Production deployment of **SigLIP2** (`google/siglip2-giant-opt-patch16-384`) for image-text embedding inference. Takes images or text as input and produces 1536-dim L2-normalized embeddings. Cosine similarity between image and text embeddings measures semantic match.

## Model Specs

| | |
|---|---|
| **Model** | `google/siglip2-giant-opt-patch16-384` |
| **Image input** | 384x384 RGB, preprocessed to float32 (rescale 1/255, normalize mean=0.5 std=0.5) |
| **Text input** | `input_ids` only (int64, padded to length 64, **no attention_mask**) |
| **Output** | 1536-dim float32 embeddings, L2-normalized |
| **Similarity** | `sigmoid(108.33 * cosine_sim - 15.98)` for match probability |
| **Vision encoder** | ~4.4 GB ONNX (external data), ~105ms/image on A40 |
| **Text encoder** | ~2.7 GB ONNX (external data), ~73ms/batch on A40 |
| **Total model size** | ~7.1 GB (vision + text encoders) |

## Important Notes

- **No attention_mask**: SigLIP2 was trained with padding tokens included (no masking). The text encoder takes **only `input_ids`**. The SigLIP2 processor does not return an `attention_mask` field. Passing a fabricated attention_mask destroys cross-modal alignment.
- **No transformer-specific ONNX fusions**: Do not use `onnxruntime.transformers.optimizer` with `model_type="vit"` or `"bert"` — these assume standard BERT/ViT attention patterns and corrupt SigLIP2's architecture. Only `"basic"` ORT optimization level is safe.
- **No torch in the server container**: The Triton container avoids torch/torchvision because torch's CUDA runtime conflicts with ONNX Runtime's CUDA EP. Server-side preprocessing uses PIL + numpy. Client-side uses `SiglipImageProcessor` (PIL-based, not the torchvision Fast variant).

## Features

- ONNX-optimized models with offline graph optimizations (constant folding, dead node elimination)
- Mixed-precision FP16 support with numerically sensitive ops kept in FP32
- Dynamic batching on all models (encoders, preprocessing, tokenizer) with model warmup
- Response caching for repeated text queries
- Docker containerization with NVIDIA Triton Inference Server (GPU-enabled)
- Python client library (`siglip2-triton-client`) with sync and async gRPC clients, retry with exponential backoff
- Standalone client-side `ImagePreprocessor` and `TextTokenizer` (bundled, zero-config) for direct encoder access and bulk indexing
- Ensemble pipelines: raw image/text in, normalized embeddings out

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   Docker Container                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │            Triton Inference Server                  │  │
│  │                                                    │  │
│  │  ┌─────────────────┐    ┌─────────────────────┐   │  │
│  │  │ Image Pipeline   │    │ Text Pipeline        │   │  │
│  │  │                 │    │                     │   │  │
│  │  │ 1. Preprocess   │    │ 1. Tokenizer        │   │  │
│  │  │    (CPU, x4)    │    │    (CPU, x4)        │   │  │
│  │  │ 2. ViT Encoder  │    │ 2. Text Encoder     │   │  │
│  │  │    (GPU, ONNX)  │    │    (GPU, ONNX)      │   │  │
│  │  └─────────────────┘    └─────────────────────┘   │  │
│  │                                                    │  │
│  │  Dynamic Batching ∙ CUDA EP ∙ Response Cache       │  │
│  │  HTTP (8000) │ gRPC (8001) │ Metrics (8002)       │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Export Models to ONNX

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Export with default settings (FP32, normalized embeddings)
python -m onnx_export

# Export with mixed-precision FP16
python -m onnx_export --fp16

# See all options
python -m onnx_export --help
```

#### Export Options

| Flag | Default | Description |
|------|---------|-------------|
| `--model_name` | `google/siglip2-giant-opt-patch16-384` | HuggingFace model name or path |
| `--output_dir` | `model_repo` | Output directory for Triton model repository |
| `--opset` | `18` | ONNX opset version |
| `--fp16` | `False` | Mixed-precision FP16 (LayerNorm/Softmax stay FP32) |
| `--normalize` | `True` | L2 normalization on output embeddings |
| `--image_size` | `384` | Vision encoder input size |
| `--validate` | `True` | Cross-modal similarity validation after export |

The export pipeline applies:
1. ONNX export with dynamic batch axes
2. ONNX Runtime offline graph optimizations via CUDA EP (constant folding, dead node elimination)
3. Optional mixed-precision FP16 conversion

#### Optimizations Applied

- **ORT offline graph optimization** — constant folding and redundant node elimination baked into the exported model at export time via CUDA EP
- **CUDA EP runtime** — GPU kernel selection and memory optimization
- **L2 normalization** — baked into the ONNX model (no post-processing needed)
- **Dynamic batching** — Triton batches concurrent requests for higher throughput
- **Triton runtime optimization disabled** (`level: 0`) — avoids redundant re-optimization at model load since the graph is already optimized offline

### 2. Deploy with Triton

```bash
# Build the Docker image
./docker/build.sh

# Start the server
./docker/deploy.sh
```

The server exposes:
- **HTTP**: `http://localhost:8000`
- **gRPC**: `localhost:8001`
- **Metrics**: `http://localhost:8002/metrics`

## Model Repository Structure

```
model_repo/
├── ensemble_image_model/              # Image ensemble: preprocess -> encode
│   ├── 1/
│   └── config.pbtxt
├── ensemble_text_model/               # Text ensemble: tokenize -> encode
│   ├── 1/
│   └── config.pbtxt
├── image_preprocessing/               # Resize + normalize (CPU, 4 instances)
│   ├── 1/
│   │   ├── model.py
│   │   └── preprocessor_config/
│   └── config.pbtxt
├── siglip2_vision_encoder_onnx/       # Vision encoder (GPU, dynamic batching)
│   ├── 1/
│   │   └── model.onnx
│   └── config.pbtxt
├── siglip2_text_encoder_onnx/         # Text encoder (GPU, dynamic batching)
│   ├── 1/
│   │   └── model.onnx
│   └── config.pbtxt
└── tokenizer/                         # Tokenizer (CPU, 4 instances, response-cached)
    ├── 1/
    │   ├── model.py
    │   └── tokenizer/
    └── config.pbtxt
```

### Triton Configuration Highlights

- **Dynamic batching** on all models including preprocessing and tokenizer (`max_batch_size: 32`)
- **CUDA Execution Provider** with memory pattern/reuse enabled
- **Offline graph optimization** at export time via CUDA EP (GPU-specific fusions baked in, runtime level 0)
- **Response caching** on tokenizer model for repeated text queries (512MB server-side cache)
- **Model warmup** on both encoders to eliminate cold-start latency
- **Multiple CPU instances** for preprocessing (4) and tokenization (4) to avoid bottlenecking the GPU

## Benchmark Results

Tested on NVIDIA A40 (48GB) with `google/siglip2-giant-opt-patch16-384`.

### Single-Request Latency (1 concurrent user, 50 requests)

| Model | Mean (ms) | P50 (ms) | P95 (ms) | RPS |
|---|---|---|---|---|
| Ensemble Image Model | 180.3 | 179.6 | 188.9 | 5.5 |
| Client Preprocess + Encoder | 120.0 | 115.8 | 132.9 | 8.3 |
| Vision Encoder Only | 105.6 | 105.4 | 106.2 | 9.5 |
| Ensemble Text Model | 73.3 | 72.8 | 77.4 | 13.6 |
| Client Tokenize + Encoder | 72.9 | 72.6 | 75.3 | 13.7 |
| Text Encoder Only | 72.7 | 72.0 | 76.8 | 13.7 |

### High Concurrency (200 concurrent users, 200 requests)

| Model | Mean (ms) | P50 (ms) | P95 (ms) | P99 (ms) | RPS |
|---|---|---|---|---|---|
| Ensemble Image Model | 4735.7 | 4210.3 | 7654.9 | 7666.7 | 25.8 |
| Client Preprocess + Encoder | 4914.7 | 4925.8 | 7764.5 | 7783.3 | 24.4 |
| Vision Encoder Only | 4912.2 | 4268.1 | 7777.3 | 7797.6 | 24.6 |
| Ensemble Text Model | 231.4 | 249.7 | 332.3 | 333.2 | 554.1 |

### Key Findings

- **Image preprocessing overhead**: ~75ms per image (41% of single-request latency). Client-side preprocessing with `ImagePreprocessor` gives 1.7x throughput improvement at low concurrency.
- **Text tokenization overhead**: <1ms per text (negligible). At low concurrency (20 users), the ensemble is faster with tighter tail latency (~70ms p95 vs ~90ms). At high concurrency (200-500 users), client tokenizer + direct encoder wins by ~1-7% by skipping the ensemble orchestration overhead. Both converge to ~420 RPS when GPU-saturated.
- **At high concurrency (200+ users)**: GPU becomes the bottleneck — all paths converge regardless of preprocessing/tokenization location.

## Python Client Library

### Installation

```bash
# Core (includes TextTokenizer, all Triton clients)
pip install siglip2-triton-client

# With ImagePreprocessor (adds transformers + pillow)
pip install siglip2-triton-client[preprocessing]
```

### Synchronous Usage

```python
import numpy as np
from PIL import Image
from siglip2_triton_client import (
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
)

# Image encoding (raw image in, normalized embedding out)
image_client = TritonEnsembleImageClient()
image = np.array(Image.open("photo.jpg"), dtype=np.uint8)
images = np.stack([image], axis=0)  # batch of 1
image_embeddings = image_client.predict(images)  # shape: (1, 1536)

# Text encoding
text_client = TritonEnsembleTextClient()
text_embeddings = text_client.predict(["a photo of a cat"])  # shape: (1, 1536)

# Cosine similarity (embeddings are already L2-normalized)
similarity = image_embeddings @ text_embeddings.T
```

### Client-Side Preprocessing (Direct Encoder Access)

For lower latency or bulk indexing, preprocess/tokenize client-side and send directly to the encoder, bypassing the ensemble. The simplest way is the preprocessed clients which handle everything internally:

```python
from siglip2_triton_client import TritonPreprocessedImageClient, TritonPreprocessedTextClient

# Image: accepts PIL images / numpy arrays directly
image_client = TritonPreprocessedImageClient()
image_embeddings = image_client.predict(Image.open("photo.jpg"))
image_embeddings = image_client.predict([img1, img2, img3])  # batch

# Text: accepts strings directly
text_client = TritonPreprocessedTextClient()
text_embeddings = text_client.predict(["a photo of a cat", "a red car"])
```

For more control (e.g., reusing preprocessed data or custom batching), use the standalone classes with the direct encoder clients:

```python
from siglip2_triton_client import ImagePreprocessor, TextTokenizer, TritonImageClient, TritonTextClient

# Image: manual preprocessing + direct encoder
preprocessor = ImagePreprocessor()
client = TritonImageClient()

for batch in preprocessor.batch_iter(all_images, batch_size=32):
    embeddings = client.predict(batch)

# Text: manual tokenization + direct encoder
tokenizer = TextTokenizer()
client = TritonTextClient()

for batch in tokenizer.batch_iter(all_texts, batch_size=32):
    embeddings = client.predict(batch)
```

### Asynchronous Usage

```python
from siglip2_triton_client import AsyncTritonEnsembleTextClient

async with AsyncTritonEnsembleTextClient() as client:
    embeddings = await client.predict(["a photo of a cat"])
    is_ready = await client.ping()
```

### Available Clients

| Client | Input | Output | Pipeline |
|--------|-------|--------|----------|
| `TritonPreprocessedImageClient` | PIL/numpy images | `float32 [N, 1536]` | Client preprocess + direct encoder |
| `TritonPreprocessedTextClient` | `str` / `list[str]` | `float32 [N, 1536]` | Client tokenize + direct encoder |
| `TritonImageClient` | `float32 [N, 3, 384, 384]` | `float32 [N, 1536]` | Direct vision encoder |
| `TritonTextClient` | `int64 [N, 64]` | `float32 [N, 1536]` | Direct text encoder |
| `TritonEnsembleImageClient` | `uint8 [N, H, W, 3]` | `float32 [N, 1536]` | Server preprocess + encode |
| `TritonEnsembleTextClient` | `list[str]` | `float32 [N, 1536]` | Server tokenize + encode |

Each has an async variant (e.g., `AsyncTritonPreprocessedImageClient`) that uses persistent gRPC channels.

### Standalone Preprocessing

| Class | Description |
|-------|-------------|
| `ImagePreprocessor` | `SiglipImageProcessor`-based, accepts PIL/numpy, returns `float32 [N, 3, 384, 384]` |
| `TextTokenizer` | Bundled `tokenizer.json` (zero-config), accepts str/list[str], returns `int64 [N, 64]` |

Both support `batch_iter(items, batch_size=32)` for memory-bounded bulk processing.

### Client Configuration

```python
from siglip2_triton_client import TritonClientSettings

settings = TritonClientSettings(
    triton_server_url="localhost:8001",     # gRPC endpoint
    triton_server_ssl=False,                # Enable for TLS
    triton_server_auth_token="my-token",    # Optional Bearer token
    max_retries=3,                          # Retry transient gRPC failures
    retry_base_delay=0.1,                   # Base delay for exponential backoff
)
client = TritonEnsembleTextClient(settings=settings)
```

## Dependencies

| Group | Install | Includes |
|-------|---------|----------|
| **Core** | `pip install siglip2-triton-client` | numpy, tritonclient[grpc], tokenizers, pydantic |
| **Preprocessing** | `pip install siglip2-triton-client[preprocessing]` | + transformers, pillow |
| **Dev** | `uv pip install -e ".[dev]"` | + torch, onnx, onnxruntime-gpu, optimum |
| **Test** | `uv pip install -e ".[test]"` | + pytest, pillow |

## Docker

### Build

```bash
./docker/build.sh
# Or manually:
docker build -f ../../docker/Dockerfile.siglip2-triton -t siglip2-triton:latest .
```

### Docker Compose

```bash
# CPU only:
docker compose -f infra/compose/siglip2-triton.yml up -d

# With GPU:
docker compose -f infra/compose/siglip2-triton.yml -f infra/compose/siglip2-triton-gpu.yml up -d
```
