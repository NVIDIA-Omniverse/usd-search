# Changelog

All notable changes to this repository are documented here.

---

## [Unreleased] — Discovery-first skills

### Changed
- `.claude/skills/quickstart/SKILL.md` rewritten (v2.0.0) as a **discovery door**, not a stack-runner. Asks exactly two questions (deployment-or-not, then search query) and saves the top 5 thumbnails to `./quickstart-results/<slug>/` with a `manifest.json` for downstream skills to pick up. Default endpoint is the shared NVIDIA dev deployment at `https://search.simready.omniverse.nvidia.com` (verified publicly reachable). Triggers reshaped from "set up local dev" phrasings to discovery phrasings (`try usd search`, `getting started`, `tour`, `first time`).
- `.claude/skills/deploy-usdsearch/SKILL.md` created (v2.0.0). Absorbs the previous `quickstart`'s docker-compose runbook (GPU/VLM/Nucleus questionnaires, smoke tests) as its **Local** branch and migrates the helm chart deployment runbook from `.claude/commands/deploy-usdsearch.md` as its **Helm** branch. Single Q at the top picks local vs helm; both branches end at "healthy + smoke passed" and set `USD_SEARCH_API_URL` so `/quickstart` can resume against the new stack.

### Added
- `docs/skills-user-journeys.md` — ASCII DAG of the new first-time UX, including the four branches (simready / own URL / own OpenSearch / deploy) and the auto-fetch step that ends in a saved `quickstart-results/<slug>/` directory.
- `docs/skills-discoverability-plan.md` — design notes, including verified live traces for journey A (simready) and journey C (slim API + remote OpenSearch via `docker run --network host`), the inline `scoring_config` template required against bare-API endpoints, and the gateway-vs-versioned route auto-detection rule.

### Removed
- `.claude/commands/deploy-usdsearch.md` — content migrated into `.claude/skills/deploy-usdsearch/SKILL.md` under the **Helm** branch.

### Earlier in this Unreleased window
- `.claude/skills/search-assets/SKILL.md` and `.claude/skills/find-similar/SKILL.md` — Claude Code skills exposing `/search-assets` and `/find-similar`. Mirror the `quickstart` skill's frontmatter format (name, description, triggers, allowed-tools).
- Removed `.claude/commands/search-assets.md` and `.claude/commands/find-similar.md` (superseded by the skill-format equivalents).

---

## [0.1.1] — 2026-05-06 — Explorer in-tree

- Added `services/explorer/` (DeepSearch Explorer, React 18 + Chakra UI),
  `docker/Dockerfile.explorer` (multi-stage Node → nginx), and
  `infra/compose/explorer.yml`. Layered compose recipe in the README.
- Added `VERSION.md` (`0.1.1`); Explorer header chip now reads it at build
  time instead of showing "v UNKNOWN".

---

## [Unreleased] — Container image publish stage

### Added
- `publish` CI stage in `.gitlab-ci.yml` that re-tags the three images produced by the `build` stage (`usdsearch`, `rendering-job`, `siglip2-triton`) and pushes them to `$PUBLISH_REGISTRY` (default `nvcr.io/omniverse/deeptag-internal`). The target registry is configurable per project or per pipeline so the same job template works for the GitLab project registry, NGC, Docker Hub, or any other OCI-compatible registry. Auth is taken from `PUBLISH_REGISTRY_USERNAME` / `PUBLISH_REGISTRY_PASSWORD`, falling back to `NGC_API_KEY` for `nvcr.io`.
- Jobs run automatically (blocking) on `$CI_COMMIT_TAG` and are manual otherwise; on the default branch they additionally publish a `:latest` tag.

---

## [Unreleased] — NVCF deploy stage

