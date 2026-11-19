## 1.5.1

### Added

- Contour `HTTPProxy` exposes the API gateway as an alternative to `kind: Ingress`: set `httpProxy.enabled=true` with an `httpProxy.fqdn`, and configure TLS (optionally cert-manager issued), CORS, edge authorization and route timeouts from the same section.
- `STORAGE_API_TOP_LEVEL_ADDRESSES_TTL` (Helm `global.storage_api.top_level_addresses_ttl`; default `0` = off) re-reads the Storage API's top-level addresses periodically, so new buckets / datasets are indexed without a restart.
- Helm `global.omniverse_discovery.enabled` registers the API gateway's REST APIs with an Omniverse Discovery Service ([docs](helm/usdsearch/README.md)).
- Helm `global.storage_api.full_listing_enabled: false` (`STORAGE_API_FULL_LISTING_ENABLED`) stops the Storage API backend from listing its whole contents, so indexing follows notifications only.
- `USDSEARCH_VISION_VALIDATION_IMAGE_FORMAT=jpeg` (Helm `validation.image_format`; default `png`) sends validation images as JPEG quality 90: 55-85 % less image-encoding CPU per verdict on 1024-px thumbnails at 448 px. Re-judges cached verdicts once ([docs](docs/vlm-validation.md#server-configuration)).
- `filter_by_properties_version` filters on version-valued USD properties by version range (e.g. `simready_metadata_validation__profile_version>=2.0.0`), with no reindex needed; Explorer shows each condition as a filter chip ([docs](docs/search-filters.md#version-ranges)).
- VLM metadata can use caller-supplied labelled views (`view_labels`; the built-in thumbnail path doesn't set them) and a file-name hint (`asset_hint`; `VLM_ASSET_HINT=true` derives it from the path; off by default). Claude models run with `json_mode`.
- `USDSEARCH_VISION_VALIDATION_IMAGE_CACHE_DIR` (Helm `validation.image_cache.*`; on by default in `/var/tmp/usdsearch-validation-images`, empty = off) keeps each asset view prepared once instead of per check, byte-identical and shared by the API processes, with a size cap, a free-disk floor, an optional memory LRU, a warm-up (`python -m deepsearch_api.validation.warm_image_cache`) and gauges of how full it is ([docs](docs/vlm-validation.md#server-configuration)).

### Deprecated

- The `usd-search-client` Python package is deprecated and unsupported; it fails on 1.5 responses. Generate a client from the OpenAPI spec instead ([docs](docs/api-clients.md)).

### Fixed

- Helm `httpProxy.path` other than `/` now works: the HTTPProxy strips the prefix before forwarding to the API gateway, which returned 404 for every prefixed route.
- `GET /download/asset` now gives a reason for every file it could not fetch ([docs](docs/asset-download.md#manifestjson)).
- `GET /download/asset` bundles every `<UDIM>` texture tile, also for asset graphs built earlier, and no longer reports `assetInfo` labels as missing once the graph is rebuilt ([docs](docs/asset-download.md#udim-textures-and-assetinfo-labels)).
- Storage API downloads served through a presigned URL no longer fail with `LineTooLong` on large binary files (e.g. USDC meshes), and an error response is no longer saved as the file.
- Dump restores no longer turn on k-NN derived source, which could mix up vectors between assets; the services now warn about indexes that have it on.
- The dump loader now fails when an index cannot be recreated or ends up with fewer documents than its dump; it reported success when bulk writes failed or documents were rejected.
- The asset-graph builder and renderers now evict least-recently-used cache files, so pods are no longer evicted at the cache `sizeLimit` (Helm `kit_worker.cache.max_size`, `usd_cache.max_size_bytes`).
- Render workers no longer leave zombie processes behind.
- The asset graph service no longer creates a Neo4j index per date-keyed prim property name (e.g. SimReady validation history), which made graph stores slow and grew to ~15k indexes. These properties stay filterable; `PROPERTY_INDEX_EXCLUDE_REGEX` (Helm `asset-graph-service.env`) sets which names are skipped.
- The asset graph service no longer creates a Neo4j TEXT index for every prim property; none of its filters used them, and keeping them current made each graph store take ~25 s on NFS-backed Neo4j. On startup it drops them, keeping only the names listed in `PROPERTY_TEXT_INDEX_FIELDS` (Helm `asset-graph-service.graphdb.textIndexProperties`, default empty).
- The asset graph links every prim to its source asset and every root prim to its scene; only the first prim per source asset or scene was linked. Scenes stored before this get the links when re-stored.
- `GET /download/asset` bundles the MDL modules a packed module imports, and textures a `.mdl` references by an explicitly relative path; both were dropped, so prims bound to those materials rendered untextured. Assets indexed before this need their asset graph rebuilt ([docs](docs/asset-download.md#rebuilding-the-asset-graph)).
- Helm no longer discards boolean values: the S3 and Azure `allow_system_writes` and `allow_non_system_writes` flags take effect when set to `false`, and a cleared `enable_access_verification` renders a valid env value.
- `filter_by_properties` and `properties_filter` match the same whether or not a comma is followed by a space ([docs](docs/search-filters.md)).
- The quickstart smoke test no longer passes when the scene-graph prim query returns nothing.
- A graph write the database rejects now fails the asset with the database's error code, instead of being recorded as stored successfully.
- An asset URL as an image query (Explorer *Find similar*) works for indexed 2D images (PNG, JPEG, …) and any asset without a `.thumbs` thumbnail, using its indexed image; one with no image now returns 404 instead of 500 ([docs](docs/search-filters.md#more-like-this--image-similarity)).
- A blank `scoring_config.hybrid_text.fields[].field` is now rejected as invalid input instead of failing the search with a 500.
- Deep pagination of a deduplicated query no longer fails with `Result window is too large` near the end of the walk: the access-filter over-fetch now sizes itself to the room left in `index.max_result_window`, so every cursor the previous page advertises can be followed.
- Helm `global.search_backend_config.max_chunk_size` (`MAX_CHUNK_BYTES`) now caps every bulk write to the search backend; most write paths ignored it and used the client default of 100 MiB.
- `scripts/build-openapi-docs.sh` and `infra/compose/dev-stack.yml` work in a clean checkout of the public repository: the merger's build context (`tools/openapi-merge/`) and the `deepsearch-api` Compose definition they reference were both missing.
- `GET /download/asset` bundles dependencies the asset graph stored percent-encoded on deployments that run with `ENABLE_ACCESS_VERIFICATION` off; only the access-verified path looked for the other spelling, so the size preview reported them as errors and the archive left them out.
- Switching index in Explorer no longer scores the first search against the previous index's vector field, which matched nothing on the new one.
- Bounding-box size filters (`min_bbox_x/y/z`, `max_bbox_x/y/z`) match in meters again: indexing scaled the default prim's bounding box by the prim's transform, which its world bounds already include, and never applied the stage's meters-per-unit. Assets indexed before this need reindexing ([docs](docs/search-filters.md)).
- Explorer ships the documented "Only VLM-validated" toggle (Show filters -> Search settings), which hides the "Lower relevance" results; it was documented but never rendered, so the setting could not be reached.
- Changing the fusion window in Explorer's Advanced scoring panel restarts the search, as the control says it does; it used to leave the results and the cursor from the previous window on screen.
- The Helm chart README says where to get the chart (NGC catalog listing, `helm repo add`, and how `helm.ngc.nvidia.com` relates to `nvcr.io`, replacing an onboarding link that pointed at unrelated docs) and how to run against an external OpenSearch instance, including Amazon OpenSearch Service, with full `global.search_backend_config.*` key paths and the k-NN, index privilege and basic-auth-only requirements ([docs](helm/usdsearch/README.md#external-opensearch-instance)).
- Changing only the page size of a hybrid search no longer changes how many results the query can reach: with access verification on, the over-fetch used to widen the fusion window, so the same query returned 222 results at `limit=37` and 200 at `limit=25`.
- Public documentation no longer points at files the mirror does not ship (the benchmark harness, the Explorer sources and build script, the quickstart test harness and the SimReady field catalog), which read as broken links outside NVIDIA; that material moved to an internal development guide. The rendering-job README builds and tests with uv against `docker/Dockerfile.rendering-job`, replacing Poetry commands and a `build.sh` that no longer exists.

### Security

- Container images updated to clear scanner warnings: Ubuntu base `noble-20261024.1`, Triton `26.10-py3` (CUDA 13.4; drivers older than R615 run it through CUDA forward compatibility), patched OS packages (brotli, apt) and patched Python dependencies (Pillow 13, filelock 4, aiohttp, authlib, OpenTelemetry, uv, pip).

## 1.5.0

### Changed

- Hybrid search finds the asset a multi-word query names ("allegro hand", "malm chest"): a name vote (`ScoringConfig.name_match`, on, weight 1.0, `min_words` 2, a one-word query when its word is rare: `rare_word_hits` 1; Helm `hybrid_search.scoring_config.name_match`) gives hits whose name or path holds every query word, as whole words, one more RRF vote, read from the hits the legs returned (no extra query).
- Metadata-generation default VLM is now `azure/openai/gpt-5.6-sol` (was `gcp/google/gemini-3.1-pro-preview`) — chosen by the 2026-08 bake-off; see `docs/models-and-config.md`.
- Metadata schema rebuilt for retrieval only: 13 fields (`use_cases`, `description`, and the quality flags removed), nullable vocabularies for `style`/`scale`/`state`, enforced item vocabulary for `physical_attributes` (the corpus-derived `category` list is deployment-opt-in — commented out in the generic release, enabled per deployment via helm values); rationale in `docs/models-and-config.md`.
- VLM image inputs are lossless PNG at up to 512px (was 256px JPEG-q75), bounded by view count and an 8 MiB encoded-image budget (`VLM_IMAGE_MAX_PX`, `VLM_MAX_IMAGES`, `VLM_MAX_REQUEST_BYTES`). Setting `VLM_METADATA_REVISION` (empty by default, so upgrading reprocesses nothing) opts a deployment into folding those settings plus the revision into the metadata cache identity; bump it to regenerate unchanged assets after a model, prompt or schema change.
- VLM schema-validation failures now trigger one informed re-ask instead of identical retries.
- VLM validation: `similarity_score` is a full-resolution float 0-100 (was an integer; `rerank` sorts on it); the `logprob` method sends only the short judge question (system prompt opt-in via `logprob.domain_context`) ([docs](docs/vlm-validation.md#validation-methods-generative-log-prob)).
- VLM validation hardening: per-verdict deadline includes queue wait; the `logprob` boot probe reports an unreadable answer; new `validation.max_tries` (`USDSEARCH_VISION_VALIDATION_MAX_TRIES`, default 1; set 2 for self-hosted vLLM).
- LLM query parsing no longer permanently disables itself after a boot-time reachability failure (e.g. a scaled-to-zero endpoint); readiness is now a TTL-cached probe (`USDSEARCH_LLM_PARSING_PROBE_TTL_SECONDS`, default 120s) that self-heals without a restart.
- VLM validation encodes a query image once for all the assets it is judged against (a page of results), not once per asset: ~40-55 ms of CPU per asset for a 1920-px upload.

### Added

- VLM validation (`logprob`): an image + text query with one asset view asks whether the candidate matches both, where the caption clause passed unrelated assets. On by default; `USDSEARCH_VISION_VALIDATION_LOGPROB_IMAGE_TEXT_QUERY=false` (Helm `validation.logprob.image_text_query`) keeps the caption clause. Cached `logprob` verdicts are recomputed once after upgrading ([docs](docs/vlm-validation.md)).
- VLM validation: `POST /vlm_validate/search_result_batch` judges a page of results in one request, streaming a verdict per result by default ([docs](docs/vlm-validation.md)).
- VLM validation (`logprob` method): optional asset facts for text queries — `USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_FACTS` lists the request fields (`path`, `vlm_metadata_caption`) the judge reads, with `..._LOGPROB_ASSET_PATH_ROOTS` for path content roots, also in the Helm chart (`validation.logprob.asset_*`) ([docs](docs/vlm-validation.md#validation-methods-generative-log-prob)).
- Storage API auto-discovers multiple backends via `ListTopLevelAddresses`, making `STORAGE_API_BASE_URI` optional.
- `STORAGE_API_ALLOWED_TOP_LEVEL_ADDRESSES` (Helm `global.storage_api.allowed_top_level_addresses`) restricts a Storage API deployment's discovered backends to a named subset instead of using all of them.
- `POST /vlm_validate/search_result` accepts raw base64 `images` to validate directly, skipping the index thumbnail fetch (mutually exclusive with `asset_url`/`image_key`/`image_keys`).
- VLM validation now filters out explicit non-matches by default (`USDSEARCH_VISION_VALIDATION_MODE=filter`; `rerank` reorders instead of dropping, `annotate` restores the previous attach-only behavior) and uses 1 view per verdict (see [docs/vlm-validation.md](docs/vlm-validation.md)).
- VLM validation adds a faster `logprob` method (`USDSEARCH_VISION_VALIDATION_METHOD=logprob`) that reads relevance from a Yes/No judge's first-token log-probs instead of generating a verdict ([docs/vlm-validation.md](docs/vlm-validation.md)).
- VLM validation failures now return a structured, typed 503 (`{error_type, message, retryable}`) so clients show the real reason and distinguish a permanent misconfiguration from a transient outage.
- VLM validation verdicts are cached persistently in Redis (keyed by full model config + query + asset image, shared across replicas, bounded by a configurable LRU cap), behind the existing in-process cache.
- `GET /images` now reuses a pooled OpenSearch client, caches the `asset_url → image_id` resolution in Redis, and sets browser cache headers, cutting repeat OpenSearch load.
- Restored the `queries` metadata field (user-phrased search strings, BM25-indexed; takes effect as assets are reprocessed).
- API Monitoring Grafana dashboard (request rate + latency histograms per endpoint, validation and image-cache hit ratios), with new `image_resolution_cache_events_total` and `vlm_validation_cache_entries` metrics.
- Explorer: per-index filter rail (generated from the field catalog + each index's live property stats) and runtime index switching via `EXPLORER_SERVER_MAPPING` (no rebuild).
- `extra_body` passthrough (env + Helm + compose) for the validation, metadata, and LLM-parsing roles — merges arbitrary OpenAI request-body fields into each call (e.g. `{"chat_template_kwargs":{"enable_thinking":false}}` to stop a self-hosted Qwen returning empty verdicts).
- The Storage API bearer token can be read from a file (`STORAGE_API_TOKEN_FILE`) and is re-read on `STORAGE_API_TOKEN_REFRESH_INTERVAL` (Helm `global.storage_api.authentication.token_refresh_interval`, same cadence as the OpenID flow), so an externally-rotated token is picked up without a restart.
- Pagination: `/search_hybrid` and `/search` take an `offset` or an opaque `cursor` and report how far a query can be paged, and the Explorer grows the list with a "Load more" button that explains what caps the results and how to raise it.
- Optional Storage API token refresher (`global.storage_api.authentication.token_refresher`): a lightweight Deployment runs a user-supplied token-vending sidecar and publishes its token into the shared credentials Secret that every service reads, with a `pre-install`/`pre-upgrade` hook that seeds the Secret before any pod starts (requires Kubernetes ≥ 1.28).
- `USDSEARCH_LLM_DEFAULT_HEADERS` (JSON object) adds custom HTTP headers to every LLM/VLM request, e.g. `{"X-HF-Bill-To":"my-org"}` for Hugging Face org billing.
- `USDSEARCH_VISION_VALIDATION_IMAGE_MAX_PX` (default off) shrinks images before VLM validation; 448 cuts prompt tokens per verdict ~4x ([docs](docs/vlm-validation.md#server-configuration)).
- The asset-graph `kit-worker` sidecar is now configurable from the chart under `plugins.asset_graph_generation.kit_worker` (resources, memory watchdog, build timeout, caches).
- Asset-graph build failures carry a per-asset reason code, reported per plugin by the new `omnideepsearch_worker_item_status_total` metric ([docs/asset-graph-failures.md](docs/asset-graph-failures.md)).
- Asset-graph builds report per-phase timings, including Kit startup cost and the phase a killed build died in, as span attributes and as the new `omnideepsearch_worker_phase_duration_seconds` metric ([docs/asset-graph-failures.md](docs/asset-graph-failures.md)).
- Optional alerting rules for the indexing streams (`deployPrometheusRules`): items dropped after exhausting their retries, and a stream whose oldest unacknowledged entry blocks trimming.
- Optional public asset URLs: a deployment can publish rewritten URLs (e.g. `https://` instead of `s3://`) while the index, asset graph and storage access keep using the original ones; requests accept either form, including percent-encoded paths (`global.url_mapping`, off by default — see [docs/configuration-map.md](docs/configuration-map.md#public-asset-urls)).
- `GET /search/stats/usd_properties` accepts the filter parameters `/search` takes (path, name, extension, dates, size, user, tags, USD properties, bbox, `search_in_scene`), so the property inventory can be scoped to part of the corpus instead of all of it ([docs/search-filters.md](docs/search-filters.md)).
- Asset downloads emit a telemetry event recording the asset, the user, and how long it took ([docs/asset-download.md](docs/asset-download.md#telemetry)).
- The `/search` skill now always shows the result thumbnails — inline Markdown images plus a `contact-sheet.html` grid — unless the user asks for text-only output.
- Asset-graph builds can now ingest sidecar/package metadata files shipped next to a USD asset (e.g. SimReady conformance/BOM files) via a declarative YAML catalog (`SIDECAR_METADATA_CONFIG_PATH`, off by default), merged into the same `usd_properties` used by in-file SimReady metadata.

### Changed

- `rendering-job` renders USD and MDL thumbnails with the ovrtx 0.5 RTX renderer instead of an Omniverse Kit subprocess (keeping Kit's grey floor and contact shadows), built from the new `docker/Dockerfile.kit`-free `docker/Dockerfile.rendering-job` (CUDA base, no Kit kernel). The published image name (`usdsearch-kit-workflows`) and the NVCF rendering function are unchanged.
- `asset-graph-builder` builds dependency graphs without Omniverse Kit: a plain-Python worker opens the stage with `usd-core` and the standalone packman `omni_usd_resolver` (ABI-matched to `usd-core`, layered on top — not ovrtx's renamed USD) for `omniverse://`/`s3://`/`http(s)://` resolution. It now ships in the CPU `docker/Dockerfile.usdsearch` image (published `usdsearch-graph-builder`, built with `OMNI_USD_STOCK_URL` to include the resolver stack), alongside the sibling `asset-graph` service, so `docker/Dockerfile.kit` is removed. Migrated to pydantic v2 and joined the `uv` workspace.
- New OpenSearch indexes disable k-NN derived source (`knn.derived_source.enabled: false`, keeping embeddings in `_source`) and set a configurable `refresh_interval` (default 60s, via `OS_REFRESH_INTERVAL` / Helm `search_backend_config.refresh_interval`); both apply to newly created indexes only.
- Telemetry resolves the username from a bearer token on any storage backend, not just Nucleus ([docs/asset-download.md](docs/asset-download.md#telemetry)).
- Default VLM validation model is now `gcp/google/gemini-3.1-flash-lite` (was `gemini-3.5-flash`): higher accuracy at lower latency and cost. Measured on 800 labeled query/asset pairs — accuracy 0.881 vs 0.865, F1 0.878 vs 0.860, ~24% faster per verdict (median 1.82s vs 2.38s). Overridable via `USDSEARCH_VISION_VALIDATION_MODEL` / helm `validation.model`.
- The search REST API reuses a single process-wide OpenSearch client instead of opening and closing a connection pool per request, cutting per-search connection + TLS setup.
- The Helm chart now mounts the Storage API token secret as a file (`STORAGE_API_TOKEN_FILE`) instead of injecting it as the `STORAGE_API_TOKEN` environment variable.
- Explorer: the zero-results state now says when matches existed but were withheld because the account cannot read where they are stored, instead of reporting a plain miss.
- Hybrid (multi-leg) searches fuse a 200-document window by default instead of 100, since that window also bounds how far a client can page; set `PAGINATION_DEFAULT_WINDOW=100` (Helm `pagination.default_window`) to restore the previous per-leg fetch volume.
- The asset-graph kit-worker sidecar takes its log level from the chart's `loggingConfig` like every other component, instead of the `WARN` baked into its image (which hid its own per-build lines).
- `GET /download/asset` stores already-compressed members instead of deflating them (`DOWNLOAD_COMPRESSION=deflate` restores the old behaviour), runs the ZIP pass off the event loop, and streams the archive from a dedicated disk volume, capped per pod by `DOWNLOAD_MAX_CONCURRENT` ([docs/asset-download.md](docs/asset-download.md)).
- Asset-download telemetry and traces break the request into phases and span each bundle member, so a slow download says which part was slow ([docs/asset-download.md](docs/asset-download.md#telemetry)).
- Explorer: asset downloads show a real percentage, rate and time remaining, and no longer hold the whole bundle in browser memory.
- `GET /download/asset` reports a specific reason per skipped file instead of one combined label ([docs/asset-download.md](docs/asset-download.md)).
- `usdsearch.admin.tools migrate_url_spellings` repairs asset-graph nodes already stored under a percent-encoded URL and can re-index them, run from the asset-graph-service pod ([services/asset-graph/README.md](services/asset-graph/README.md#admin-tools)).
- Asset Graph Service: `limit=0` on the four `dependency_graph` endpoints returns every entry, for callers that need a whole dependency tree rather than a page of it. The default stays 1000.

### Fixed

- `GET /download/asset` now bundles every dependency when `DOWNLOAD_MAX_DEPENDENCIES` is unlimited (the default): the request omitted the limit, so the asset graph applied its own 1000-entry default and scenes referencing more files were silently bundled incomplete. A bundle that fills a configured cap now reports `dependencies_truncated` ([docs/asset-download.md](docs/asset-download.md)).
- Local-fs mode: `/download/asset` bundles a scene's dependencies (it returned only the root file), and the dependency-graph endpoints, `search_in_scene` and in-scene prims no longer come back empty.
- Helm API gateway with CORS enabled and several `allowedOrigins` sent them all in one `Access-Control-Allow-Origin` header, which browsers reject; it now echoes back the request's origin when it is allowlisted.
- Local-fs `fs-watcher` now ingests files whose names contain spaces or other URL-special characters (was rejected with HTTP 400 `Asset missing`); `/process/asset` also accepts a percent-encoded URL when only its decoded spelling exists.
- `rendering-job` accepts asset URLs on custom S3 endpoints (s3proxy, MinIO): a non-AWS `http(s)://` URL previously failed with HTTP 500 `Invalid URL` before rendering, so thumbnail and embedding generation never ran for those assets.
- Quickstart compose: the storage overlays (`local-fs`, `local-s3`, `s3proxy-auth`) no longer define the GPU-only services, so their documented commands work without the `gpu-plugins` overlay instead of failing validation; the GPU overrides moved to companion `docker-compose.*.gpu.yml` files.
- Quickstart compose: `info-endpoint` now loads the same plugin config as `monitor-crawler`, so `/process/asset` and `/info/plugins` no longer ignore `asset_graph_generation` and the VLM metadata plugins.
- Cursor pages 2+ of `/search_hybrid` served from the RRF ranking cache carry each hit's top matched view (`metadata.explanations[0].matched_vectors[0].image`) like page 1; they had none, so clients judging a hit past the first page fell back to its asset URL.
- The storage cron's image-cache cleanup no longer deletes thumbnails of assets indexed within the last `refresh_interval` (default 60s), which made `GET /images` return 404 for them.
- A k8s rendering job that times out, runs out of memory or crashes now reports the failure for its assets instead of leaving the worker waiting up to an hour for results that never arrive.
- The search API shares one asset-graph client instead of building and leaking one per request; `/images?image_key=` no longer resolves the search backend.
- The `deepsearch-crawler` Helm subchart now restarts its pod on `loggingConfig` changes (missing checksum annotation on that ConfigMap, unlike its env/extra-config ones).
- Percent-encoded asset-graph URLs no longer hide dependencies from `GET /download/asset`; the builder now records the storage key ([docs/asset-download.md](docs/asset-download.md)).
- An unreadable dependency no longer fails a whole `GET /download/asset` with a 500 on S3 backends.
- The Helm chart rendered large `DOWNLOAD_MAX_BUNDLE_BYTES` values in scientific notation, which the service rejected at startup.
- Text queries are now lowercased before SigLIP2 embedding, matching the model's reference preprocessing, so search results no longer depend on how the query was capitalized ([docs/models-and-config.md](docs/models-and-config.md)).
- `POST /llm_parse/query` now publishes `filters[].field` as a plain string instead of an enum of one deployment's filter catalog, so clients generated from the OpenAPI spec (Rust, Go, C#, …) no longer fail to deserialize responses from a deployment with a different catalog; the valid names are discovered at runtime via `GET /llm_parse/fields`.
- Search results are now ordered reproducibly: every query leg sorts on a unique tiebreaker, so equal-scoring documents no longer shuffle between identical requests (which shifted RRF scores, since fusion is rank-based).
- A kit-worker restart mid-batch no longer fails every asset in that batch, only the one in flight.
- A Kit process that dies during rendering startup is now reported as itself instead of a generic exception, and its memory/PID gauges reset instead of holding the dead worker's last reading.
- Asset-graph builder no longer crashes with `KeyError: 'properties'` when a stage's default prim is not traversed (e.g. an `over`, inactive, or abstract prim).
- SimReady custom-layer metadata with non-string values (e.g. bool) no longer breaks USD-property indexing (`'bool' object has no attribute 'encode'`); such values are stringified in the graph and coerced at the AGS plugin.
- USD property values over OpenSearch's 32766-byte keyword-term limit are skipped (with a warning) instead of rejecting the whole asset-graph metadata write.
- Prim property values over Neo4j's index size limit are stored unindexed instead of crashing ingestion, and Neo4j errors return their code/message instead of a bare 500.
- Asset-graph plugin now surfaces the AGS response body (e.g. the failing prim fields on a 422) when a graph write is rejected, instead of only the bare status code.
- Asset-graph builder drops never-traversed prim stubs (e.g. an `over` default prim) before posting, instead of emitting a bare entry that AGS rejects with a 422; such override/payload sublayers now index.
- Asset-graph builder substitutes `±FLT_MAX` sentinels for prims whose bounding box has non-finite coordinates (e.g. unbounded Volumes), instead of emitting `inf`/`NaN` that orjson serializes to `null` and AGS rejects with a 422 on `bbox_max`/`bbox_min`/`bbox_midpoint`.
- Rejected OpenSearch metadata writes now log the offending `_update` payload for diagnosis, and gzip is toggleable via `OS_HTTP_COMPRESS` / Helm `search_backend_config.http_compress` (disabled by default in the chart).
- Query images with an EXIF rotation tag now embed upright instead of sideways (and are shown upright to the VLM validator). The same fix applies at indexing time via the shared SigLIP2 client preprocessor, so corpora containing EXIF-rotated photos should be re-indexed (force re-process) to pick up upright embeddings — cached embeddings are not invalidated automatically.
- The search REST API now has a Helm startup probe, so a slow first start (the remote VLM/LLM capability probes) no longer trips the liveness probe and restarts the pod just as it becomes ready.
- An item that stops being worked on — the worker raised, or died holding it — is now requeued at the back of its Redis stream under a single retry budget (`-1` to retry forever), instead of staying pending and blocking the whole stream (including the results stream) from ever being trimmed, which made Redis memory grow without bound; an item that exhausts its retries is recorded against the asset as `failed_retries_exhausted`, and the new `omnideepsearch_stream_oldest_pending_age_seconds` metric shows when an entry is stuck.
- Asset-graph and rendering Kit workers can now read from a Storage API served without TLS: the endpoint they are handed carries an explicit `http://` scheme when `STORAGE_API_SSL` is false, since Kit's `omni.client` infers TLS from the endpoint string and previously attempted a TLS handshake against every non-loopback host. A scheme in `STORAGE_API_GRPC_ENDPOINT` itself is now rejected at startup instead of silently producing a gRPC channel that never connects.
- AGS no longer reissues `CREATE INDEX` for a USD property it has already indexed on every single asset write, cutting Neo4j schema-lock contention under concurrent writes.
- Updated dependencies to address reported security vulnerabilities.

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
