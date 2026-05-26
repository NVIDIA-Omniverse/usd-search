# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Searching for assets

When the user asks to find a 3D model, search assets, or get more like an existing asset, use the `/search` skill at `.claude/skills/search/SKILL.md`. It covers text / image / hybrid search against `/search_hybrid` + `/images`, server-side `is_match` validation, the per-hit VLM validator, and thumbnail inspection. This mirrors the codex-side pointer in `AGENTS.md` so both agents start from the same skills.

## Key Architecture Notes

- **Dependency order**: `search-utils` ← `deepsearch-crawler`, `ngsearch-backend`, `deepsearch-utils` ← `services/*`
- `services/crawlers` and `services/deepsearch-monitor` both depend on `services/deepsearch-crawler` (for `DeepSearchConsumer`)
- `services/deepsearch_api` depends on `packages/asset-graph-client` (generated, no manual edits)
- Generated clients (`asset-graph-client`) live in `packages/` and are regenerated from OpenAPI specs — do not hand-edit. **Exception**: the SPDX/Apache-2.0 license headers added by `scripts/apply_spdx_headers.py` are intentional. Regenerating the client wipes them; re-run the script (or restrict it to `packages/asset-graph-client/`) after every regeneration.
- `services/rendering-job` has no Python-level deps on other workspace packages; called at runtime over HTTP from `services/deepsearch-monitor` via `deepsearch-utils/rendering_utils.py`
- `packages/siglip2-triton-client` is a workspace leaf used by `ngsearch-backend`; `services/siglip2-triton` is its standalone server counterpart
- `packages/vision-endpoint` provides LangChain-based VLM clients, CLIP/SigLIP2 Triton clients, image validation, and metadata generation; used by `services/deepsearch-monitor` and `services/deepsearch_api`
- Package manager: **uv workspace** — all packages except `services/rendering-job` and `services/asset-graph-builder` are workspace members (see Known Workspace Limitations for why). `services/explorer` is a Node project, also excluded.
- **Test data paths** in package tests must use `pathlib.Path(__file__).parent` to anchor paths relative to the test file, not the CWD. Bare relative paths like `"tests/..."` break when pytest is run from the workspace root.

## Docker

`docker/Dockerfile.usdsearch` is a single combined image that includes all workspace services **except** `services/rendering-job`, `services/asset-graph-builder`, and `services/siglip2-triton` (excluded for the same reasons they are excluded from the workspace — see Known Workspace Limitations).

Other Dockerfiles:
- `docker/Dockerfile.siglip2-triton` — Triton Inference Server image for SigLIP2 ONNX models; build context is `services/siglip2-triton/` (where the model weights live).
- `docker/Dockerfile.explorer` — multi-stage `node:20-alpine` → `nginx:1.27-alpine` build for the React front-end. Build context is the repo root. Not part of the unified `usdsearch:latest` image. The compose stack at `infra/compose/explorer.yml` builds it with `REACT_APP_API_URL=/api`; `services/explorer/nginx.conf` reverse-proxies `/api/*` to `deepsearch-api:8000`. `REACT_APP_VERSION` is injected from `VERSION.md`.
- `docker/Dockerfile.kit` — GPU-accelerated rendering image (Omniverse Kit subprocess workers); build context is `services/rendering-job/`. Fetches packman via sparse git checkout of `tools/packman` from the **public** `NVIDIA-Omniverse/kit-app-template` repo (tag controlled by `ARG KIT_APP_TEMPLATE_TAG=110.1.0`). The repo's own `tools/packman/config.packman.xml` (public CloudFront CDN) is used directly — no local override.
- `services/deepsearch_api/docker/Dockerfile` — slimmer single-service image for deepsearch-api only.

**Build** (from repo root — build context must be the workspace root):
```bash
docker build -f docker/Dockerfile.usdsearch -t usdsearch:latest .
```

