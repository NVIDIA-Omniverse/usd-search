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

USD Search talks to **any OpenAI-API-compatible LLM/VLM serving system** and
ships configured to use NVIDIA Inference Hub by default. You set **one
connection** — a key and a base URL — that every role (search, metadata,
validation) reuses:

| Env var | Purpose |
|---|---|
| `USDSEARCH_LLM_API_KEY` | Bearer key for the OpenAI-compatible endpoint. |
| `USDSEARCH_LLM_BASE_URL` | Base URL. Defaults to the shipped endpoint (NVIDIA Inference Hub). Point it at any OpenAI-API server — vLLM, LiteLLM, Azure OpenAI, OpenAI, etc. |

Each role then only picks a **model** on that shared connection — e.g.
`USDSEARCH_VISION_METADATA_MODEL` for the metadata workers.

```bash
USDSEARCH_LLM_API_KEY=sk-... \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gpu-plugins.yml \
  -f docker-compose.vlm-plugins.yml \
  up -d --build
```

## Explorer web UI

The Explorer is a static React SPA served by bitnami nginx (`/app` on `:8080`).
Enable it in the local stack with the WebUI overlay; the gateway serves it at
`/ui` and routes the APIs:

```bash
docker compose -f docker-compose.yml -f docker-compose.web-ui.yml up -d --build
# open http://<host>:8080/ui/
```

For the full picture of every container image — what each is, how it's built,
and where it's published — see [`docs/containers.md`](containers.md).

## Beyond docker compose

For Kubernetes / Helm deployments, or for a step-by-step assistant that
walks through these choices interactively, run `/deploy-usdsearch` from
Claude Code (or `$deploy-usdsearch` from Codex). It branches on local
docker compose vs. Helm on a cluster and prompts for the same
backend / GPU / VLM / credential choices, accepting env-var names
only.

## Gateway routes & smoke tests

The nginx gateway (config at `infra/quickstart/gateway.conf`, or
`gateway.web-ui.conf` with the WebUI overlay) proxies:

- `/` -> 302 to `/docs/` (or `/ui/` with the WebUI overlay)
- `/docs/` -> static Swagger UI serving the committed
  `helm/usdsearch/docs/openapi.json` (regenerate via
  `scripts/build-openapi-docs.sh`)
- `/search`, `/search_hybrid`, `/llm_parse/...`, `/vlm_validate/...`,
  `/images`, `/download/...` -> deepsearch-api
- `/info`, `/process` -> info-endpoint
- `/asset_graph/`, `/dependency_graph` -> asset-graph-service

`./scripts/quickstart-smoke.sh` exercises every proxied endpoint
(PASS/FAIL per route) once the stack reports healthy. It honors `BASE`
(gateway URL), `ASSET_GRAPH_TIMEOUT` (seconds to wait for the first graphed
scene, default 15), `BASIC_AUTH=user:password` (required for Nucleus mode,
where the gateway gates API routes with the stack's `OV_USERNAME` /
`OV_PASSWORD`), and `WEB_UI=on|off`.

Tip: `/search` and `/search_hybrid` accept `return_root_prims=true` — a
non-empty `root_prims` on a hit proves the asset-graph worker finished that
asset, which is handy for deterministically detecting graphed scenes.

## End-to-end test harness

`ci/quickstart/` ships a parametric runner (`run_tests_quickstart.sh`) and a
sequential driver (`run_all.sh`) covering six configs: `public-s3`,
`public-s3-vlm`, `private-s3`, `private-s3-vlm`, `nucleus`, `nucleus-vlm`.
Each brings up base + GPU plugins (+ VLM overlay where applicable) with
`docker compose up -d --wait --build`, polls `/search` until an asset is
indexed, runs the smoke script with bumped timeouts, and tears down with
`down -v` on exit. Not wired into GitLab CI yet (needs GPU runners).
