# Development guide

Everything you need to build, run, test, and modify USDSearch from source — for
contributors and operators who want the details, and for Claude Code when
working **on** the repo itself (as opposed to using its skills to
search/inspect/deploy assets — for that, see [`CLAUDE.md`](../CLAUDE.md)). The
top-level README covers the agent-driven and one-command Docker Compose paths;
this file is the source of truth for development work. Read it before doing any
repo-maintenance work.

## Repository layout

```
usdsearch/
├── packages/
│   ├── search-utils/           # Shared infrastructure (storage clients, OpenSearch, Redis Streams, caching)
│   ├── llm-client/             # Shared OpenAI-compatible LLM/VLM client + metadata/validation schemas
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

`services/rendering-job` and `services/asset-graph-builder` are **not** uv workspace members due to dependency conflicts (see Known Workspace Limitations). `services/explorer` is a Node.js project and is also excluded.

## Key architecture notes

- **Dependency order**: `search-utils` ← `deepsearch-crawler`, `ngsearch-backend`, `deepsearch-utils` ← `services/*`
- `services/crawlers` and `services/deepsearch-monitor` both depend on `services/deepsearch-crawler` (for `DeepSearchConsumer`)
- `services/deepsearch_api` depends on `packages/asset-graph-client` (generated, no manual edits)
- Generated clients (`asset-graph-client`) live in `packages/` and are regenerated from OpenAPI specs — do not hand-edit. **Exception**: the SPDX/Apache-2.0 license headers added by `scripts/apply_spdx_headers.py` are intentional. Regenerating the client wipes them; re-run the script (or restrict it to `packages/asset-graph-client/`) after every regeneration.
- `services/rendering-job` has no Python-level deps on other workspace packages; called at runtime over HTTP from `services/deepsearch-monitor` via `deepsearch-utils/rendering_utils.py`
- `packages/siglip2-triton-client` is a workspace leaf used by `ngsearch-backend`; `services/siglip2-triton` is its standalone server counterpart
- `packages/llm-client` is the shared OpenAI-compatible LLM/VLM client (LangChain `ChatOpenAI`) plus the metadata/validation schemas; used by `services/deepsearch-monitor`, `services/deepsearch_api`, and `packages/plugins`. It supersedes the retired `packages/vision-endpoint` (the directory still physically exists but is not a workspace member; its CLIP/SigLIP2 Triton client moved to `packages/siglip2-triton-client`, and the helm values key `vision_endpoint` is kept for backward compatibility).
- **One shared LLM/VLM connection, model picked per role.** `llm_client.LLMConnectionConfig` reads the endpoint once from `USDSEARCH_LLM_API_KEY` / `USDSEARCH_LLM_BASE_URL` (env prefix `usdsearch_llm_`); each role then only selects a model under its own prefix — query parsing `USDSEARCH_LLM_PARSING_*` (`services/deepsearch_api/.../llm_parse/config.py`, optionally overriding base-url/api-key for a separate parsing endpoint), validation `USDSEARCH_VISION_VALIDATION_*`, metadata `USDSEARCH_VISION_METADATA_*`. There is no provider selector — the old provider-specific scheme (`METADATA_GENERATION_VLM_SERVICE` + per-provider `*_API_KEY`) is gone. The helm chart renamed `ngsearch.microservices.search_rest_api.search_llm` → `llm_parsing` to match.
- Package manager: **uv workspace** — all packages except `services/rendering-job` and `services/asset-graph-builder` are workspace members (see Known Workspace Limitations for why). `services/explorer` is a Node project, also excluded.
- **Test data paths** in package tests must use `pathlib.Path(__file__).parent` to anchor paths relative to the test file, not the CWD. Bare relative paths like `"tests/..."` break when pytest is run from the workspace root.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager and workspace tool
- Internet access to [PyPI](https://pypi.org/) (all dependencies are publicly available)
- [buf](https://buf.build/) — for regenerating protobuf/gRPC clients (optional, only needed when IDL changes)
- `7z` (`apt install p7zip-full` on Debian/Ubuntu, `brew install p7zip` on macOS) — needed by the `search-utils` build step below
- Docker + Docker Compose — for local service stacks

## Build and install

```bash
# Pre-step: fetch the pre-compiled Omniverse protobuf packages that
# `search-utils` force-includes into its wheel. Required before the first
# `uv sync`. Pulls 5 packages (~few MB total) from a public NVIDIA
# CloudFront CDN; no credentials needed. Requires `7z` (apt: p7zip-full).
./build/build_search_utils.sh

# Install all workspace members in editable mode
uv sync

# Install a single package only
uv sync --package search-utils
uv sync --package deepsearch-api
```

The pre-step populates `packages/search-utils/_build/{discovery.client.py,
idl.py, omniverse_connection, omniverse.auth.client.py, tag_idl_client}/`,
referenced by `[tool.hatch.build.targets.wheel.force-include]` in
`packages/search-utils/pyproject.toml`. `_build/` is `.gitignored`
(`packages/search-utils/.gitignore:58`); the script regenerates it on demand.
The same script runs in `docker/Dockerfile.usdsearch`, so the Docker and
local-`uv sync` paths share the mechanism. Skipping it produces:

```
FileNotFoundError: Forced include not found:
.../packages/search-utils/_build/discovery.client.py/omni
```

## Running services

All workspace services ship in a single Docker image (`docker/Dockerfile.usdsearch`). Override the command at launch to select the service:

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

See the corresponding compose file for the canonical command per service.

## Docker

`docker/Dockerfile.usdsearch` is a single combined image that includes all workspace services **except** `services/rendering-job`, `services/asset-graph-builder`, and `services/siglip2-triton` (excluded for the same reasons they are excluded from the workspace — see Known Workspace Limitations).

Other Dockerfiles:
- `docker/Dockerfile.siglip2-triton` — Triton Inference Server image for SigLIP2 ONNX models; build context is `services/siglip2-triton/` (where the model weights live).
- **Explorer front-end (two build paths).** The Explorer SPA depends on the `@kui` / `@kui-contrib` packages, which resolve only from the NVIDIA-internal NGC npm proxy (see `services/explorer/.npmrc`), so it **cannot be built from source outside NVIDIA**. The build is therefore split:
  - `docker/Dockerfile.explorer` — **public, self-contained.** `FROM bitnami nginx` + `COPY services/explorer/dist /app`. No npm build, no internal registry. It serves the pre-built **generic** bundle tracked in the repo at `services/explorer/dist/` (empty `REACT_APP_API_URL` = same-origin `/api/`, `usd*` include filter, no server mapping). This is the image the OSS mirror ships, the compose stack (`infra/compose/explorer.yml`) builds, and CI publishes as the canonical `usdsearch-explorer:<sha>` (job `build-explorer-public`).
  - `docker/Dockerfile.explorer-internal` — **internal only.** Today's multi-stage `node:20-alpine` → bitnami nginx build that runs `npm ci` (against the internal registry) + `npm run build`, with all the `REACT_APP_*` build args (CRA inlines them at build time). `REACT_APP_VERSION` is injected from `VERSION.md`. Use it — via `scripts/build-explorer.sh` (`--cutoff` / `--extensions`, `--suffix`, `--push`) or `scripts/build-explorer-general.sh` (bakes the shared `REACT_APP_SERVER_MAPPING`) — to produce customized/parameterized images. CMS team build: `REGISTRY=nvcr.io/m3sujtetvf5w/usdsearch ./scripts/build-explorer.sh --extensions "" --cutoff 0 --suffix=cms --push`. Excluded from the OSS mirror.
  - **Regenerating the tracked bundle.** After changing any Explorer source, run `scripts/generate-explorer-build.sh` (internal; runs the internal Dockerfile's `build` stage with generic defaults and rewrites `services/explorer/dist/`) and **commit `services/explorer/dist/`**. CI's `verify-explorer-build` job rebuilds the bundle the same way and fails, byte-for-byte, if the committed `dist/` is stale — its failure message tells you to re-run the script. Not part of the unified `usdsearch:latest` image.
- `docker/Dockerfile.kit` — GPU-accelerated rendering image (Omniverse Kit subprocess workers); build context is `services/rendering-job/`. Fetches packman via sparse git checkout of `tools/packman` from the **public** `NVIDIA-Omniverse/kit-app-template` repo (tag controlled by `ARG KIT_APP_TEMPLATE_TAG=110.1.0`). The repo's own `tools/packman/config.packman.xml` (public CloudFront CDN) is used directly — no local override.
- `services/deepsearch_api/docker/Dockerfile` — slimmer single-service image for deepsearch-api only.

**Build** (from repo root — build context must be the workspace root):
```bash
docker build -f docker/Dockerfile.usdsearch -t usdsearch:latest .
```

Extras **not** installed in the combined image by default: `siglip2` (pulls `transformers`, ~1 GB). Add `--extra siglip2` to the `uv sync` step if SigLIP2 preprocessing is needed client-side.

**Important implementation details**:
- `services/siglip2-triton/` is excluded via explicit per-service `COPY` instructions in `docker/Dockerfile.usdsearch` (not via `.dockerignore`) — the directory contains 7.2 GB of ONNX model weights. Adding new services to the image requires an explicit `COPY services/<name>/ services/<name>/` line.
- `logging.yml` is copied to `/logging.yml` (filesystem root, not `/app/`) — `base_logging.get_logging_config()` defaults to `LOGGING_CONFIG=/logging.yml`. **Container-test compose overlays** (`*.container-test.yml`) must explicitly mount it and set the env var — they do not inherit the image's copy automatically:
  ```yaml
  environment:
    - LOGGING_CONFIG=/logging.yml
  volumes:
    - ../../logging.yml:/logging.yml:ro
  ```
- `infra/compose/asset-graph-service.yml` builds from `docker/Dockerfile.usdsearch` (unified image) rather than a pinned pre-built image. Its CI cache overlay is `infra/compose/asset-graph-service.ci.yml`, which shares the `usdsearch:cache` registry tag with any other service built from the same Dockerfile.
- **`.dockerignore` and `_build/` content**: Do not use `**/data/` in `.dockerignore` — it is too broad and will strip `packages/search-utils/_build/idl.py/idl/data/` from the build context before hatch can bundle it into the search-utils wheel. Use scoped patterns like `services/**/data/` instead. The `**/tests/` exclusion is safe because test directories are never needed in the image.
- **`uv sync` extras in `docker/Dockerfile.usdsearch`**: `--extra search-backend`, `--extra storage-api`, and `--extra pillow` are already activated by service-level `search-utils[...]` dependencies but are kept for explicitness. `--extra tools` (tqdm) is covered by `usdsearch`'s direct dep.
- **Passing args to `docker compose run` with `bash -c`**: Use `bash -c '...' -- "$@"` — not `bash -c "... $@"`. The double-quote form expands `$@` in the outer shell, splitting multi-word args across the command string and bash's `$0`, so pytest receives `-n` without its value. The single-quote form with `-- "$@"` passes args as positional parameters to the inner shell.

**`docker compose up --build`**: CI scripts that use compose files containing a `build:` section (`siglip2-triton.yml`, `asset-graph-service.yml`, `asset-graph-builder.yml`, `rendering-job.yml`) pass `--build` to `docker compose up` so containers are always rebuilt from current source. Scripts that only start pre-built infrastructure images (redis, opensearch, neo4j, minio, storage-apis) do not need `--build` and are left unchanged.

## Helm chart

The `usdsearch` Helm chart lives at `helm/usdsearch/`. It deploys the full USD Search stack to Kubernetes: deepsearch, ngsearch, deepsearch-crawler, rendering-service, asset-graph-service, s3proxy (local sub-charts), plus vendored dependencies (OpenSearch, Redis, Neo4j, NGINX). Regenerate the chart README with `helm/scripts/update_readme.sh` after editing `README.md.gotmpl` or `values.yaml`.

### Versioning (dual git-tag scheme)

Three independent tag namespaces control versioning:

| Tag Pattern | Controls | Example |
|---|---|---|
| `chart-X.Y.Z` | Helm chart `version` in Chart.yaml | `chart-1.4.0` |
| `images-X.Y.Z` | Helm chart `appVersion` + Docker image tags for NGC | `images-1.4.0` |
| Bare `X.Y.Z` | Python packages via `uv-dynamic-versioning` | `1.0.0` |

- **Chart.yaml** is checked in with placeholder `0.0.0-dev` values — CI stamps real versions at package time via `helm/scripts/version.sh`.
- On non-tagged commits, versions get a `-N` suffix (commits since last matching tag).
- `uv-dynamic-versioning` uses `pattern = "default-unprefixed"` and only matches bare tags — no interference with prefixed tags.

### Running helm tests

```bash
# Unit tests (helm dry-run based — no cluster needed):
HELM_CHART_PATH=./helm/usdsearch ci/helm/tests/unit/run_all.sh