**Run a specific service** — override CMD at launch. Each service has its own module entrypoint (e.g. `uvicorn deepsearch_api.main:app`, `python -m monitor.src.monitor_worker`, `python -m storage.src.run_cron`); see the corresponding compose file for the canonical command:
```bash
docker run -e ... usdsearch:latest uvicorn deepsearch_api.main:app --host 0.0.0.0 --port 8000
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
- **`uv sync` extras in `docker/Dockerfile.usdsearch`**: `--extra search-backend`, `--extra storage-api`, and `--extra pillow` are already activated by service-level `search-utils[...]` dependencies but are kept for explicitness. `--extra tools` (tqdm) is covered by `vision-endpoint`'s direct dep.
- **Passing args to `docker compose run` with `bash -c`**: Use `bash -c '...' -- "$@"` — not `bash -c "... $@"`. The double-quote form expands `$@` in the outer shell, splitting multi-word args across the command string and bash's `$0`, so pytest receives `-n` without its value. The single-quote form with `-- "$@"` passes args as positional parameters to the inner shell.

**`docker compose up --build`**: CI scripts that use compose files containing a `build:` section (`siglip2-triton.yml`, `asset-graph-service.yml`, `asset-graph-builder.yml`, `rendering-job.yml`) pass `--build` to `docker compose up` so containers are always rebuilt from current source. Scripts that only start pre-built infrastructure images (redis, opensearch, neo4j, minio, storage-apis) do not need `--build` and are left unchanged.

## Helm Chart

The `usdsearch` Helm chart lives at `helm/usdsearch/`. It deploys the full USD Search stack to Kubernetes: deepsearch, ngsearch, deepsearch-crawler, rendering-service, asset-graph-service, s3proxy (local sub-charts), plus vendored dependencies (OpenSearch, Redis, Neo4j, NGINX).

### Versioning (Dual Git-Tag Scheme)

Three independent tag namespaces control versioning:

| Tag Pattern | Controls | Example |
|---|---|---|
| `chart-X.Y.Z` | Helm chart `version` in Chart.yaml | `chart-1.4.0` |
| `images-X.Y.Z` | Helm chart `appVersion` + Docker image tags for NGC | `images-1.4.0` |
| Bare `X.Y.Z` | Python packages via `uv-dynamic-versioning` | `1.0.0` |

- **Chart.yaml** is checked in with placeholder `0.0.0-dev` values — CI stamps real versions at package time via `helm/scripts/version.sh`.
- On non-tagged commits, versions get a `-N` suffix (commits since last matching tag).
- `uv-dynamic-versioning` uses `pattern = "default-unprefixed"` and only matches bare tags — no interference with prefixed tags.

### Running Helm Tests

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

### CI Pipeline (Helm)

Defined in `ci/helm/gitlab-ci.yml` (included from root). Helm jobs slot into the shared root pipeline stages: `lint` (helm-lint, helm-template-validate) → `init` (build-helm-readme) → `build` (helm-package) → `test` (helm-unit-test, helm-integration-test) → `publish` (helm-publish-ngc, helm-publish-readme).

- Jobs trigger on `changes: helm/**/*` and `ci/helm/tests/**/*` — Python-only PRs skip helm CI entirely.
- Tag pushes matching `chart-*` trigger the full lint → package → test → publish pipeline.
- Publishing pushes to NGC at `omniverse/deeptag-internal/usdsearch`.

### Releasing a Chart Version

Push a tag in the relevant namespace (or both together on the same commit) — CI handles the rest:
```bash
git tag chart-1.4.0      # Helm chart version → NGC chart publish
git tag images-1.4.0     # appVersion + Docker image tags → NGC image publish
git push origin chart-1.4.0 images-1.4.0
```

## Quickstart Compose Stack

Top-level compose files at the repo root run a complete local dev stack (separate from the per-service files under `infra/compose/` used by CI). **Requires Docker Compose >= v2.26** — earlier versions (incl. the v2.20 shipped with Ubuntu 22.04) fail with `services.siglip2-triton conflicts with imported resource` because the gpu-plugins overlay extends a service that the root `docker-compose.yml` brings in via `include:`.

- `docker-compose.yml` — base stack: opensearch, redis, neo4j, siglip2-triton (CPU-mock), deepsearch-api, info-endpoint, asset-graph-service, deepsearch-crawler, indexing-crawler, monitor-crawler, embedding workers (image/thumbnail), `monitor-worker-asset-graph-generation`, `graph-builder` (Kit image, `MODE=graph-builder`, no GPU reservation), and the nginx gateway. **No Explorer WebUI by default** — add the `docker-compose.web-ui.yml` overlay to include it.
- `docker-compose.web-ui.yml` — overlay: Explorer React front-end. Adds the `explorer` service (built from `docker/Dockerfile.explorer`) and swaps the gateway's nginx config from `gateway.conf` to `gateway.web-ui.conf` (via the `!override` volumes tag) so `/`, `/ui/`, `/static/`, and the root-static catch-all proxy to the explorer container. Without this overlay, the gateway's `/` redirects to `/docs/` instead of `/ui/`.
- `docker-compose.gpu-plugins.yml` — overlay: real SigLIP2 (GPU), `rendering-job` (Kit), and the GPU plugin workers `monitor-worker-thumbnail-generation` and `monitor-worker-rendering-to-embedding`.
- `docker-compose.vlm-plugins.yml` — overlay: VLM metadata workers. Provider is selected via `METADATA_GENERATION_VLM_SERVICE` (default `openai`); supported values match `vision_endpoint.vlm.base_vlm.VLMService` — `openai`, `inference_hub` (NVIDIA Inference Hub), `anthropic`, `nim`, `azure_openai`, `google`, `qwen`, `qwen_alibaba`, `mistralai`. The matching `<PROVIDER>_API_KEY` (e.g. `INFERENCE_HUB_API_KEY`) must be set on the host shell; the overlay's `x-vlm-worker-env` anchor null-pass-through-forwards every supported provider key, so unset ones stay omitted from the container.
- `docker-compose.s3proxy-auth.yml` — overlay: deploys s3proxy as a credential-translating reverse proxy for authenticated non-AWS S3 endpoints. Reads upstream credentials from the same `S3_STORAGE_AWS_*` host env vars the stack already uses, and exposes the bucket locally at `http://s3proxy:80` with `S3PROXY_AUTHORIZATION=none`. Required when using a custom S3 endpoint (non-`*.amazonaws.com`) with GPU plugins — Kit's native client library cannot authenticate to non-AWS endpoints (see Known Pitfalls). All services are redirected through s3proxy for consistency (same pattern as the Helm chart's sub-chart).
- Infra services (`redis`, `opensearch`, `neo4j`, `siglip2-triton` base) come in via `include:` from `infra/compose/<svc>.yml` plus quickstart-only overrides at `infra/compose/quickstart/<svc>.override.yml`.
- All services declare `restart: unless-stopped` (via the `x-usdsearch-image` anchor for image-based services, or explicitly for infra/gateway/explorer).
- `graph-builder` shares `docker/Dockerfile.kit` with `rendering-job` but is tagged `usdsearch-graph-builder:latest` (separate from the renderer's `usdsearch-rendering-job:latest`); BuildKit cache makes the second build a near-instant cache-hit.

**Gateway routes** (`infra/quickstart/gateway.conf` — baseline, no WebUI):
- `/` → 302 to `/docs/`
- `/docs/` → static Swagger UI (nginx serves `helm/usdsearch/docs/index.html` + `helm/usdsearch/docs/openapi.json` mounted into `/usr/share/nginx/docs/`; same files the helm chart ships in its static-content configmap). The gateway has a healthcheck that probes `/docs/` since it requires no upstream. The merged spec is regenerated by `scripts/build-openapi-docs.sh` (default output: `helm/usdsearch/docs/openapi.json`).
- `/search`, `/search_hybrid`, `/vlm_validate/...`, `/images` → deepsearch-api
- `/info`, `/process` → info-endpoint
- `/asset_graph/`, `/dependency_graph` → asset-graph-service

With the `docker-compose.web-ui.yml` overlay, the gateway is reconfigured from `infra/quickstart/gateway.web-ui.conf` and additionally serves:
- `/` → 302 to `/ui/` (overrides the docs redirect)
- `/ui/`, `/static/`, and a root-static catch-all → explorer

**Smoke tests**: `./scripts/quickstart-smoke.sh` exercises every gateway-proxied API and prints PASS/FAIL per endpoint. Run it after `docker compose up` reports services as healthy. The `/deploy-usdsearch` skill (Local branch) calls it automatically as its final step before handing control back to `/quickstart`. Honors `BASE` (gateway URL), `ASSET_GRAPH_TIMEOUT` (seconds the AGS section waits for the first graphed scene; default 15), `BASIC_AUTH=user:password` (threaded through every curl call as `-u`), and `WEB_UI=on|off` (default `off`). When the WebUI overlay is enabled, set `WEB_UI=on` so the script asserts `/ → /ui/` and `/ui/ → 200`; otherwise it asserts `/ → /docs/` and skips the `/ui/` check.

**Nucleus mode requires HTTP Basic Auth on every gateway request.** When `STORAGE_BACKEND_TYPE=nucleus`, the gateway gates the deepsearch-api / info-endpoint / asset-graph routes with Basic Auth using the same `OV_USERNAME` / `OV_PASSWORD` the stack was started with. Browsers show a credential prompt; smoke + curl-from-host calls need `BASIC_AUTH="$OV_USERNAME:$OV_PASSWORD"` (smoke script) or `-u "$OV_USERNAME:$OV_PASSWORD"` (raw curl). Without this, every endpoint returns 401 — which is misleading because the stack itself is fine. S3 backends run anonymously, no auth needed.

**End-to-end test harness** at `ci/quickstart/`: parametric runner (`run_tests_quickstart.sh`) + sequential driver (`run_all.sh`) covering 6 configs — `public-s3`, `public-s3-vlm`, `private-s3`, `private-s3-vlm`, `nucleus`, `nucleus-vlm`. Each runner brings up base + GPU plugins (+ VLM overlay where applicable) via `docker compose up -d --wait --build`, polls `/search` until ≥1 indexed asset, runs the smoke script with bumped timeouts, and tears down with `down -v --remove-orphans` on EXIT. Auto-sets `BASIC_AUTH` from `$OV_USERNAME:$OV_PASSWORD` for nucleus configs. Not in GitLab CI yet — depends on GPU runner availability that isn't currently provisioned. Caller exports credentials under domain-specific names (`DS_STAGING_AWS_*` for staging S3) which the configs map to canonical names (`S3_STORAGE_AWS_*`); for Nucleus the canonical names `OV_USERNAME` / `OV_PASSWORD` are used directly.

**Detecting graphed assets via `/search`**: `/search` and `/search_hybrid` accept `return_root_prims=true` (and `return_default_prims=true`), which annotate each hit with its prims pulled from the asset graph store. A non-empty `root_prims` proves the `asset_graph_generation` worker has already finished that asset — useful for tests or UIs that need to filter to graphed scenes deterministically (one query, no probing of `/asset_graph/usd/prims`).

## Local Filesystem Backend (s3proxy)

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

## Build and Install

```bash
# Pre-step: fetch the pre-compiled Omniverse protobuf packages that
# `search-utils` force-includes into its wheel. Required before the first
# `uv sync`. Pulls 5 packages (~few MB total) from a public NVIDIA
# CloudFront CDN; no credentials needed. Requires `7z` (apt: p7zip-full).
./build/build_search_utils.sh

# Install all workspace members in editable mode (requires access to NVIDIA PyPI indexes)
uv sync

# Install a single package only
uv sync --package search-utils
uv sync --package ngsearch-storage
```

The pre-step populates `packages/search-utils/_build/{discovery.client.py,
idl.py, omniverse_connection, omniverse.auth.client.py, tag_idl_client}/`,
referenced by `[tool.hatch.build.targets.wheel.force-include]` in
`packages/search-utils/pyproject.toml`. `_build/` is `.gitignored`
(`packages/search-utils/.gitignore:58`); the script regenerates it on
demand. The same script runs in `docker/Dockerfile.usdsearch:34`, so the
Docker and local-`uv sync` paths share the mechanism. Skipping it
produces:

```
FileNotFoundError: Forced include not found:
.../packages/search-utils/_build/discovery.client.py/omni
```

## Running Tests

```bash
# Run tests for a specific workspace member
uv run --package ngsearch-storage pytest services/storage/tests/

# Run a single test file
uv run --package deepsearch-crawler pytest services/deepsearch-crawler/tests/test_consumer.py -v

# Run a single test by name
uv run --package search-utils pytest packages/search-utils/tests/ -k "test_redis_cache" -v
```

## Skill Tests

Claude Code skills under `.claude/skills/` ship with their own test suites at `ci/skills/<skill-name>/`. Two layers are exercised: a static lint of `SKILL.md` (frontmatter, sections, `bash -n` over every fenced block, probe/table key consistency) and a behavioral test of the L1 pre-flight bash block under a sandboxed `PATH` populated with mock `docker` / `git` / `nvidia-smi` binaries that read `MOCK_*` env vars.

```bash
# Run all skill suites
./ci/skills/run_all.sh

# Run a specific skill suite
./ci/skills/deploy-usdsearch/run_tests.sh

# Run a single test
./ci/skills/deploy-usdsearch/run_tests.sh -k test_lfs_some_pointers
```

The suite resolves `REPO_ROOT` via `git rev-parse --show-toplevel`, so it works from any cwd. `pytest` + `pyyaml` are pulled in ephemerally via `uv run --with`, so no project-wide dependency changes are needed. Coverage reporting is explicitly disabled via `--no-cov` since the skills under test are markdown, not Python.

The `skills-lint` job lives in the root `.gitlab-ci.yml`, slots into the `lint` stage, and depends on `repo-init` so it inherits the prebuilt uv environment / pytinyexr / search-utils artifacts. It is gated on `changes: .claude/skills/**/* | ci/skills/**/*` — Python-only or helm-only MRs skip it entirely.

## Lint / Format

Each package that has lint tooling can be run via:
```bash
uv run --package search-utils black packages/search-utils/search_utils/
uv run --package search-utils isort packages/search-utils/search_utils/
```

## Pre-commit Hooks

Always run `pre-commit run --all-files` (or at minimum `pre-commit run` against staged files) before publishing changes — i.e. before any `git push`, MR creation, or tag push. The hooks defined in `.pre-commit-config.yaml` cover yaml/whitespace/large-file checks, `black`, `flake8`, and `apply-spdx-headers` (which rewrites SPDX/Apache-2.0 headers via `scripts/apply_spdx_headers.py`). The SPDX hook is a fixer: if it modifies files, re-stage and commit again before pushing so the published tree matches what CI will see.

## Third-Party Notices

`THIRD_PARTY_NOTICE.md` at the repo root + the `licenses/` directory list every third-party Python package shipped with USD Search at runtime, with name, version, SPDX license, homepage, and per-package license text. They are regenerated by `scripts/generate_third_party_notice.sh` (bash entry point) which calls `scripts/_generate_third_party_notice.py` (HTTP + wheel/sdist extraction). Re-run after any `pyproject.toml` change.

Four production-dep trees are enumerated (test/dev groups excluded) — the three latter are the same services that are excluded from the workspace and thus need their own lock:

- root `uv.lock`
- `services/rendering-job/uv.lock`
- `services/asset-graph-builder/uv.lock`
- `services/siglip2-triton/docker/uv.lock`

All four are tracked, even though `uv.lock` is in `.gitignore` — `.gitignore` carries explicit `!`-exceptions for these four paths. Adding another excluded service in the future requires another exception line.

The script passes `--frozen` to every `uv export` so reruns never silently mutate a lockfile. Cached PyPI metadata + downloaded artifacts live under `_tmp/license-cache/` (already gitignored via the catch-all `_tmp` rule).

Same-name-different-version entries are kept as separate rows, one per `(name, version)`. Today this captures two known workspace splits: `pydantic` 1.x vs 2.x and `websockets` 10.4 vs 16.0.

When a wheel/sdist on PyPI does not ship a `LICENSE*`/`COPYING*`/`NOTICE*` file, the script falls back to fetching one from the project's GitHub repository (URL pulled from PyPI's `project_urls` / `home_page`) by probing common filenames at `https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{name}` — currently `LICENSE`, `LICENSE.txt`, `LICENSE.md`, `LICENSE.rst`, `LICENSE-MIT`, `LICENSE-APACHE`, `LICENSE-APACHE-2.0`, `COPYING`, `COPYING.txt`, `COPYING.md`, `NOTICE`. Hits and misses are cached under `_tmp/license-cache/github/`. If a future package shows up as `_(not retrieved)_`, either its declared GitHub URL is missing/wrong or its LICENSE file uses an unknown filename — extend `GITHUB_LICENSE_FILENAMES` in `scripts/_generate_third_party_notice.py`.

