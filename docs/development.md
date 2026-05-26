# Development guide

Everything you need to build and run USDSearch services from source. The top-level README covers the agent-driven and one-command Docker Compose paths; this file is for contributors and operators who want the details.

## Repository layout

```
usdsearch/
├── packages/
│   ├── search-utils/           # Shared infrastructure (storage clients, OpenSearch, Redis Streams, caching)
│   ├── vision-endpoint/        # VLM/embedding/metadata utilities (LangChain, CLIP, SigLIP2)
│   ├── ngsearch-backend/       # SigLIP2/CLIP + OpenSearch search backend
│   ├── deepsearch-utils/       # Plugin pipeline support utilities
│   ├── cache/                  # Redis Stream / job queue API
│   ├── plugins/                # Asset processing plugins (thumbnails, embeddings, metadata)
│   ├── usdsearch/              # Admin CLI (usdsearch.admin.tools)
│   ├── siglip2-triton-client/  # gRPC client for the SigLIP2 Triton server
│   └── asset-graph-client/     # Generated OpenAPI client for asset-graph-service
├── services/
│   ├── deepsearch_api/         # User-facing search API (V2/V3 FastAPI, hybrid vector+text, VLM validation)
│   ├── deepsearch-crawler/     # Storage scanner → Redis stream
│   ├── deepsearch-monitor/     # Asset processing worker
│   ├── info-endpoint/          # Asset status + on-demand processing REST API
│   ├── asset-graph/            # Neo4j USD scene graph service
│   ├── storage/                # NGSearch HTTP storage service
│   ├── crawlers/               # Tag + indexing crawlers
│   ├── siglip2-triton/         # Triton Inference Server for SigLIP2 ONNX models
│   ├── rendering-job/          # GPU USD/MDL renderer (Omniverse Kit subprocess workers)
│   ├── asset-graph-builder/    # Kit-based USD scene graph builder
│   └── explorer/               # React 18 + Chakra UI search front-end (sample WebUI)
├── docker/                     # Dockerfiles
├── infra/compose/              # Docker Compose files for local dev and CI
├── ci/                         # Per-service CI shell scripts
└── docs/                       # Architecture docs and migration proposals
```

`services/rendering-job` and `services/asset-graph-builder` are **not** uv workspace members due to dependency conflicts (see `pyproject.toml` for details). `services/explorer` is a Node.js project and is also excluded.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager and workspace tool
- Internet access to [PyPI](https://pypi.org/) (all dependencies are publicly available)
- [buf](https://buf.build/) — for regenerating protobuf/gRPC clients (optional, only needed when IDL changes)
- `7z` (`apt install p7zip-full` on Debian/Ubuntu, `brew install p7zip` on macOS) — needed by the `search-utils` build step below
- Docker + Docker Compose — for local service stacks

## Installation

```bash
# 1. Fetch the pre-compiled Omniverse protobuf packages that `search-utils`
#    bundles into its wheel. Required before the first `uv sync` and any
#    time those packages need refreshing. Pulls ~5 packages from a public
#    NVIDIA CloudFront CDN (no credentials needed).
./build/build_search_utils.sh

# 2. Install all workspace members in editable mode
uv sync

# Install a single package only
uv sync --package search-utils
uv sync --package deepsearch-api
```

The first step populates `packages/search-utils/_build/`, which `hatchling` force-includes into the wheel via `[tool.hatch.build.targets.wheel.force-include]` in `packages/search-utils/pyproject.toml`. Skipping it produces `FileNotFoundError: Forced include not found: ..._build/discovery.client.py/omni` during `uv sync`. The same script runs in `docker/Dockerfile.usdsearch`, so local and container builds share the mechanism.

## Running services

All services ship in a single Docker image (`docker/Dockerfile.usdsearch`). Override the command at launch to select the service:

```bash
docker build -f docker/Dockerfile.usdsearch -t usdsearch:latest .

# DeepSearch API
docker run -e ... usdsearch:latest uvicorn deepsearch_api.main:app --host 0.0.0.0 --port 8000

# DeepSearch crawler
docker run -e ... usdsearch:latest python -m deepsearch_crawler.main

# DeepSearch monitor worker
docker run -e ... usdsearch:latest python -m monitor.src.monitor_worker

# Info endpoint
docker run -e ... usdsearch:latest uvicorn info_endpoint.src.main:app --host 0.0.0.0 --port 8000

# Asset graph service
docker run -e ... usdsearch:latest python -m asset_graph_service.api.uvicorn

# NGSearch storage cron
docker run -e ... usdsearch:latest python -m storage.src.run_cron

# Tag / indexing crawlers
docker run -e ... usdsearch:latest python -m crawlers.src.tag_crawler_cron
docker run -e ... usdsearch:latest python -m crawlers.src.indexing_cron
```

Separate images exist for services with conflicting dependencies:
- `docker/Dockerfile.siglip2-triton` — Triton Inference Server for SigLIP2 ONNX models (build context: `services/siglip2-triton/`, includes 7.2 GB model weights from Git LFS).
- `docker/Dockerfile.kit` — GPU renderer (build context: `services/rendering-job/`).

## Lint / format

```bash
uv run --package search-utils black packages/search-utils/search_utils/
uv run --package search-utils isort packages/search-utils/search_utils/
```

## Per-service docs

For per-service details (modules, install, build notes), see the README
in each service or package directory — e.g.
[`packages/search-utils/README.md`](../packages/search-utils/README.md),
[`services/deepsearch-crawler/README.md`](../services/deepsearch-crawler/README.md),
[`services/asset-graph/README.md`](../services/asset-graph/README.md), and so on.

[`CLAUDE.md`](../CLAUDE.md) at the repo root covers guidance for AI-assisted development.

## Contributing, security

- Contributions: see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
- Vulnerability reporting: see [`SECURITY.md`](../SECURITY.md).