### Added
- `deploy` CI stage in `.gitlab-ci.yml` with `deploy-nvcf-rendering-job` and `deploy-nvcf-siglip2-triton` jobs. Each creates or updates an NVCF function pointing at the image just published by the matching `publish-*` job and waits for `ACTIVE`. Manual trigger only.
- Both jobs extend `.deploy-nvcf-container` from `omniverse/gen-ai/ci-templates/gitlab-templates` (same template `deepsearch-rendering-job` uses in production); per-service variables override function name, inference and health URL, GPU and instance type, and scaling. `NGC_CLI_API_KEY` (or `NGC_API_KEY`) must be set as a project CI variable.
- `ci/create_function.py` shipped locally so the upstream template's `before_script` skips its `git clone` of the gen-ai template repo and runs ours instead. Adds an `INFERENCE_PROTOCOL` env var (`HTTP` default → `api_body_format=CUSTOM`, `GRPC` → `api_body_format=PREDICT_V2`) so siglip2 deploys as a gRPC function on Triton's `8001` port while rendering-job stays HTTP.

---

## [Unreleased] — `deepsearch_api` dead-code sweep

Pure cleanup. No behavior change, no API contract change, no dependency delta. Default callers see byte-identical responses.

### Removed
- `services/deepsearch_api/deepsearch_api/ng_search/` — legacy NGSearch client; `get_ngsearch_client()` returned `None` unconditionally and `NGSearch_Client` was never instantiated.
- `services/deepsearch_api/deepsearch_api/embedding/` — duplicate of `search_backend/embeddings.py`.
- `services/deepsearch_api/deepsearch_api/routers_v1/` — no V1 child routers were registered. Surviving symbols moved out (see "Added" below).
- `services/deepsearch_api/deepsearch_api/main_yappi.py` — yappi profiling entry point; not referenced by any Dockerfile, compose file, or CI script. Profiling section dropped from `services/deepsearch_api/README.md`.
- `services/deepsearch_api/deepsearch_api/routers_v2/search_results_helper.py` — only consumer was its own unit test, also removed.
- `services/deepsearch_api/deepsearch_api/config/backend.yaml` — only read by the deleted NGSearch backend.
- `MainServiceSettings.enable_v1_endpoints` (and matching empty `/v1` router mount + V1 tags-metadata) and `get_service_public_info()` (only call site was already commented out).
- Dead test scaffolding: `unhealthy_client` / `total_search_results` fixtures in `tests/conftest.py`, the `test_process_image_results` test in `tests/test_search_v2.py`, and the matching `embedding_client` import.
- `packages/deepsearch-utils/deepsearch_utils/dl_backend_utils.py` (+ its test) — only consumer was its own unit test.

### Added
- `services/deepsearch_api/deepsearch_api/exceptions.py` — relocated `AuthenticationError`, `NoneTokenProvided`, `AGSServiceUnavailable`, `AGSServiceConnectionError` from the deleted `ng_search/exceptions.py`.
- `services/deepsearch_api/deepsearch_api/config.py` — relocated `DeepSearchBackendConfig`. Field names and `DEEPSEARCH_BACKEND_*` env-var bindings preserved verbatim (no breaking changes).
- `services/deepsearch_api/deepsearch_api/_constants.py` — centralised image-magic-byte signatures, an `IMAGE_MAGIC_TO_MIME` map shared by the inbound base64 validator (`routers_v2/models.py`) and the outbound Content-Type detector (`routers_v3/images.py`), `MAX_IMAGES_PER_VALIDATION = 8`, and the `HEALTH_URI` / `METRICS_URI` test constants.
- `services/deepsearch_api/deepsearch_api/health.py` — `HealthResponse`, `response_headers`, and the `/health` route relocated from the deleted `routers_v1/`.
- `services/deepsearch_api/deepsearch_api/models.py` — `Prim` and `Prediction` Pydantic models relocated from the deleted `routers_v1/base_models.py`.