## CI Pipeline

Pipeline runs on: MR events, commit tags, default branch, and `release/*` branches.

**Stages**: `init` → `lint` → `unit` → `build` → `publish-images` → `test` → `sevan-integration` → `security` → `publish` → `deploy` → `pages-prepare` → `pages`. Helm jobs share the root stages (`lint`, `init`, `build`, `test`, `publish`) rather than living in their own helm-prefixed stages.

External template includes:
- `omniverse/deeptag/ci-cd-storage-backends` → `nucleus.yml`
- `omniverse/deeptag/gitlab-templates` → `deepsearch-build-upload-pipeline.yaml`
- `local: ci/helm/gitlab-ci.yml` → Helm chart lint, package, test, publish

The Claude Code skill lint + behavioral tests (gated on `changes: .claude/skills/** | ci/skills/**`) are defined inline in the root `.gitlab-ci.yml` as `skills-lint`, not in a separate include.

**`uv` is not pre-installed on CI runners** — each job that needs it must run `pip install uv` first.

**Git LFS is skipped** (`GIT_LFS_SKIP_SMUDGE: "1"`) in jobs that don't need model weights: `build-search-utils`, `unit-search-utils`, `unit-storage`, `unit-vision-endpoint`, `unit-usdsearch`, `unit-info-endpoint`. **Exception**: `build-siglip2-triton` must NOT set this variable — it COPYs the 7.2 GB ONNX weights from `model_repo/` (stored in Git LFS).

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

