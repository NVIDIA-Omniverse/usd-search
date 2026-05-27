# DeepSearch Rendering Job

GPU-accelerated USD rendering service. Wraps Omniverse Kit subprocess
workers to render assets requested over HTTP by
`services/deepsearch-monitor`'s thumbnail / rendering plugin workers (via
the HTTP client in `deepsearch-utils/rendering_utils.py`).

## Workspace status

This service is **not** a `uv` workspace member. It requires
`websockets>=12.0`, which conflicts with `deepsearch-utils`'
`websockets~=10.4` pin. It therefore has its own
[`uv.lock`](uv.lock) and is built and tested independently of the
unified workspace. See
[Known Workspace Limitations](../../CLAUDE.md#known-workspace-limitations).

The image is also published under a different name from the rest of the
stack: `nvcr.io/nvidia/usdsearch/usdsearch-kit-workflows:<version>`
(rather than `usdsearch-rendering-job`) because the Kit image is reused
both as the renderer and as the asset-graph-builder sidecar. The repo
itself, Python module, and compose stack tag keep the legacy
`rendering-job` name.

## Requirements

- NVIDIA GPU + `nvidia-container-toolkit` on the host.
- For local testing: `docker compose` v2.

## Building the image

The image is built from [`docker/Dockerfile.kit`](../../docker/Dockerfile.kit),
with the build context `services/rendering-job/`. Packman is fetched at
build time via a sparse git checkout of `tools/packman` from the public
[`NVIDIA-Omniverse/kit-app-template`](https://github.com/NVIDIA-Omniverse/kit-app-template)
repo (tag controlled by `ARG KIT_APP_TEMPLATE_TAG=110.1.0`). No local
packman config edits are required — the in-tree
[`config.packman.xml`](config.packman.xml) (public CloudFront CDN) is
used directly.

From the repo root:

```bash
docker build -f docker/Dockerfile.kit -t usdsearch-rendering-job:latest services/rendering-job/
```

## Running locally

Single-shot render of a USD asset:

```bash
docker run --rm --gpus=all \
    usdsearch-rendering-job:latest \
    https://omniverse-content-production.s3.us-west-2.amazonaws.com/Samples/OldAttic/Props/BookA.usd
```

HTTP API mode (used by the monitor in the compose stack):

```bash
docker run --rm --gpus=all \
    -p 8000:8000 \
    -v "$PWD/.cache":/cache \
    -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin \
    --entrypoint=python \
    usdsearch-rendering-job:latest \
    -m uvicorn deepsearch_rendering_job.api.main:app --host=0.0.0.0 --port=8000
```

For the integrated compose path, use the GPU plugin overlay from the
repo root:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-plugins.yml up -d --build
```

## Known pitfall: non-AWS S3 endpoints

Kit's native HTTP provider cannot authenticate to non-AWS S3 endpoints
(MinIO, Ceph, anything not matching `*.s3.*.amazonaws.com`). When using
GPU plugins against an authenticated non-AWS endpoint, layer the
`docker-compose.s3proxy-auth.yml` overlay so requests are routed through
s3proxy with credentials terminated at the proxy. See the [Known
Pitfalls](../../CLAUDE.md#known-pitfalls) entry.
