# Support Matrix

Hardware and software requirements for running USD Search. For the quick
local docker-compose requirements, see the top-level
[`README.md`](../README.md#requirements) instead — this page covers
production Kubernetes/Helm sizing.

## Models

| Component | Model |
|---|---|
| Embedding | SigLIP2 (see [`models-and-config.md`](models-and-config.md)) |
| Vision auto-tagging / result validation (optional plugins) | Any OpenAI-compatible LLM/VLM endpoint you configure — see [`models-and-config.md`](models-and-config.md) |

## Hardware

| Component | Requirement |
|---|---|
| GPUs | Minimum 2 — one for rendering, one for inference. |
| GPU architecture | A10g, A100, L40, or H100. |
| GPU driver | `595.58.03` or higher — a lower version causes the embedding service to silently fall back to CPU even with the GPU Operator installed (see `helm/usdsearch/README.md`'s FAQ, "Embedding service falls back to CPU with the GPU Operator installed"). |
| CPU cores | 32 minimum. |
| System RAM | 128 GB minimum. |

Scale beyond these minimums per your corpus size and concurrency using
[`performance.md`](performance.md) and the Helm chart's `resources` blocks
(see `helm/usdsearch/README.md`, "Resources").

## Software

| Component | Requirement |
|---|---|
| Kubernetes | Any cluster with RBAC enabled (required for GPU-based rendering jobs) — see `helm/usdsearch/README.md` Prerequisites. |
| Helm | `>= 3.0.0` |
| GPU exposure | [NVIDIA k8s device plugin](https://github.com/NVIDIA/k8s-device-plugin), or the [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html) (which includes it) |
| Metrics server | Optional — required only for Horizontal Pod Autoscaling |
| Prometheus Operator + Grafana | Optional — required only for the built-in monitoring dashboards. [Kube Prometheus Stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack) satisfies both. See `helm/usdsearch/README.md`'s Monitoring section. |

## Storage backends

- Amazon S3 and S3-compatible providers (via s3proxy)
- Omniverse Nucleus
- Omniverse Storage API
- Local filesystem (docker-compose / evaluation only, via s3proxy)

See [`architecture.md`](architecture.md) for how these fit into the overall
system, and `helm/usdsearch/README.md`'s Deployment section for per-backend
setup.