# Template validation:
helm template test-release helm/usdsearch \
  --set global.accept_eula=true \
  --set global.storage_backend_type=s3 \
  --set global.s3.bucket_name=test \
  --set global.imagePullSecrets={nvcr.io}

# Integration tests (requires kubectl access to a test cluster):
HELM_CHART_PATH=./helm/usdsearch ci/helm/tests/integration/run_all.sh
```

### CI pipeline (helm)

Defined in `ci/helm/gitlab-ci.yml` (included from root). Helm jobs slot into the shared root pipeline stages: `lint` (helm-lint, helm-template-validate) → `init` (build-helm-readme) → `build` (helm-package) → `test` (helm-unit-test, helm-integration-test) → `publish` (helm-publish-ngc, helm-publish-readme).

- Jobs trigger on `changes: helm/**/*` and `ci/helm/tests/**/*` — Python-only PRs skip helm CI entirely.
- Tag pushes matching `chart-*` trigger the full lint → package → test → publish pipeline.
- Publishing pushes to NGC at `omniverse/deeptag-internal/usdsearch`.

### Releasing a chart version

Push a tag in the relevant namespace (or both together on the same commit) — CI handles the rest:
```bash
git tag chart-1.4.0      # Helm chart version → NGC chart publish
git tag images-1.4.0     # appVersion + Docker image tags → NGC image publish
git push origin chart-1.4.0 images-1.4.0
```

## Quickstart compose stack

Top-level compose files at the repo root run a complete local dev stack (separate from the per-service files under `infra/compose/` used by CI). **Requires Docker Compose >= v2.26** — earlier versions (incl. the v2.20 shipped with Ubuntu 22.04) fail with `services.siglip2-triton conflicts with imported resource` because the gpu-plugins overlay extends a service that the root `docker-compose.yml` brings in via `include:`.

- `docker-compose.yml` — base stack: opensearch, redis, neo4j, siglip2-triton (CPU-mock), deepsearch-api, info-endpoint, asset-graph-service, deepsearch-crawler, indexing-crawler, monitor-crawler, embedding workers (image/thumbnail), `monitor-worker-asset-graph-generation`, `graph-builder` (Kit image, `MODE=graph-builder`, no GPU reservation), and the nginx gateway. **No Explorer WebUI by default** — add the `docker-compose.web-ui.yml` overlay to include it.
- `docker-compose.web-ui.yml` — overlay: Explorer React front-end. Adds the `explorer` service (built from `docker/Dockerfile.explorer`) and swaps the gateway's nginx config from `gateway.conf` to `gateway.web-ui.conf` (via the `!override` volumes tag) so `/`, `/ui/`, `/static/`, and the root-static catch-all proxy to the explorer container. Without this overlay, the gateway's `/` redirects to `/docs/` instead of `/ui/`.
- `docker-compose.gpu-plugins.yml` — overlay: real SigLIP2 (GPU), `rendering-job` (Kit), and the GPU plugin workers `monitor-worker-thumbnail-generation` and `monitor-worker-rendering-to-embedding`.
- `docker-compose.vlm-plugins.yml` — overlay: VLM metadata + validation workers; inference runs on a remote OpenAI-compatible API, so no local GPU is needed. Set the one shared `USDSEARCH_LLM_API_KEY` (optionally `USDSEARCH_LLM_BASE_URL` to point at any OpenAI-compatible endpoint); each role only picks a model via `USDSEARCH_VISION_METADATA_MODEL` / `USDSEARCH_VISION_VALIDATION_MODEL`. There is no per-provider key. Credentials are null-pass-through via the `x-vlm-provider-env` / `x-vlm-worker-env` anchors, so unset vars stay omitted from the container.
- `docker-compose.s3proxy-auth.yml` — overlay: deploys s3proxy as a credential-translating reverse proxy for authenticated non-AWS S3 endpoints. Reads upstream credentials from the same `S3_STORAGE_AWS_*` host env vars the stack already uses, and exposes the bucket locally at `http://s3proxy:80` with `S3PROXY_AUTHORIZATION=none`. Required when using a custom S3 endpoint (non-`*.amazonaws.com`) with GPU plugins — Kit's native client library cannot authenticate to non-AWS endpoints (see Known Pitfalls). All services are redirected through s3proxy for consistency (same pattern as the Helm chart's sub-chart).
- Infra services (`redis`, `opensearch`, `neo4j`, `siglip2-triton` base) come in via `include:` from `infra/compose/<svc>.yml` plus quickstart-only overrides at `infra/compose/quickstart/<svc>.override.yml`.
- All services declare `restart: unless-stopped` (via the `x-usdsearch-image` anchor for image-based services, or explicitly for infra/gateway/explorer).
- `graph-builder` shares `docker/Dockerfile.kit` with `rendering-job` but is tagged `usdsearch-graph-builder:latest` (separate from the renderer's `usdsearch-rendering-job:latest`); BuildKit cache makes the second build a near-instant cache-hit.

**Gateway routes** (`infra/quickstart/gateway.conf` — baseline, no WebUI):
- `/` → 302 to `/docs/`
- `/docs/` → static Swagger UI (nginx serves `helm/usdsearch/docs/index.html` + `helm/usdsearch/docs/openapi.json` mounted into `/usr/share/nginx/docs/`; same files the helm chart ships in its static-content configmap). The gateway has a healthcheck that probes `/docs/` since it requires no upstream. The merged spec is regenerated by `scripts/build-openapi-docs.sh` (default output: `helm/usdsearch/docs/openapi.json`); CI's `build-openapi-docs` job diffs it and fails when stale.
- `/search`, `/search_hybrid`, `/vlm_validate/...`, `/images`, `/download/...` (e.g. `/download/asset`) → deepsearch-api
- `/info`, `/process` → info-endpoint
- `/asset_graph/`, `/dependency_graph` → asset-graph-service

With the `docker-compose.web-ui.yml` overlay, the gateway is reconfigured from `infra/quickstart/gateway.web-ui.conf` and additionally serves:
- `/` → 302 to `/ui/` (overrides the docs redirect)
- `/ui/`, `/static/`, and a root-static catch-all → explorer

**Smoke tests**: `./scripts/quickstart-smoke.sh` exercises every gateway-proxied API and prints PASS/FAIL per endpoint. Run it after `docker compose up` reports services as healthy. The `/deploy-usdsearch` skill (Local branch) calls it automatically as its final step before handing control back to `/quickstart`. Honors `BASE` (gateway URL), `ASSET_GRAPH_TIMEOUT` (seconds the AGS section waits for the first graphed scene; default 15), `BASIC_AUTH=user:password` (threaded through every curl call as `-u`), and `WEB_UI=on|off` (default `off`). When the WebUI overlay is enabled, set `WEB_UI=on` so the script asserts `/ → /ui/` and `/ui/ → 200`; otherwise it asserts `/ → /docs/` and skips the `/ui/` check.

**Nucleus mode requires HTTP Basic Auth on every gateway request.** When `STORAGE_BACKEND_TYPE=nucleus`, the gateway gates the deepsearch-api / info-endpoint / asset-graph routes with Basic Auth using the same `OV_USERNAME` / `OV_PASSWORD` the stack was started with. Browsers show a credential prompt; smoke + curl-from-host calls need `BASIC_AUTH="$OV_USERNAME:$OV_PASSWORD"` (smoke script) or `-u "$OV_USERNAME:$OV_PASSWORD"` (raw curl). Without this, every endpoint returns 401 — which is misleading because the stack itself is fine. S3 backends run anonymously, no auth needed.

**Storage API backend (`STORAGE_BACKEND_TYPE=storage_api`)** is selected purely by host env, exactly like Nucleus — no dedicated overlay file. Set `STORAGE_API_GRPC_ENDPOINT` (a **container-reachable** `host:port` — not bare `localhost`; use the host LAN IP, an external DNS name, or `host.docker.internal` with an `extra_hosts: ["host.docker.internal:host-gateway"]` entry which the base compose does not add) plus optional `STORAGE_API_BASE_URI` / `STORAGE_API_SSL` / `STORAGE_API_TOKEN` / `STORAGE_API_OPENID_*`. These are null-pass-through in `x-common-env`, `x-gpu-worker-env`, and `x-vlm-worker-env` (`StorageAPIStorageClientConfig` declares `env_prefix="storage_api_"`). No gateway Basic Auth (that is Nucleus-specific). GPU render-from-USD works: the `RenderingServiceClient` forwards storage_api creds to the rendering-job service **per request** — the gRPC endpoint as `storage_api_url` in the POST body and the optional bearer token via an `X-Token-Auth` header — so the GPU **workers** need `STORAGE_API_*`, but the `rendering-job` service does **not** (it builds the Kit `Authentication` from the request, not its own env).

**End-to-end test harness** at `ci/quickstart/`: parametric runner (`run_tests_quickstart.sh`) + sequential driver (`run_all.sh`) covering 6 configs — `public-s3`, `public-s3-vlm`, `private-s3`, `private-s3-vlm`, `nucleus`, `nucleus-vlm`. Each runner brings up base + GPU plugins (+ VLM overlay where applicable) via `docker compose up -d --wait --build`, polls `/search` until ≥1 indexed asset, runs the smoke script with bumped timeouts, and tears down with `down -v --remove-orphans` on EXIT. Auto-sets `BASIC_AUTH` from `$OV_USERNAME:$OV_PASSWORD` for nucleus configs. A `storage-api` config also exists (external Storage API gRPC endpoint, `STORAGE_API_GRPC_ENDPOINT` required from the host) — availability-gated like nucleus/private-s3. Not in GitLab CI yet — depends on GPU runner availability that isn't currently provisioned. Caller exports credentials under domain-specific names (`DS_STAGING_AWS_*` for staging S3) which the configs map to canonical names (`S3_STORAGE_AWS_*`); for Nucleus the canonical names `OV_USERNAME` / `OV_PASSWORD` are used directly.

**Detecting graphed assets via `/search`**: `/search` and `/search_hybrid` accept `return_root_prims=true` (and `return_default_prims=true`), which annotate each hit with its prims pulled from the asset graph store. A non-empty `root_prims` proves the `asset_graph_generation` worker has already finished that asset — useful for tests or UIs that need to filter to graphed scenes deterministically (one query, no probing of `/asset_graph/usd/prims`).

## Local filesystem backend (s3proxy)

The `docker-compose.local-fs.yml` overlay provides a transparent local-development experience: your asset directory is mounted directly via **s3proxy** (an S3-compatible gateway backed by the filesystem). No copy step, no Docker volume indirection. API responses return absolute local paths; input queries accept them.

**Usage:**
```bash
LOCAL_FS_DATA_DIR=/path/to/my-assets \
  docker compose -f docker-compose.yml -f docker-compose.local-fs.yml up --build
```

**Components:**
- `s3proxy` (andrewgaul/s3proxy) — filesystem-nio2 backend, port 9000, mounts `$LOCAL_FS_DATA_DIR`
- `fs-watcher` (services/fs-watcher/) — watches `$LOCAL_FS_DATA_DIR`, triggers `/process/asset` on info-endpoint for each new/changed file
- `LocalFSPathMiddleware` (packages/search-utils/search_utils/local_fs_middleware.py) — ASGI middleware on all 3 API services that bidirectionally rewrites `s3://bucket/` <-> `$LOCAL_FS_DATA_DIR/`

**Environment variables:**
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOCAL_FS_DATA_DIR` | Yes | — | Host path to your assets directory |
| `LOCAL_FS_BUCKET` | No | `usdsearch-local` | Bucket name in s3proxy |

**How the path rewriting works:**
- Requests: local paths in query params/bodies (`/home/user/assets/car.usd`) are rewritten to `s3://usdsearch-local/car.usd` before reaching the application
- Responses: `s3://usdsearch-local/car.usd` in JSON responses is rewritten to `/home/user/assets/car.usd` before reaching the client
- Controlled by `LOCAL_FS_MODE=true` + `LOCAL_FS_HOST_PATH` env vars (set by the compose overlay)
- Complete no-op when `LOCAL_FS_MODE` is unset (production, CI, other backends)

**Alternative: MinIO backend** (`docker-compose.local-s3.yml`) — copies files into MinIO at startup, closer to production S3 behavior, MinIO can be scaled for larger deployments.

## Running tests

```bash
# Run tests for a specific workspace member
uv run --package ngsearch-storage pytest services/storage/tests/

# Run a single test file
uv run --package deepsearch-crawler pytest services/deepsearch-crawler/tests/test_consumer.py -v

# Run a single test by name
uv run --package search-utils pytest packages/search-utils/tests/ -k "test_redis_cache" -v
```

Before validating a change, check `./ci/` first: most members have a CI runner at `ci/<name>/run_tests_<name>.sh` that provisions the right backing services (via `infra/compose/*.yml`), exports the env vars the app reads, and invokes pytest the way CI does — a local pass there actually predicts a CI pass. (Note: these scripts append the tests dir and pass extra args through an unquoted `$@`, so a single-token `-k` works but a multi-word `-k "a or b"` expression splits — narrow to one token or run the full suite.)

## Skill tests

Claude Code skills live under `skills/` at the repo root (the source of truth; `.claude/skills` is a compat symlink -> `../skills` so the harness still finds them). They ship with their own test suites at `ci/skills/<skill-name>/`. Two layers are exercised: a static lint of `SKILL.md` (frontmatter, sections, `bash -n` over every fenced block, probe/table key consistency) and a behavioral test of the L1 pre-flight bash block under a sandboxed `PATH` populated with mock `docker` / `git` / `nvidia-smi` binaries that read `MOCK_*` env vars.

```bash
# Run all skill suites
./ci/skills/run_all.sh

# Run a specific skill suite
./ci/skills/deploy-usdsearch/run_tests.sh

# Run a single test
./ci/skills/deploy-usdsearch/run_tests.sh -k test_lfs_some_pointers
```

The suite resolves `REPO_ROOT` via `git rev-parse --show-toplevel`, so it works from any cwd. `pytest` + `pyyaml` are pulled in ephemerally via `uv run --with`, so no project-wide dependency changes are needed. Coverage reporting is explicitly disabled via `--no-cov` since the skills under test are markdown, not Python.

The `skills-lint` job lives in the root `.gitlab-ci.yml` and slots into the `lint` stage. It has no `repo-init` dependency (`needs: []`) and starts immediately: `run_tests.sh` runs pytest via `uv run --no-project` with only `pytest` + `pyyaml` layered in, and the skill tests never import a workspace package — so no search-utils `_build` / pytinyexr / uv-cache is needed. A sibling `skills-validate` job (also `lint`, also `needs: []`) runs `ci/skills/validate_skills.sh`, which validates every `skills/*/SKILL.md` with the NVIDIA `nv-base` validator (installed on demand as an isolated `uv tool` from internal Artifactory, never a workspace dep). It writes per-skill reports to `skill-validation-reports/<skill>/` (via `SKILL_VALIDATION_OUT_DIR`) and keeps them as artifacts with `when: always`. Both jobs are gated on `changes: skills/**/* | .claude/skills/**/* | .codex/skills/**/* | ci/skills/**/*` — Python-only or helm-only MRs skip them entirely.

## Agent skills & docs maintenance

The agent skills and the user-facing agent docs are shared by **Claude** and
**Codex Desktop**; keep them agent-neutral and safe for the public repo.

**Source of truth.**
- Skill implementations live under `skills/` (Claude discovers them there via the
  `.claude/skills` symlink; Codex via `.codex/skills`).
- [`docs/README.md`](README.md) is the documentation index.
- [`docs/agent-desktop/search/README.md`](agent-desktop/search/README.md) is the
  external-facing (OSS-shipped) search guide.
- [`docs/agent-skills.md`](agent-skills.md) is the shared Claude + Codex overview.
- [`AGENTS.md`](../AGENTS.md) holds Codex runtime notes; [`CLAUDE.md`](../CLAUDE.md)
  holds the Claude skill-usage pointers.

When behavior changes, update the skill first, then the docs that expose it.

**Public-safety rules** (these docs sync to the OSS mirror — see
`scripts/rsync-opensource.sh`):
- No raw API keys, tokens, passwords, cookies, or private credentials.
- No private service URLs unless explicitly approved for the public repo.
- For credentialed examples, tell users to `export` values locally and give the
  agent only the environment-variable **names**.
- Prefer examples against `https://search.simready.omniverse.nvidia.com`, the
  public hosted instance the docs use.
- Do not paste large generated result payloads into docs; describe the expected
  output shape instead.
- Internal-only material (`docs/agent-desktop/search/internal/`) must stay in the
  sync drop list, never linked from a public doc.

**Skill discovery compatibility.** The repo carries compat symlinks so each
runtime finds the same `skills/`:

```text
.codex/skills  -> ../skills
.claude/skills -> ../skills
```

Codex also documents repo-scoped discovery through `.agents/skills` and
user-scoped discovery through `$HOME/.agents/skills`. Before changing install
instructions, verify the current runtime behavior and make sure the public docs
do not hard-code a stale path.

**Update checklist.**
- [ ] For Codex: check `codex --version` and confirm the current skill-discovery path.
- [ ] Confirm the skill installer can install the documented `skills/` paths from
      `NVIDIA-omniverse/usd-search`.
- [ ] In a fresh agent session, verify the documented skill names appear.
- [ ] Run a hosted smoke prompt (e.g. `$search yellow forklift` / `/search yellow
      forklift`) and confirm it writes `./search-results/<slug>/manifest.json`.
- [ ] Check links in `docs/README.md` and `docs/agent-desktop/search/README.md`.
- [ ] Update `docs/agent-skills.md` or the root `README.md` links only after the
      docs draft is reviewed.

**Keeping examples current.** Use prompts that stay useful even as the hosted
index changes — `$search yellow forklift`, `$search warehouse shelves with rigid
body physics under 100MB`, `$inspect-asset <asset-url-from-search-results>`.
Avoid hard-coding a specific asset URL unless it is known to be stable and
public; search indexes evolve and stale URLs make onboarding fail.

## Lint / format

```bash
uv run --package search-utils black packages/search-utils/search_utils/
uv run --package search-utils isort packages/search-utils/search_utils/
```

## Pre-commit hooks

Always run `pre-commit run --all-files` (or at minimum `pre-commit run` against staged files) before publishing changes — i.e. before any `git push`, MR creation, or tag push. The hooks defined in `.pre-commit-config.yaml` cover yaml/whitespace/large-file checks, `black`, `flake8`, and `apply-spdx-headers` (which rewrites SPDX/Apache-2.0 headers via `scripts/apply_spdx_headers.py`). The SPDX hook is a fixer: if it modifies files, re-stage and commit again before pushing so the published tree matches what CI will see.

## Third-party notices

`THIRD_PARTY_NOTICE.md` at the repo root + the `licenses/` directory list every third-party Python package shipped with USD Search at runtime, with name, version, SPDX license, homepage, and per-package license text. They are regenerated by `scripts/generate_third_party_notice.sh` (bash entry point) which calls `scripts/_generate_third_party_notice.py` (HTTP + wheel/sdist extraction). Re-run after any `pyproject.toml` change — or after changing the runtime image's `apt-get` layer (see "Bundled OS packages" below).

Four production-dep trees are enumerated (test/dev groups excluded) — the three latter are the same services that are excluded from the workspace and thus need their own lock:

- root `uv.lock`
- `services/rendering-job/uv.lock`
- `services/asset-graph-builder/uv.lock`
- `services/siglip2-triton/docker/uv.lock`

All four are tracked, even though `uv.lock` is in `.gitignore` — `.gitignore` carries explicit `!`-exceptions for these four paths. Adding another excluded service in the future requires another exception line.

The script passes `--frozen` to every `uv export` so reruns never silently mutate a lockfile. Cached PyPI metadata + downloaded artifacts live under `_tmp/license-cache/` (already gitignored via the catch-all `_tmp` rule).

The `third-party-notice` pre-commit hook (`.pre-commit-config.yaml`) guards the tracked notices against drift: it runs `scripts/generate_third_party_notice.sh --check`, which regenerates the notice + `licenses/` into a temp tree and diffs them against the committed copies, failing with a byte-for-byte diff when they are stale (the failure message tells you to re-run the script and commit the result). The hook only fires when a staged file can actually change the notice — `**/pyproject.toml`, the four tracked `uv.lock`s, the two enumerated Dockerfiles (`docker/Dockerfile.usdsearch`, `docker/Dockerfile.siglip2-triton`), the generator scripts (`scripts/generate_third_party_notice.sh`, `scripts/_generate_third_party_notice.py`, `scripts/_apt_deps_incontainer.sh`, `scripts/third_party_extras.json`), or the tracked outputs (`THIRD_PARTY_NOTICE.md`, `licenses/`) — so unrelated commits skip it. Because it does a full regeneration it needs docker + NGC pull access (for the apt base images) and network access to PyPI/GitHub, the same as a manual run; run it explicitly with `pre-commit run third-party-notice --all-files`. Note the `licenses/` carve-out on the `trailing-whitespace` / `end-of-file-fixer` hooks: the license texts are verbatim and those fixers would otherwise mangle them (and keep this check permanently red).

Same-name-different-version entries are kept as separate rows, one per `(name, version)`. Today this captures two known workspace splits: `pydantic` 1.x vs 2.x and `websockets` 10.4 vs 16.0.

When a wheel/sdist on PyPI does not ship a `LICENSE*`/`COPYING*`/`NOTICE*` file, the script falls back to fetching one from the project's GitHub repository (URL pulled from PyPI's `project_urls` / `home_page`) by probing common filenames at `https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{name}` — currently `LICENSE`, `LICENSE.txt`, `LICENSE.md`, `LICENSE.rst`, `LICENSE-MIT`, `LICENSE-APACHE`, `LICENSE-APACHE-2.0`, `COPYING`, `COPYING.txt`, `COPYING.md`, `NOTICE`. Hits and misses are cached under `_tmp/license-cache/github/`. If a future package shows up as `_(not retrieved)_`, either its declared GitHub URL is missing/wrong or its LICENSE file uses an unknown filename — extend `GITHUB_LICENSE_FILENAMES` in `scripts/_generate_third_party_notice.py`.