## Known Pitfalls

- **Do not bump the `usdsearch` Docker base to Python 3.14**: The image must stay on `python:3.13-bookworm` (builder) + `nvcr.io/nvidia/distroless/python:3.13-v4.0.6-dev` (runtime). A previous attempt to move to 3.14 broke the Nucleus connection at runtime — symptoms looked like a TLS/certificate verification failure during the Omniverse client handshake; root cause not yet pinned down. Until it's understood and fixed, keep `docker/Dockerfile.usdsearch` on 3.13 and do not add `3.14` to `build/build_pytinyexr.sh`'s `PYTHON_VERSIONS` default for production builds.
- **pytest-asyncio mode**: Services use explicit `@pytest.mark.asyncio` on each test function and `@pytest_asyncio.fixture` on async fixtures (e.g. `services/asset-graph/tests/conftest.py`). Do **not** add `asyncio_mode = "auto"` to any `pyproject.toml` — it silently changes fixture resolution and breaks async tests in these services.
- **VLM `max_tokens`**: All VLM configs default to `max_tokens=4096`. Do not lower this — thinking/reasoning models (e.g. Gemini Flash Preview, o3/o4 variants) consume ~900 tokens on internal reasoning, leaving too few for a complete structured JSON response at 1024.
- **Redis consumer group start ID**: `search_utils.streams.redis.RedisStreamWorker.connect_consumer()` creates the consumer group with `id="0"` (read from the beginning of the stream). Do not change this to `$` — if a service starts after messages are already in the stream, `$` would cause the group to miss all existing entries. The `id` only applies at first creation; subsequent reconnections resume from the group's last-delivered position.
- **`DeepSearchConsumer.close()` in async fixtures**: Always call `await consumer.close()` in the fixture teardown. The constructor spawns a background `_connect` task; without an explicit cancel + await, pytest reports "Task was destroyed but it is pending!" for every fixture instance when the event loop closes.
- **`asset-graph` prim responses and `default_prim`**: The `/asset_graph/usd/prims` endpoint uses `response_model_exclude_none=True`. `Prim.default_prim` is `bool | None` — non-default prims have `None` and the key is absent from the JSON. Always use `prim.get("default_prim")` when iterating an unfiltered prim list; `prim["default_prim"]` raises `KeyError` on non-default prims.
- **pydantic-settings: field-level `alias` overrides `env_prefix`**: When a `BaseSettings` subclass sets `env_prefix="foo_"` and a field declares `Field(alias="bar")`, the field is read from the env var `BAR` (uppercased alias) — **not** `FOO_BAR`. Unrecognized prefixed names are silently ignored, so the default value sticks. Affected configs in this repo include `AGSPluginConfig` (`packages/plugins/plugins/asset_graph_generation.py` — reads `ASSET_GRAPH_SERVICE_ENDPOINT`, `KIT_WORKER_SERVICE_ENDPOINT`) and several search-backend models in `services/deepsearch_api/.../search_backend/models.py`. Before adding new env vars, grep the config class for `Field(alias=...)` and use the bare alias if present.
- **Monitor worker `job_item_type` default skips `priority` jobs**: `DeepSearchMonitorWorkerConfig.job_item_type` defaults to `[JobItemType.normal, JobItemType.none]` (`services/deepsearch-monitor/monitor/src/config.py`). Jobs enqueued with `job_type="priority"` (e.g. by `info-endpoint`'s on-demand `/process` route) are silently filtered out at `monitor_worker.py:200`. Set `DEEPSEARCH_MONITOR_WORKER_CONFIG_JOB_ITEM_TYPE='["priority","normal","none"]'` on every worker that should drain the full queue. The quickstart compose files do this for all 8 workers.
- **Empty-string env var breaks anonymous public-S3 access**: `S3StorageClient` (`packages/search-utils/.../storage_client/s3/client.py:163`) only registers `disable_signing` when `self.config.aws_access_key_id is None`. pydantic-settings reads `S3_STORAGE_AWS_ACCESS_KEY_ID=""` as the empty string `""` (not `None`), so the disable-signing branch is skipped and aioboto tries to sign requests against the public bucket → `NoCredentialsError`. The fix in all top-level compose files is YAML-null pass-through (`KEY:` with no value) for credential env vars — this forwards the var from the host if set and OMITS it from the container otherwise. Same fix for the rendering-job's list-form environment uses bare `- KEY` entries. Do not revert these to `${VAR:-}` empty-string defaults.
- **VLM provider env vars: compose-level vs library-level naming differ**: `MetadataGenerationConfig` declares `model_config = {"env_prefix": "metadata_generation_"}` (`packages/vision-endpoint/.../metadata/metadata_generation.py:60-63`), so the worker reads `METADATA_GENERATION_VLM_SERVICE` — **not** `VLM_SERVICE`. The `vision-endpoint` README and standalone notebook examples use `VLM_SERVICE`; that's a different code path (the validation config) and does not affect the metadata worker. Set `METADATA_GENERATION_VLM_SERVICE=openai|inference_hub|anthropic|nim|azure_openai|google|qwen|qwen_alibaba|mistralai` and the matching `<PROVIDER>_API_KEY` (e.g. `INFERENCE_HUB_API_KEY`). The provider's own `*_API_KEY` env var has no `metadata_generation_` prefix because it's read by `<Provider>VLMConfig` whose `env_prefix` is the bare provider name (e.g. `inference_hub_`).
- **Kit client library cannot authenticate to non-AWS S3 endpoints**: URLs not matching `*.s3.*.amazonaws.com` are routed through the base HTTP provider in Kit's `HttpProviderFactory.cpp` (`services/rendering-job/deepsearch_rendering_job/kit.py:45`), which ignores configured S3 credentials. The rendering-job and graph-builder use Kit to open USD files, so they cannot open assets from authenticated non-AWS endpoints (MinIO, Ceph, s3proxy, etc.) directly. Workaround: use the `docker-compose.s3proxy-auth.yml` overlay, which deploys s3proxy as a credential-translating proxy (`S3PROXY_AUTHORIZATION=none` internally) and routes all services through it for consistency. The Helm chart's s3proxy sub-chart does this by default. Not needed for real AWS S3 (Kit handles `*.s3.*.amazonaws.com` natively) or without GPU plugins (Python services use aioboto3 which handles SigV4 for any endpoint).
## Removed / Deprecated Backends

- **Nucleus backend is being deprecated**: The `/deploy-usdsearch` skill (Local branch) flags this when listing storage backends — when adding new code paths or examples, prefer S3 over Nucleus. The Nucleus client itself remains supported and is still tested via `ci/quickstart/configs/nucleus*.env`, but the path forward is S3 (public or private).

## Known Workspace Limitations

- `services/rendering-job` is **not** a workspace member: requires `websockets>=12.0` which conflicts
  with `deepsearch-utils`' `websockets~=10.4` pin (`ws_server.py` uses the `max_queue` param removed
  in v11). Fix: update `deepsearch_utils/farm/ws_server.py` to the new websockets API.
- `services/asset-graph-builder` is **not** a workspace member: poetry-based, requires pydantic<2 which
  conflicts with the rest of the workspace (pydantic v2). Migrate when pydantic v2 is adopted.
- `services/explorer` is **not** a workspace member: it is a Node.js (Create React App) project, not
  Python. It is built independently via `docker/Dockerfile.explorer`.
- **OpenSearch 3.x (Lucene 10) silently breaks the `~` complement operator in regexp queries**: queries
  like `{"regexp": {"field": {"value": "~(pattern)", "flags": "ALL"}}}` return 0 hits instead of the
  complement set. Intersection `&` still works. Fixed in `services/deepsearch_api` by detecting
  top-level `~(inner)` patterns and rewriting them as `{"bool": {"must_not": {"regexp": ...}}}`, which
  is correct on both 2.x and 3.x. Do not add new regexp filter paths using `~` directly.
