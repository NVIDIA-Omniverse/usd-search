## [1.4.0]

### Added

- **`/usd-property-catalog` skill** — discovers which USD properties a corpus carries via `GET /search/stats/usd_properties` and writes a local `usd_property_catalog.yaml` + `search_fields.generated.yaml` (guide: [`docs/usd-property-catalog.md`](docs/usd-property-catalog.md)).
  - A "gap audit" mode reports which target properties are present/absent and pulls sample assets for parsing validation.
- LLM query parsing can ground the generic `usd_property` filter on the real keys/values in a corpus via `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH` (Helm `ngsearch.microservices.search_rest_api.llm_parsing.property_catalog`).
- GIF thumbnail sampling gains a `gif_sampling_mode` option: `fixed` (every Nth frame, default) or `uniform` (spread `gif_max_frames` frames evenly across the GIF).
- **Asset download** — `GET /download/asset` bundles any indexed asset plus its transitive dependencies into a self-contained ZIP with paths preserved (see [`docs/asset-download.md`](docs/asset-download.md)).
  - Pre-flight size preview (`?manifest_only=true`) returns file count and total size before the user commits to a download.
  - `manifest.json` in every archive lists each included file, sizes, and anything skipped (no access, deleted, download error).
  - Access-aware: only bundles files the requester can access; skipped files are reported in the manifest and in the `X-Download-Summary` response header.
  - Configurable via `DOWNLOAD_*` env vars and the Helm chart (`ngsearch.microservices.search_rest_api.download.*`): concurrency, size cap, dependency limit, temp directory.
- **Explorer WebUI refactor** — major overhaul of the sample Explorer front-end (redesigned UX, advanced-filter rail, client-side caching, stability and performance fixes).
  - Asset download manager: per-card and modal downloads with a sequential queue, live progress, cancel, and pre-flight bundle size.
  - Optional LLM query parsing: when enabled, free-text queries are parsed into removable filter chips via `POST /llm_parse/query`, reporting any clauses it couldn't apply (`dropped_filters`, `unmapped_constraints`); when it is disabled or unavailable the UI falls back to plain hybrid search.
  - Catalog-backed SimReady / physics filters (rigid body, collider, mass, density, dimension, object class) from `GET /llm_parse/fields` (see [`docs/search-filters.md`](docs/search-filters.md)), discoverable via the "Add filter" picker and natural language, applied as real server-side `/search_hybrid` filters.
  - Zoomable asset preview and dependency graph (wheel-zoom + drag-pan), in a wider asset modal with a larger preview pane.
- **Discoverable filter dropdown** — the Explorer "Add filter" picker lists the deployment's supported filters from `GET /llm_parse/fields`, configurable via [`search_fields.yaml`](services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml) (see [`docs/search-filters.md`](docs/search-filters.md)).
- `packages/llm-client` — one OpenAI-compatible client shared by every AI role, configured via `USDSEARCH_LLM_API_KEY` / `USDSEARCH_LLM_BASE_URL`.
- Fully configurable AI surface — per-role models, externalized prompts, metadata schema, and LLM-parsing field mappings (see [`docs/models-and-config.md`](docs/models-and-config.md)).
- LLM parsing can use its own endpoint (`llm_parsing.provider.*`), else shares the connection.
- LLM-parsing output-token cap is configurable via Helm (`llm_parsing.max_tokens`, env `USDSEARCH_LLM_PARSING_MAX_TOKENS`), default 1536.
- Helm: embedding pod RuntimeClass is configurable via `deepsearch.microservices.embedding.runtimeClassName` (empty by default, field left unset).
- graph-builder keeps a persistent on-disk Kit asset cache (`CACHE_LOCATION`, default `/cache`) so downloaded USD/textures are reused across requests.
- `docker/Dockerfile.kit` takes `USER_ID`/`GROUP_ID`/`USER_NAME` build args, wired through `scripts/build_kit_workflows_custom_user.sh` and the `ci/asset-graph-builder` compose (`KIT_USER_ID`/`KIT_GROUP_ID`/`KIT_USER_NAME`).
- asset_graph_generation emits OpenTelemetry spans for `preprocess` and `process_valid_items` (with per-item child spans for the Kit/store calls).
- `THIRD_PARTY_NOTICE.md` now enumerates the runtime image's apt-get OS-package closure.
- Storage API backend (external Omniverse/Sevan gRPC) selectable in the docker-compose quickstart via `STORAGE_BACKEND_TYPE=storage_api` + `STORAGE_API_*`.
- `deploy-usdsearch` skill: new "Storage API" storage-backend option, plus a Sevan-based `ci/quickstart/configs/storage-api.env`.
- GPU render-from-USD works with the Storage API backend — creds are forwarded per request (`storage_api_url` body + `X-Token-Auth` header).

