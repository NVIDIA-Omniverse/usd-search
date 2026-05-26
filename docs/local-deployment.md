# Local Deployment — Configuration Recipes

The default deployment runs USDSearch against NVIDIA's public S3 bucket
(`omniverse-content-production`) with **SigLIP2 on GPU** (via Triton)
and the **GPU-accelerated renderer enabled** for thumbnail generation.
It is brought up by combining the base compose file with the
`docker-compose.gpu-plugins.yml` overlay:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu-plugins.yml \
  up -d --build
```

Requirements: an NVIDIA GPU on the host and
[`nvidia-container-toolkit`](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
configured so `docker run --gpus all` works.

Every recipe below layers additional `-f <overlay>` files and
environment variables on top of this default. Run them from the repo
root.

## CPU-only fallback (no GPU)

If you do not have an NVIDIA GPU on the host, drop the
`docker-compose.gpu-plugins.yml` overlay. SigLIP2 then runs on CPU
(slower indexing) and the renderer is not started, so new thumbnails are
not generated. Embeddings remain real — only indexing throughput and
thumbnail generation are affected.

```bash
docker compose -f docker-compose.yml up -d --build
```

## Custom S3 bucket (your own data)

Index a private or third-party S3 bucket instead of the NVIDIA public
default.

```bash
STORAGE_BACKEND_TYPE=s3 \
S3_STORAGE_BUCKET_NAME=my-bucket \
S3_STORAGE_AWS_ACCESS_KEY_ID=AKIA... \
S3_STORAGE_AWS_SECRET_ACCESS_KEY=... \
S3_STORAGE_REGION=us-east-1 \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu-plugins.yml \
  up -d --build
```

For a public bucket the credentials can be left unset — but leave the
variables **unset entirely**, not empty strings. The compose files
forward them with YAML null pass-through so unset vars are dropped from
the container; `S3_STORAGE_AWS_ACCESS_KEY_ID=""` would break anonymous
access.

## Local filesystem (assets on this machine)

Mount a directory of USD files directly through an S3-compatible
filesystem gateway. API responses round-trip absolute local paths.

```bash
LOCAL_FS_DATA_DIR=/path/to/my-assets \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.local-fs.yml \
  -f docker-compose.gpu-plugins.yml \
  up -d --build
```

## Enable VLM auto-tagging

Run the metadata-generation workers that caption every asset with a
Vision-Language Model. Required for the best keyword-side search
quality.

Pick one provider via `METADATA_GENERATION_VLM_SERVICE` and export its
matching API key on the host shell:

| Provider | `METADATA_GENERATION_VLM_SERVICE` | Required env var |
|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY` |
| NVIDIA Inference Hub | `inference_hub` | `INFERENCE_HUB_API_KEY` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| Google | `google` | `GOOGLE_API_KEY` |
| Qwen / Alibaba | `qwen_alibaba` | `QWEN_API_KEY` |
| Azure OpenAI | `azure_openai` | `AZURE_OPENAI_API_KEY` |
| Mistral | `mistralai` | `MISTRAL_API_KEY` |
| Self-hosted NIM | `nim` | `NIM_API_KEY` |

```bash
METADATA_GENERATION_VLM_SERVICE=openai \
OPENAI_API_KEY=sk-... \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu-plugins.yml \
  -f docker-compose.vlm-plugins.yml \
  up -d --build
```

## Beyond docker compose

For Kubernetes / Helm deployments, or for a step-by-step assistant that
walks through these choices interactively, run `/deploy-usdsearch` from
Claude Code (or `$deploy-usdsearch` from Codex). It branches on local
docker compose vs. Helm on a cluster and prompts for the same
backend / GPU / VLM / credential choices, accepting env-var names
only.