### Changed (renames — purely internal, no env-var or public-API impact)
- `_clip_client` → `_siglip2_client` (model is SigLIP2, not CLIP).
- `log_and_measure` → `track_inference_metrics`.
- `_filter_by_scene_assets` → `_get_scene_asset_whitelist` (returns a whitelist; doesn't filter).
- `_process_image_queries` → `_download_remote_images` (downloads remote images; doesn't query anything).
- The single 95-line `get_image_by_asset_url` in `routers_v3/images.py` was split into two narrower helpers — `load_image_by_key(image_key, image_loader)` for direct cache lookups (no OpenSearch hop, no ACL) and `resolve_image_by_asset_url(asset_url, ...)` for the full ACL → OpenSearch term query → image-id extraction → cache load path. Input validation moved up into the `get_image` FastAPI handler that owns the dispatch. Tracer span names rebuilt to be honest. Both `routers_v3/search_v3.py` call sites only ever passed `asset_url=..., image_key=None`, so they switch to `resolve_image_by_asset_url` directly.
- Inline image-magic-byte literals in `routers_v2/models.py` and `routers_v3/images.py` replaced with named imports from `_constants`.

### Notes
- `get_instance_prims_from_search_results` was **not** renamed.
- Pydantic config fields `asset_graph_service_n_retries` and `asset_graph_service_n_parallel_requests` were **not** renamed to `max_*` — that would break `DEEPSEARCH_BACKEND_*` env-var bindings for downstream deployments. A separate PR with `Field(alias=...)` migration can do that safely.
- `packages/deepsearch-api-client/` (auto-generated) untouched; its V1 client classes will drop naturally on the next regen against the trimmed `/openapi.json`.

---

## [0.1.0] — 2026-04-22 — Initial monorepo consolidation

### Summary

Eight separate source repositories (`search-utils`, `ngsearch`, `deepsearch-crawler`,
`deepsearch`, `deepsearch-api`, `asset-graph-service`, `deepsearch-rendering-job`,
`siglip2-onnx-triton-server`) consolidated into a single `uv` workspace monorepo.

---

### Added

#### Workspace infrastructure
- Root `pyproject.toml` as a `uv` workspace root (non-package) with shared index
  configuration for NVIDIA PyPI mirrors and the `deepsearch-group` GitLab package registry.
- Root `.gitignore` covering Python artifacts, uv/venv, test/coverage, and IDE files.
- Root `.gitlab-ci.yml` that includes per-service CI configs and will grow as services are
  fully migrated.

#### Packages
- **`packages/search-utils`** — Shared infrastructure library: storage clients
  (S3, Azure, Nucleus, multi-backend), Elasticsearch/OpenSearch, Redis Streams,
  caching utilities, observability, and logging helpers. Migrated from `search-utils` repo.
  Added `setup_logging_from_yaml()` to consolidate YAML-based logging bootstrap from
  downstream services.
- **`packages/ngsearch-backend`** — CLIP/SigLIP search backend for NGSearch
  (Elasticsearch, OpenSearch, Triton). Extracted from `ngsearch/modules/ngsearch_backend/`.
- **`packages/deepsearch-utils`** — DeepSearch plugin support utilities: farm client,
  rendering service client, k8s_renderer, image processing, secure pickle. Extracted from
  `deepsearch/modules/deepsearch_utils/`.
- **`packages/deepsearch-api-client`** — Generated OpenAPI client for the DeepSearch API
  (V2/V3). Migrated from `deepsearch-api/deepsearch-api-client/`; poetry → uv/hatchling.
- **`packages/asset-graph-client`** — Generated OpenAPI client for the Asset Graph Service.
  Migrated from `asset-graph-service/asset-graph-service-api-client/`; poetry → uv/hatchling.
  Replaces the external `asset_graph_service_client` package from the deepsearch-group index.
- **`packages/siglip2-triton-client`** (source only) — gRPC client for the SigLIP2 Triton
  inference server, with text tokenizer for client-side tokenization. Copied from
  `siglip2-onnx-triton-server/`. Not yet a workspace member: `vision-endpoint[siglip2]` from
  the deepsearch-group index pins a dep on the external package, which conflicts until a
  `>=0.3.0` tag is cut in this repo.

#### Services
- **`services/deepsearch-crawler`** — Storage scanner service and `DeepSearchConsumer` base
  class. Migrated from `deepsearch-crawler` repo; poetry → uv/hatchling.
- **`services/storage`** — NGSearch HTTP storage service (indexes and serves asset metadata
  via Elasticsearch/OpenSearch). Extracted from `ngsearch/services/storage/`.
- **`services/crawlers`** — NGSearch tag and indexing crawlers (consume Redis stream and
  index assets). Extracted from `ngsearch/services/crawlers/`.
- **`services/monitor`** — DeepSearch monitor worker, cache API, plugins pipeline, and
  info endpoint. Migrated from `deepsearch/services/{monitor,cache,info_endpoint}/` and
  `deepsearch/plugins/`. Packaged as a single wheel (`monitor`, `cache`, `plugins`,
  `info_endpoint` namespaces) because the four components have circular imports.
- **`services/deepsearch_api`** — User-facing search API: V2/V3 FastAPI endpoints, hybrid
  vector+text search, VLM validation. Migrated from `deepsearch-api`.
- **`services/asset-graph`** — Neo4j-backed USD scene graph service: spatial queries,
  dependency tracking, REST API, and graph builder Kit worker. Migrated from
  `asset-graph-service`; poetry → uv/hatchling.
- **`services/siglip2-triton`** — Triton Inference Server deployment for SigLIP2 ONNX
  models: model repository and ONNX export scripts. Copied from `siglip2-onnx-triton-server/`.
- **`services/rendering-job`** (source only) — GPU-accelerated USD/MDL asset renderer:
  FastAPI service managing Omniverse Kit subprocess workers. Migrated from
  `deepsearch-rendering-job`; poetry → uv/hatchling. Not yet a workspace member:
  requires `websockets>=12.0` which conflicts with `deepsearch-utils`' `websockets~=10.4`
  pin (`ws_server.py` uses the `max_queue` parameter removed in v11).

#### Infrastructure
- **`infra/compose/`** — Consolidated docker-compose files from across all source repos:
  `redis.yml`, `opensearch.yml`, `storage-apis.yml`, `deepsearch-crawler.yml`,
  `siglip2-triton.yml`, `siglip2-triton-cpu.yml`.

#### CI
- **`ci/search-utils/gitlab-ci.yml`** — CI pipeline for `packages/search-utils`.
- **`ci/deepsearch-crawler/gitlab-ci.yml`** — CI pipeline for `services/deepsearch-crawler`.

#### Documentation
- **`docs/repo-organization-proposal.md`** — Full eight-repo consolidation proposal with
  dependency graph, design decisions, and step-by-step migration plan.
- **`docs/search-utils.md`**, **`docs/ngsearch.md`**, **`docs/deepsearch-crawler.md`**,
  **`docs/deepsearch.md`**, **`docs/deepsearch-api.md`**, **`docs/asset-graph-service.md`** —
  Per-repo architecture summaries.

---

### Changed

- **`packages/search-utils/search_utils/log_utils.py`** — Added `setup_logging_from_yaml()`
  consolidating the YAML-based logging bootstrap that was previously duplicated in
  `ngsearch`, `deepsearch`, `services/storage`, and `services/crawlers`.
- **`services/storage/storage/src/services/ngsearch_storage_service.py`** — Updated import
  from `utils.logging_utils` → `search_utils.log_utils.setup_logging_from_yaml`.
- **`services/crawlers/crawlers/src/base.py`** — Updated import from `utils.logging_utils`
  → `search_utils.log_utils.setup_logging_from_yaml`.

---

### Removed

- **`services/storage/utils/`** — Temporary `logging_utils` shim (superseded by
  `search_utils.log_utils.setup_logging_from_yaml`).
- **`services/crawlers/utils/`** — Temporary `logging_utils` shim (superseded by
  `search_utils.log_utils.setup_logging_from_yaml`).

---

### Known issues / follow-up work

- `packages/siglip2-triton-client` workspace activation: cut a `>=0.3.0` git tag in this
  repo so it satisfies `vision-endpoint[siglip2]`'s transitive requirement without
  conflicting with the deepsearch-group index version.
- `services/rendering-job` workspace activation: update
  `deepsearch_utils/farm/ws_server.py` to the websockets v11+ API (replace
  `websockets.serve(..., max_queue=...)` with the new `serve()` signature), then relax
  `deepsearch-utils`' `websockets~=10.4` constraint to allow `>=10.4`.
- `services/monitor/monitor/src/logging_utils.py` still contains a local copy of
  `setup_logging`; update to import `setup_logging_from_yaml` from `search_utils.log_utils`.
- CI pipelines for `ngsearch-backend`, `deepsearch-utils`, `services/monitor`,
  `services/deepsearch_api`, and `services/asset-graph` not yet wired into the root
  `.gitlab-ci.yml`.