### Bundled OS packages (runtime apt-get layer)

The notice also enumerates the Debian/Ubuntu packages the bundled images install (or upgrade) via their `apt-get` layers, **plus their dependency closure**. They land in a separate "Bundled OS packages" table with `os-<name>-<version>.txt` license files, and the `Sources` column names the image each package belongs to. Two images are enumerated today, configured via the `APT_TARGETS` array in `generate_third_party_notice.sh` (each entry is `<source-label>:<dockerfile>:<stage>`, where `<stage>` is empty for a single-stage Dockerfile):
- **`usdsearch-runtime`** — `docker/Dockerfile.usdsearch`'s `runtime` stage on top of its `nvcr.io/nvidia/base/ubuntu:noble` base (`python3.12`, `ca-certificates`).
- **`siglip2-triton`** — `docker/Dockerfile.siglip2-triton` (single stage) on top of its `nvcr.io/nvidia/tritonserver` base (`openssl`, a vulnerability bugfix bump).

This step is docker-based (the only way to compute the real install closure + read each package's copyright):

1. For each `APT_TARGETS` entry, `generate_third_party_notice.sh` parses the target stage's `FROM` image (`FROM ... AS <stage>` when a stage is named, else the first `FROM`) and its `apt-get install` package list straight out of the Dockerfile (so it tracks Dockerfile changes; single-line package lists only).
2. It runs that base image and executes `scripts/_apt_deps_incontainer.sh` inside it (mounted read-only, with `TPN_SOURCE=<source-label>`): snapshot `dpkg` before, `apt-get install` the parsed packages, and emit a JSON manifest (`name`, `version`, copyright from `/usr/share/doc/<pkg>/copyright`, `source`) of the reported set — the newly-**added** closure **plus the explicitly-requested packages** (`"$@"`). The latter union is what captures a package the base already ships and `apt-get install` merely **upgrades** (e.g. the openssl bump on the Triton base), which a pure before/after diff would miss. When the copyright path is missing or a **dangling symlink** (the base image strips the target package's doc dir — e.g. `openssl` → `../libssl3/copyright`, whose `libssl3t64` doc was removed), the text is recovered from the archive: `apt-get download` the package's own `.deb`, else the symlink-target package's `.deb`, resolving the t64/rename by prefix-matching the target name against the package's `apt-cache depends` list (`libssl3` → `libssl3t64`). The `.deb`'s copyright is extracted via `dpkg-deb --fsys-tarfile | tar -xO`. The per-target manifests are merged into a single `_tmp/license-cache/apt_deps.json`.
3. `_generate_third_party_notice.py --apt-manifest` writes the copyright files and infers each license id: SPDX-ish short ids from a machine-readable (DEP-5) `copyright`, else SPDX text heuristics over a widened window (free-form copyrights bury the license body past the preamble — e.g. Python's), else `UNKNOWN`. Entries with the same `(name, version)` across images are merged into one row whose `Sources` lists every image.

Notes / gotchas:
- **Requires docker + NGC pull access** to each target's base image. The step is best-effort per target: if docker is missing it skips all targets; a single unparseable/unbuildable target warns and contributes `[]` without killing the others (the rest of the notice still generates). Set `THIRD_PARTY_SKIP_APT=1` to skip it entirely; edit `APT_TARGETS` (or `DOCKERFILE=` for the usdsearch entry) to change what's enumerated.
- An apt-get layer that only **upgrades** a base-image package is captured only for packages named explicitly on the `apt-get install` line — the dependency closure of an upgrade (versions bumped on already-installed transitive deps) is **not** enumerated, since those packages were already present before the install. Net-new packages still bring their full closure.
- A package whose `/usr/share/doc/<pkg>/copyright` is a **dangling symlink** is recovered from the archive `.deb` (see step 2 above), so it no longer falls back to `UNKNOWN` / `_(not retrieved)_`. Recovery is best-effort and needs apt network access inside the container; if the target package has no candidate and no rename-matching dependency, it still degrades to `UNKNOWN`. The base images' own packages are out of scope here (delta only); track a base image itself in `scripts/third_party_extras.json` if needed.

## CI pipeline

Pipeline runs on: MR events, commit tags, default branch, and `release/*` branches.

**Stages**: `init` → `lint` → `unit` → `build` → `publish-images` → `test` → `sevan-integration` → `security` → `publish` → `deploy` → `pages-prepare` → `pages`. Helm jobs share the root stages (`lint`, `init`, `build`, `test`, `publish`) rather than living in their own helm-prefixed stages.

External template includes:
- `omniverse/deeptag/ci-cd-storage-backends` → `nucleus.yml`
- `omniverse/deeptag/gitlab-templates` → `deepsearch-build-upload-pipeline.yaml`
- `local: ci/helm/gitlab-ci.yml` → Helm chart lint, package, test, publish

The Claude Code skill lint + behavioral tests (gated on `changes: skills/** | .claude/skills/** | ci/skills/**`) are defined inline in the root `.gitlab-ci.yml` as `skills-lint`, not in a separate include.

**`uv` is not pre-installed on CI runners** — each job that needs it must run `pip install uv` first.

**Git LFS is skipped** (`GIT_LFS_SKIP_SMUDGE: "1"`) in jobs that don't need model weights: `build-search-utils`, `unit-search-utils`, `unit-storage`, `unit-llm-client`, `unit-usdsearch`, `unit-info-endpoint`. **Exception**: `build-siglip2-triton` must NOT set this variable — it COPYs the 7.2 GB ONNX weights from `model_repo/` (stored in Git LFS).

**Per-package CI scripts**: each workspace member has a runner at `./ci/<name>/run_tests_<name>.sh`. Most are plain pytest runs; the docker-compose-based ones are `asset-graph-builder` (no upstream `needs`), `siglip2-triton` (GPU optional), `rendering-job` (GPU required), `search-utils` (needs minio + dind), and the helm chart suite (`./ci/helm/tests/unit/run_all.sh`).

**Build-stage jobs** (`build-usdsearch`, `build-siglip2-triton`, `build-rendering-job`): push images to the GitLab registry tagged `$CI_COMMIT_SHORT_SHA` for downstream jobs to pull.

**`publish-images` stage** (`publish-usdsearch`, `publish-siglip2-triton`, `publish-rendering-job`): triggered **only on `images-X.Y.Z` tag pushes**. Pulls images from the GitLab registry (tagged `$CI_COMMIT_SHORT_SHA` by the build stage), re-tags them with the version from the git tag, and pushes to `nvcr.io/nvidia/usdsearch/<name>:<version>`. This ensures the `images-X.Y.Z` tag actually publishes Docker images to NGC — the same images that were tested in the `test` stage. Note: the `publish-rendering-job` job (and the build/scan/test jobs feeding it) emits the OCI image under the name `usdsearch-kit-workflows`, not `rendering-job` — the Kit image is reused for both the renderer and the asset-graph-builder sidecar, so the rename disambiguates the publication target. Source dir, Python module, and compose stack tags keep the legacy `rendering-job` name.

**`test` stage** (CI variable: container tests): contains three kinds of jobs:
- `sanity-usdsearch` — pulls the built `usdsearch` image and runs `python -m usdsearch.admin.tools $COMMAND` (matrix over several `--help` commands) to verify the Fire CLI entry point is importable.
- `test-deepsearch-crawler-container` — starts redis, storage-api, and the deepsearch-crawler container via `docker compose up -d --wait`; runs pytest against the live crawler. The crawler uses `network_mode: host` so it can reach the Nucleus GitLab service at `localhost`.
- `test-deepsearch-api-container` — starts opensearch, siglip2-triton, and the deepsearch-api container via `docker compose up -d --wait`; requires both `build-usdsearch` and `build-siglip2-triton`. On failure, an `on_error` trap in the script dumps all container logs before tearing down.

**docker buildx driver**: All CI jobs that use BuildKit cache export must run `docker buildx create --driver docker-container` before any `docker build` or `docker compose build` call. The default `docker` driver does not support cache export. This is handled via `!reference [.docker-buildx-init, script]` in `.usdsearch-unit`'s `before_script`. Jobs that override `before_script` entirely (e.g. `unit-plugins`) must re-include this reference explicitly.

**Docker-compose CI pattern** — two variants:
- *Build-and-run* (`asset-graph-builder`, `siglip2-triton`, `rendering-job`): base compose file in `infra/compose/<service>.yml` builds from its Dockerfile; optional GPU overlay `<service>-gpu.yml`; CI cache overlay `<service>.ci.yml` adds BuildKit `cache_from`/`cache_to`. Test runner layers overlays conditionally on `GITLAB_CI=true` and uses `docker compose run --rm --no-deps` with a source volume mount.
- *Pre-built image* (`test-deepsearch-api-container`, `test-deepsearch-crawler-container`): a `<service>.container-test.yml` overlay sets `image: ${SERVICE_IMAGE:-service:latest}` (CI injects the commit-tagged registry image) and strips host port mappings. Runner calls `docker compose up -d --wait --quiet-pull --remove-orphans`, runs pytest on the host against mapped ports, then `docker compose down`. An `on_error` trap dumps `docker compose logs --no-color` before tearing down.

**Required CI secrets/variables**:
- `NGC_API_KEY` — Docker login to `nvcr.io`
- `CI_REGISTRY_USER`, `CI_REGISTRY_PASSWORD`, `CI_REGISTRY_IMAGE` — GitLab container registry (auto-set by GitLab)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` — read access to `s3://deepsearch-test-bucket` in `eu-central-1`
- `BASE_STACK_USERNAME`, `BASE_STACK_PASSWORD` — Nucleus test stack credentials
- `SERVER_IP_OR_HOST` (optional, defaults to `localhost`) — Nucleus server address

**Security stage**: SonarQube scan is currently disabled (`when: never`).

## Known pitfalls

- **`usdsearch` Docker image is on Python 3.12**: `docker/Dockerfile.usdsearch` builds on `python:3.12-bookworm` (builder/test-runner) and runs on `nvcr.io/nvidia/base/ubuntu:noble-20260217` (runtime), which apt-installs `python3.12` (Ubuntu noble's native CPython). The venv is built in bookworm (interpreter at `/usr/local/bin/python3.12`) and copied into noble (apt python at `/usr/bin/python3.12`); a symlink in the runtime stage bridges the two paths — both are CPython 3.12, so the venv's cp312 wheels are ABI-compatible. **Do not bump to Python 3.14**: a previous attempt broke the Nucleus connection at runtime — symptoms looked like a TLS/certificate verification failure during the Omniverse client handshake; root cause not pinned down. Do not add `3.14` to `build/build_pytinyexr.sh`'s `PYTHON_VERSIONS` default for production builds.
- **`requires-python` is intentionally capped at `<3.14` everywhere**: every workspace `pyproject.toml` (and the excluded services `rendering-job`, `asset-graph-builder`, `siglip2-triton/docker`) pins `requires-python = ">=3.11,<3.14"`. This ceiling is **deliberate** — Python 3.14+ breaks the Nucleus connection at runtime (see the Python-3.12 note above). Do **not** widen it to `<4.0` or drop the upper bound, even though numpy 2.x (the previous reason for a tighter cap) now ships 3.14 wheels — the Nucleus breakage is the real blocker, not wheel availability. If you bump numpy or relock, keep the `<3.14` cap and let `uv lock` resolve under CPython 3.13.
- **Re-locking and pytinyexr wheels**: `wheels/` holds custom-built pytinyexr wheels (see the caution in the root `pyproject.toml`) — run `./build/build_pytinyexr.sh` before `uv lock` or the lock silently degrades to the unbuildable PyPI sdist (repo-init asserts this).
- **pytest-asyncio mode**: Services use explicit `@pytest.mark.asyncio` on each test function and `@pytest_asyncio.fixture` on async fixtures (e.g. `services/asset-graph/tests/conftest.py`). Do **not** add `asyncio_mode = "auto"` to any `pyproject.toml` — it silently changes fixture resolution and breaks async tests in these services.
- **VLM `max_tokens`**: All VLM configs default to `max_tokens=4096`. Do not lower this — thinking/reasoning models (e.g. Gemini Flash Preview, o3/o4 variants) consume ~900 tokens on internal reasoning, leaving too few for a complete structured JSON response at 1024.
- **Redis consumer group start ID**: `search_utils.streams.redis.RedisStreamWorker.connect_consumer()` creates the consumer group with `id="0"` (read from the beginning of the stream). Do not change this to `$` — if a service starts after messages are already in the stream, `$` would cause the group to miss all existing entries. The `id` only applies at first creation; subsequent reconnections resume from the group's last-delivered position.
- **`DeepSearchConsumer.close()` in async fixtures**: Always call `await consumer.close()` in the fixture teardown. The constructor spawns a background `_connect` task; without an explicit cancel + await, pytest reports "Task was destroyed but it is pending!" for every fixture instance when the event loop closes.
- **`asset-graph` prim responses and `default_prim`**: The `/asset_graph/usd/prims` endpoint uses `response_model_exclude_none=True`. `Prim.default_prim` is `bool | None` — non-default prims have `None` and the key is absent from the JSON. Always use `prim.get("default_prim")` when iterating an unfiltered prim list; `prim["default_prim"]` raises `KeyError` on non-default prims.
- **pydantic-settings: field-level `alias` overrides `env_prefix`**: When a `BaseSettings` subclass sets `env_prefix="foo_"` and a field declares `Field(alias="bar")`, the field is read from the env var `BAR` (uppercased alias) — **not** `FOO_BAR`. Unrecognized prefixed names are silently ignored, so the default value sticks. Affected configs in this repo include `AGSPluginConfig` (`packages/plugins/plugins/asset_graph_generation.py` — reads `ASSET_GRAPH_SERVICE_ENDPOINT`, `KIT_WORKER_SERVICE_ENDPOINT`) and several search-backend models in `services/deepsearch_api/.../search_backend/models.py`. Before adding new env vars, grep the config class for `Field(alias=...)` and use the bare alias if present.
- **Monitor worker `job_item_type` default skips `priority` jobs**: `DeepSearchMonitorWorkerConfig.job_item_type` defaults to `[JobItemType.normal, JobItemType.none]` (`services/deepsearch-monitor/monitor/src/config.py`). Jobs enqueued with `job_type="priority"` (e.g. by `info-endpoint`'s on-demand `/process` route) are silently filtered out at `monitor_worker.py:200`. Set `DEEPSEARCH_MONITOR_WORKER_CONFIG_JOB_ITEM_TYPE='["priority","normal","none"]'` on every worker that should drain the full queue. The quickstart compose files do this for all 8 workers.
- **Empty-string env var breaks anonymous public-S3 access**: `S3StorageClient` (`packages/search-utils/.../storage_client/s3/client.py:163`) only registers `disable_signing` when `self.config.aws_access_key_id is None`. pydantic-settings reads `S3_STORAGE_AWS_ACCESS_KEY_ID=""` as the empty string `""` (not `None`), so the disable-signing branch is skipped and aioboto tries to sign requests against the public bucket → `NoCredentialsError`. The fix in all top-level compose files is YAML-null pass-through (`KEY:` with no value) for credential env vars — this forwards the var from the host if set and OMITS it from the container otherwise. Same fix for the rendering-job's list-form environment uses bare `- KEY` entries. Do not revert these to `${VAR:-}` empty-string defaults.
- **LLM/VLM env vars: one connection, model-only per-role overrides**: the shared OpenAI-compatible endpoint is set **once** via `USDSEARCH_LLM_API_KEY` / `USDSEARCH_LLM_BASE_URL` (`llm_client.LLMConnectionConfig`, env prefix `usdsearch_llm_`); each role's config only selects a model and is read under its own prefix — `USDSEARCH_LLM_PARSING_*` (query parsing; may also override `_BASE_URL`/`_API_KEY` to point parsing at a separate endpoint), `USDSEARCH_VISION_VALIDATION_*`, `USDSEARCH_VISION_METADATA_*`. There is **no provider selector**: the old `METADATA_GENERATION_VLM_SERVICE` + per-provider `*_API_KEY` scheme has been removed. Before adding a new LLM/VLM env var, find the role's config class (`llm_parse/config.py`, `validation/config.py`) and use its prefix; do not reintroduce provider-name prefixes.
- **Kit client library cannot authenticate to non-AWS S3 endpoints**: URLs not matching `*.s3.*.amazonaws.com` are routed through the base HTTP provider in Kit's `HttpProviderFactory.cpp` (`services/rendering-job/deepsearch_rendering_job/kit.py:45`), which ignores configured S3 credentials. The rendering-job and graph-builder use Kit to open USD files, so they cannot open assets from authenticated non-AWS endpoints (MinIO, Ceph, s3proxy, etc.) directly. Workaround: use the `docker-compose.s3proxy-auth.yml` overlay, which deploys s3proxy as a credential-translating proxy (`S3PROXY_AUTHORIZATION=none` internally) and routes all services through it for consistency. The Helm chart's s3proxy sub-chart does this by default. Not needed for real AWS S3 (Kit handles `*.s3.*.amazonaws.com` natively) or without GPU plugins (Python services use aioboto3 which handles SigV4 for any endpoint).
- **Never pull the whole `siglip2-embedding` nested field into search responses**: each thumbnail's `siglip2-embedding.embedding` is a 1536-float vector, so returning the field bloats every hit. In the `deepsearch_api` search backend (`search_backend/main.py`), `_build_source_includes` requests only the sub-field actually needed (`siglip2-embedding.embedding` for similarity-threshold dedup / `return_predictions`, `siglip2-embedding.image` for `return_images`) — never the whole field. `_vector_inner_hits_source` keeps the vector-leg `inner_hits` `_source` at the **fully-qualified** names `["siglip2-embedding.image", "siglip2-embedding.keyword", "siglip2-embedding.label"]`, adding the vector only when `return_embeddings` is set. The dotted prefix is mandatory: nested `inner_hits` `_source` includes resolve relative to the **root** document, so bare names (`"image"`) match nothing and the inner `_source` comes back empty — silently breaking thumbnail loading for `description`-only queries (the vector leg is then the only source of the image hash). Consumers differ: similarity dedup + predictions read the embedding from the **top-level `_source`**, while the image hash is read from the vector legs' `siglip2-embedding` **inner_hits** (v2 `compat.py` and v3) — so inner_hits must always keep `image`.
- **`SearchResult.source` is a plain dict at runtime**, not a `SearchResultSource` instance — `compat.py`, `filtered.py`, and `routers_v3/search_v3.py` consume it with `.get()`/`.items()`/`[...]`. Do **not** "fix" it by constructing the model (`SearchResultSource(**src)`); that raises `AttributeError` across the pipeline. A `field_serializer` on the field (`search_backend/models.py`) silences the pydantic serialization warning while keeping it a dict.
- **Asset-graph spatial coords reject non-finite values with 422**: the `radius`, `center_x/y/z`, and bounding-box `min_/max_bbox_*` query params in `services/asset-graph/.../api/endpoints.py` set `Query(..., allow_inf_nan=False)`, so `inf`/`nan` inputs fail validation with HTTP 422 instead of reaching the DB. Keep `allow_inf_nan=False` when adding new float spatial query params.

## Removed / deprecated backends

- **Nucleus backend is being deprecated**: The `/deploy-usdsearch` skill (Local branch) flags this when listing storage backends — when adding new code paths or examples, prefer S3 over Nucleus. The Nucleus client itself remains supported and is still tested via `ci/quickstart/configs/nucleus*.env`, but the path forward is S3 (public or private).

## Known workspace limitations

- `services/rendering-job` is **not** a workspace member. The historical blocker — its `websockets>=12.0`
  requirement conflicting with `deepsearch-utils`' old `websockets~=10.4` pin — is now resolved:
  `deepsearch-utils` was bumped to `websockets>=14,<16` and `deepsearch_utils/farm/ws_server.py` was
  migrated to the v14 `websockets.asyncio.server.serve` API (single-arg handler). The two pins are now
  compatible, so this specific conflict no longer applies; full workspace inclusion still needs its
  remaining deps verified against the workspace resolution before it can be added.
- `services/asset-graph-builder` is **not** a workspace member: poetry-based, requires pydantic<2 which
  conflicts with the rest of the workspace (pydantic v2). Migrate when pydantic v2 is adopted.
- `services/explorer` is **not** a workspace member: it is a Node.js (Create React App) project, not
  Python. It is built independently via `docker/Dockerfile.explorer`.
- **OpenSearch 3.x (Lucene 10) silently breaks the `~` complement operator in regexp queries**: queries
  like `{"regexp": {"field": {"value": "~(pattern)", "flags": "ALL"}}}` return 0 hits instead of the
  complement set. Intersection `&` still works. Fixed in `services/deepsearch_api` by detecting
  top-level `~(inner)` patterns and rewriting them as `{"bool": {"must_not": {"regexp": ...}}}`, which
  is correct on both 2.x and 3.x. Do not add new regexp filter paths using `~` directly.

## Per-service docs

For per-service details (modules, install, build notes), see the README
in each service or package directory — e.g.
[`packages/search-utils/README.md`](../packages/search-utils/README.md),
[`services/deepsearch-crawler/README.md`](../services/deepsearch-crawler/README.md),
[`services/asset-graph/README.md`](../services/asset-graph/README.md), and so on.

## Contributing, security

- Contributions: see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
- Vulnerability reporting: see [`SECURITY.md`](../SECURITY.md).