### Changed

- Explorer: migrated the WebUI from Chakra UI to NVIDIA Kaizen Foundations (dark theme, NVIDIA-green brand), dropping the Chakra UI, Emotion, and choc-ui dependencies and refreshing the results view, search bar, and filter rail.
- README: replaced the landing-page hero with an Explorer feature showcase and moved the beta features to [`docs/beta.md`](docs/beta.md).
- Helm: secret-hook annotations (`helm.sh/hook`, `helm.sh/hook-weight`) moved into `global.secrets.annotations` instead of being hardcoded per secret.
- Consolidated all LLM/VLM access — replaced the 9-provider `vision-endpoint` package with `llm-client` (one shared OpenAI-compatible connection + per-role models).
- SigLIP2 embedding client moved to `siglip2-triton-client`.
- `usdsearch` image: runtime base moved from distroless Python 3.13 to `nvcr.io/nvidia/base/ubuntu:noble-20260217` (apt-installs only `python3.12` + `ca-certificates`); builder/test-runner on `python:3.12-bookworm`. The image now runs on Python 3.12.
- API: `QueryRelevanceValidationResult` includes the active model identifier so the client cache invalidates on backend model swaps.
- graph-builder applies the shared `logging.yml` (honoring `LOGGING_CONFIG`) across the FastAPI service and the Kit `usd_deps_kit.py` worker.
- graph-builder tracks in-flight Kit subprocesses in a per-request registry so concurrent requests (`N_PARALLEL_PROCESSES > 1`) no longer clobber each other's process state.
- graph-builder returns the graph via an orjson `Response` (skipping FastAPI's `jsonable_encoder`) and only builds the debug graph dump when debug logging is enabled.
- Helm: the graph-builder (`kit-worker`) sidecar sets `N_PARALLEL_PROCESSES` from the plugin's `n_concurrent_queue_workers` (else `plugin_worker.settings.n_concurrent_queue_workers`).
- GIF thumbnails are now sampled by frame count (`gif_frame_sample_frequency`, default every frame; `gif_max_frames`, default 512) instead of a fixed time offset (`gif_offset_ms`).
- Replace the monitor worker's global data-load lock with a per-plugin `data_load_concurrency` setting (default unlimited; `image_to_embedding` defaults to 1) to unblock parallel thumbnail fetches.
- Parallelize S3 thumbnail GETs and drop the redundant per-candidate LIST in `S3StorageClient.load_thumbnail`; add a HEAD-based `head_item` used for per-asset existence probes in the monitor worker.
- Speed up template-based thumbnail loading: exact-key templates skip the LIST entirely, and wildcard templates narrow the S3 listing to the regex's literal prefix instead of scanning the whole `.thumbs` folder.
- Search: vector-leg `inner_hits` no longer return the 1536-d embedding vector unless `return_embeddings` is set, cutting `return_images` response size.
- Search: `_source` pulls only the needed `siglip2-embedding` sub-field — `.embedding` for similarity/predictions, `.image` for `return_images` — instead of the whole nested field.
- Fix `return_images` on `description`-only queries: fully-qualify the vector-leg `inner_hits` `_source` fields (`siglip2-embedding.image`, …).
- `storage-api` protos are no longer vendored; the generator fetches them from `NVIDIA-Omniverse/ovstorage` at a configurable git ref (default `v0.1.0`).
- indexing / tag-crawler use an async Redis client for the per-item dedup cache so cache I/O no longer blocks the event loop.
- monitor-crawler / indexing / tag-crawler recompute stream `statistics()` only on the Prometheus (5s) and log (60s) intervals instead of per item.
- Expose `PROCESSING_BATCH_SIZE` as a Helm value for the monitor-crawler, indexing, and tag-crawler deployments.
- Gateway: added `/download/...` route (e.g. `/download/asset`) with a 300 s read timeout.
- Minimum Python raised to 3.11, capped below 3.14 (3.14+ breaks the Nucleus connection).
- Updated Python packages (numpy, langchain, websockets, aiohttp) to address vulnerabilities.
- Kit kernel bumped to 110.1.1.

### Fixed

- Gateway: widen `/vlm_validate/` proxy scope so the validator's full route surface is reachable (revives !32).
- S3 storage client `_key_from_uri` now accepts virtual-hosted HTTPS URLs in addition to `s3://` scheme, fixing ACL checks and downloads for assets whose `base_key` is an HTTPS URL.
- info-endpoint: `/info/backend/storage` no longer 500s on the Storage API backend.
- Rendering client now mints an OpenID bearer token for Storage API backends, fixing `load_error` ("File not found") with OpenID configs (e.g. Sevan).
- LLM parse: a value-less `key=` `usd_property` guess is dropped so the query degrades to semantic search instead of hard-filtering to nothing (catalog now requires `key=value`).
- Search: silence the `PydanticSerializationUnexpectedValue` warning on `SearchResult.source` via a `field_serializer` (the field is a dict at runtime).
- AGS: non-positive spatial `radius` now returns 422, not an empty 200.
- API: trailing-slash paths (e.g. `/search/`) now 404 instead of redirecting and leaking the internal route prefix.
- Explorer: eliminated result-list and thumbnail flashing (asset-detail open/close, modal backdrop/Escape dismiss) and populated the list view's "modified" column.
- Explorer: fixed the overlapping source/sign-in control, made auth status a verified per-source check, and stopped result flashing/twitching during VLM validation.

### Security

- Removed the unused TorchServe `model-serving-config` ConfigMap from the deepsearch chart (embedding serving runs on Triton; the template was dead code binding a management API to `0.0.0.0`).
- graph-builder `/construct_graph/` now caps `timeout_seconds` so one request cannot hold a Kit-processing slot indefinitely.
- docker-compose quickstart credentials (admin key, Neo4j password, MinIO root) are now env-overridable and flagged "local dev only / change before non-local use".
- Redis/file cache and farm-result deserialization now route through an import-allowlist unpickler, blocking pickle-based RCE from cached or queued payloads.
- Farm-result WebSocket frames are capped at a finite size (default 1 GiB, `FARM_CLIENT_WS_MAX_SIZE` / chart `rendering_settings.ws_max_size`) and decompressed payloads are size-bounded, closing a zlib-bomb OOM vector.
- Cached numpy arrays now load with `allow_pickle=False`.
- `/download/asset` strips control characters from request-derived values (asset URL, error text) before logging them, preventing log injection (CWE-117).
- API-gateway CORS now honors the configured `allowedOrigins` on every endpoint; previously several (`/search_hybrid`, `/images`, `/llm_parse/`, `/download`, and others) hardcoded a wildcard origin, bypassing the operator's allowlist (USDS-019, CWE-346).


## [1.3.2] - 2026-05-28

### Added

- Initial open-source release of USD Search API, including Claude Code
  skills (`.claude/skills/`) and Codex skills (`.codex/skills/`) for
  search, scene inspection, asset inspection, deployment, and quickstart.

### Notes

- For previous releases, see the NGC catalog:
  https://catalog.ngc.nvidia.com/orgs/nvidia/teams/usdsearch/collections/usdsearch
