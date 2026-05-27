

# **DeepSearch Vision Endpoint**


## **Install**

```bash
uv pip install -e ".[langfuse,dev,test,lint]"
```

### **Optional CLIP Dependencies**

The SigLIP2 CLIP triton client module is optional and can be installed separately:

```bash
# Install with SigLIP2 support
uv pip install -e "[siglip2]"
```

## **Metadata Generation**

By passing a set of images from various camera angles of a 3D asset, we are able to generate a detailed description of the object. This text description can be used to generate relevant metadata for fuzzy matching using DeepSearch, or to produce new relationships between nodes in AGS.

To use Metadata Generation, all you need to do is specify the environment variables:


### **Environment Variables**

> **Note (USD Search deployments):** in the deepsearch-monitor
> `metadata_generation` worker, the same setting is read as
> `METADATA_GENERATION_VLM_SERVICE` (and the worker uses `MetadataGenerationConfig`
> whose `env_prefix="metadata_generation_"`). Setting bare `VLM_SERVICE` does
> nothing for that worker — see [Known Pitfalls](../../CLAUDE.md#known-pitfalls)
> for the full explanation. The bare `VLM_SERVICE` env var below applies
> when instantiating `MetadataGeneration` directly as a library.

Select which VLM Service you would like to use (defaults to Inference Hub):

```bash
export VLM_SERVICE=inference_hub
```

Pass your API Key - use the VLM Service name as a prefix, followed by _API_KEY:

```bash
export INFERENCE_HUB_API_KEY=YOUR_API_KEY
```

(Optional) Select which model - use the VLM Service name as a prefix, followed by _MODEL:

```bash
export INFERENCE_HUB_MODEL=gcp/google/gemini-3-flash-preview
```


(Optional) Specify the custom metadata fields that you want to be generated (defaults to [metadata_fields.yaml](vision_endpoint/metadata/metadata_fields.yaml)):

```bash
export METADATA_YAML_FILEPATH=metadata_fields.yaml
```

(Optional) specify your own image prompt by passing it via text file:
```bash
export METADATA_PROMPT_FILEPATH=metadata_prompt.txt
```

##
## **Supported VLM Services**

| VLM Service            | Default Model            | Notes                                            |
|------------------------|-------------------------|--------------------------------------------------|
| `openai`               | `gpt-4o`                | - |
| `azure_openai`         | `gpt-4o-20241120`       | For Azure OpenAI Service users                    |
| `anthropic`            | `claude-3-5-sonnet-latest` | -                    |
| `google`               | `gemini-2.5-pro`          | -             |
| `qwen`                 | `Qwen/Qwen3.5-35B-A3B-FP8` | Local SGLang server (OpenAI-compatible API) |
| `qwen_alibaba`         | `qwen3-vl-235b-a22b-instruct` | Alibaba DashScope cloud API |
| `mistralai`            | `pixtral-large-latest`  | - |
| `nim`                  | `meta/llama-4-maverick-17b-128e-instruct` | NVIDIA NIM |
| `inference_hub`        | `gcp/google/gemini-3-flash-preview` | NVIDIA Inference Hub |


##

### **For a full example, please check out the [Metadata Generation Notebook](notebooks/metadata_generation.ipynb).**



After specifying the Environment Variables, instantiate the `MetadataGeneration` class:

```python
from vision_endpoint import MetadataGeneration

os.environ['VLM_SERVICE'] = "inference_hub"
os.environ['INFERENCE_HUB_API_KEY'] = "API_KEY"

metadata_generation = MetadataGeneration()
```

and pass base64 encoded images to it:

```python
metadata: BaseModel = metadata_generation.generate(
    base64_images=electric_guitar_images
)
```

<img src="docs/guitar2.png" width="450">



All you need is a yaml file with your field names and instructions (as shown above with [metadata_fields.yaml](vision_endpoint/metadata/metadata_fields.yaml)), and point to it with the environment variable:
```python
export METADATA_YAML_FILEPATH=metadata_fields.yaml
```


## **Customizable Image Prompt**


You can specify your own image prompt by creating a [image_prompt.txt](vision_endpoint/metadata/metadata_prompt.txt) file, and pointing to it with the environment variable:
```python
export METADATA_PROMPT_FILEPATH=metadata_prompt.txt
```

## **Avoid output parsing and pass your metadata fields via prompt**

Simply set the `parse_output` input variable of [MetadataGeneration](vision_endpoint/metadata/metadata_generation.py#L126) to `False`:

<img src="docs/parse.png" width="250">




## **Using it a as a simple LLM**

** Please check out the [LLM Notebook](notebooks/llm.ipynb).**

Simply leave the `base64_images` input variable blank, and solely use `prompt`:

<img src="docs/llm.png" width="700">

---

## **Validation**

Validate whether a query (text or image) matches reference images of a 3D asset using VLM-powered analysis.

### **For full examples, see the [Validation Notebook](notebooks/validation.ipynb) and [Qwen Validation Example](examples/qwen_validation_example.ipynb).**

### Quick Start

```python
from vision_endpoint import Validation, ValidationConfig
from vision_endpoint.vlm import VLMService

# Initialize with Inference Hub (default)
validator = Validation()

# Or use the local Qwen 3.5 model
config = ValidationConfig(vlm_service=VLMService.qwen, max_tries=2)
validator = Validation(config=config)

# Or use Azure OpenAI
config = ValidationConfig(vlm_service=VLMService.azure_openai)
validator = Validation(config=config)

# Text query validation
is_match = validator.validate(
    query="red electric guitar",
    reference_images=["front.png", "side.png", "back.png"]
)

# Image query validation
is_match = validator.validate(
    query="query_image.png",
    reference_images=reference_images
)

# Get detailed results with confidence and reasoning
result = validator.validate(
    query="acoustic guitar",
    reference_images=reference_images,
    return_detailed=True,
    asset_caption="Electric guitar with solid body",
)
print(f"Match: {result.is_match}, Confidence: {result.confidence}")
print(f"Reasoning: {result.reasoning}")
```

### Environment Variables

```bash
# Inference Hub (default)
export VLM_SERVICE=inference_hub
export INFERENCE_HUB_API_KEY=YOUR_API_KEY

# Local Qwen 3.5 (SGLang)
export VLM_SERVICE=qwen
export QWEN_BASE_URL=http://localhost:8000/v1
export QWEN_MODEL=Qwen/Qwen3.5-35B-A3B-FP8

# Azure OpenAI
export VLM_SERVICE=azure_openai
export AZURE_OPENAI_API_KEY=YOUR_API_KEY
export AZURE_OPENAI_BASE_URL=YOUR_ENDPOINT
```

---

## **CLIP Triton Client**

Generate image and text embeddings using CLIP models served via Triton Inference Server. By default, preprocessing (image transforms, text tokenization) happens client-side before sending to the encoder model. Pass `use_ensemble_model=True` to use server-side ensemble models instead.

### **For a full example, see the [Embeddings Notebook](notebooks/embeddings.ipynb).**

### Installation

```bash
# SigLIP2 support
uv pip install -e ".[siglip2]"
```

### Quick Start

```python
from vision_endpoint.clip_triton_client import SigLIP2, SigLIP2Config
from PIL import Image

# Configure and initialize
config = SigLIP2Config(triton_server_url="localhost:8001")
clip = SigLIP2(clip_config=config)

# Generate image embeddings (client-side preprocessing by default)
images = [Image.open("image1.png"), Image.open("image2.png")]
image_embeddings = clip.embed_images(images)

# Generate text embeddings (client-side tokenization by default)
texts = ["red guitar", "blue car"]
text_embeddings = clip.embed_texts(texts)

# Use server-side ensemble models instead
image_embeddings = clip.embed_images(images, use_ensemble_model=True)
text_embeddings = clip.embed_texts(texts, use_ensemble_model=True)

# Async support
image_embeddings = await clip.aembed_images(images)
text_embeddings = await clip.aembed_texts(texts)
```

### Environment Variables

```bash
export SIGLIP2_TRITON_SERVER_URL=localhost:8001
export SIGLIP2_TRITON_SERVER_AUTH_TOKEN=YOUR_TOKEN  # optional
export SIGLIP2_TRITON_SERVER_SSL=false              # optional
export SIGLIP2_MAX_WORKERS=8                        # max concurrent async requests (default: 8)
export SIGLIP2_BATCH_SIZE=4                         # images per request batch (default: 4)
```

| CLIP Service | Description |
|--------------|-------------|
| `siglip2`    | Google's SigLIP2 model |

### Batch Chunking vs Concurrent Chunking

When embedding large numbers of images (e.g. 10,000+), two mechanisms work together to maximize throughput:

**Batch Chunking** (`batch_size`)

Splits images into fixed-size chunks before sending to Triton. Each chunk is a single gRPC request containing multiple images stacked into one tensor.

```
10,000 images → 2,500 chunks of 4 images → 2,500 gRPC requests
```

This is necessary because:
- Triton has a `max_batch_size` limit per request — sending all images at once will be rejected
- A single massive request would exceed gRPC message size limits and GPU memory
- Smaller batches allow Triton to pipeline execution more efficiently

Set `batch_size` to match your Triton server's `max_batch_size` for best results.

**Concurrent Chunking** (`max_workers`)

Controls how many batch chunks are in-flight simultaneously using an `asyncio.Semaphore`. Only applies to the async path (`aembed_images`).

```
2,500 chunks, max_workers=8 → 8 chunks in-flight at any time
```

This is advantageous because:
- Keeps the GPU pipeline saturated — while one batch is being computed, the next is already being transferred
- Prevents server overload — without a limit, all 313 requests would fire at once, causing `RESOURCE_EXHAUSTED` errors
- Allows tuning to your hardware — more GPU instances can handle more concurrent requests

**How they work together:**

```
10,000 images
    ├── split into 2,500 chunks of 4
    └── send 8 chunks concurrently (semaphore)
            ├── chunk 1 → preprocess + infer → embeddings
            ├── chunk 2 → preprocess + infer → embeddings
            ├── ...
            └── chunk 8 → preprocess + infer → embeddings
            ... (next chunks start as earlier ones complete)
    └── concatenate all results
```

**Tuning guide:**

| Parameter | Controls | Tune based on |
|-----------|----------|---------------|
| `batch_size` | Images per request | Triton's `max_batch_size` config |
| `max_workers` | Concurrent requests | GPU count and utilization (`nvidia-smi`) |

- If you see `RESOURCE_EXHAUSTED` errors → lower `max_workers`
- If GPU utilization is low → raise `max_workers`
- If requests are rejected for being too large → lower `batch_size`

**Image Embedding:**

| Path | RPS | Mean Latency | P50 | P95 | P99 |
|------|-----|-------------|-----|-----|-----|
| Preprocessed (client-side) | 18.2 | 5,279ms | 5,292ms | 6,524ms | 7,042ms |
| Ensemble (server-side) | 18.5 | 5,211ms | 5,467ms | 6,235ms | 6,674ms |

**Text Embedding:**

| Path | RPS | Mean Latency | P50 | P95 | P99 |
|------|-----|-------------|-----|-----|-----|
| Preprocessed (client-side) | 409.8 | 231ms | 237ms | 282ms | 286ms |
| Ensemble (server-side) | 410.6 | 232ms | 233ms | 255ms | 309ms |

Both paths perform identically under load. The preprocessed path offloads preprocessing to the client, reducing server compute. Use ensemble when client resources are constrained.

Run the benchmark: `SIGLIP2_TRITON_SERVER_URL=localhost:8001 python tests/bench_clip.py`

### Connection Management and Fault Tolerance

The async client uses a persistent gRPC channel that is lazily initialized via `connect()`.

**Why `connect()` is needed:**
- The async gRPC channel (`grpc.aio`) must be created inside a running event loop, so it cannot be set up in `__init__`
- `connect()` is called automatically before async operations (`aembed_images`, `aembed_texts`, `aping`)
- It is idempotent — calling it multiple times is safe; subsequent calls return immediately if already connected

**What happens if Triton goes down:**

The client has built-in retry logic with exponential backoff for transient failures:

| Status Code | Meaning | Retried? |
|---|---|---|
| `UNAVAILABLE` | Server unreachable / connection refused | Yes |
| `DEADLINE_EXCEEDED` | Request timed out | Yes |
| `RESOURCE_EXHAUSTED` | Server overloaded | Yes |

Retry behavior: up to 3 retries with exponential backoff (0.1s, 0.2s, 0.4s). If all retries fail, a `CLIPException` is raised.

The gRPC channel handles reconnection internally — if Triton restarts, the existing channel will automatically reconnect on the next request without needing to call `connect()` again or recreate the client.
