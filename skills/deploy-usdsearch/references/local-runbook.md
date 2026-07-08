# Local runbook — configuration & launch (L2–L6)

Continue here after the L1 pre-flight checks in `SKILL.md`. These steps
gather the storage / plugin / WebUI choices, build the compose command,
launch the stack, and smoke-test it.

## L2: Storage backend

Ask the user a structured question. Pose the question with this wording verbatim:
"Which storage backend should USD Search index?"

The five options break into two conceptual groups — **"Search a Public
Asset library"** (option A) and **"Search Your Own Library"** (options
B–E). If the runtime has a picker with no section dividers, prefix each
option's label with its group name in square brackets so the hierarchy is
visible in the picker (e.g. `[Search a Public Asset library] Public S3`).
In text-only runtimes, show the groups as plain headings and ask the user
to type A, B, C, D, E, or a free-form answer. In every runtime, keep the
option descriptions verbatim.

- **Header:** "Backend"
- **Options** (use these labels and descriptions verbatim; add the
  bracketed group prefix only for picker runtimes that need it):
  - A) **[Search a Public Asset library] Public S3** — Indexes NVIDIA's
    omniverse-content-production bucket - no credentials needed.
    Great for exploring sample USD assets.
  - B) **[Search Your Own Library] Custom S3 bucket** — Your own S3
    bucket. You'll need bucket name, region, and credentials (if
    relevant).
  - C) **[Search Your Own Library] Local filesystem** — Search Your Own
    Local Files - no credentials needed. Mounts a local directory
    directly via s3proxy. Files appear in real time - no copy step, no
    cloud credentials. A file-watcher auto-triggers reindexing when you
    add / change assets.
  - D) **[Search Your Own Library] Storage API** — Your own Storage API
    service. You'll need GRPC endpoint, Base URI, and credentials (if
    relevant).
  - E) **[Search Your Own Library] Nucleus (to be deprecated)** — NVIDIA
    Omniverse Nucleus server. Requires your own server hostname/IP
    plus `OV_USERNAME` / `OV_PASSWORD`. Note: Nucleus backend will be
    deprecated soon - S3 bucket is favorable.
- Free-form input is always available — the user can type their own
  answer ("Type something else") — so don't add an explicit "Other"
  option manually.

If the user picks **A (Public S3)**, follow up with a **crawler scope**
question. Pose the question with this wording verbatim: "NVIDIA's
public content bucket is very large, so indexing the whole bucket may
take some time. Index a smaller branch of the bucket, or the whole
bucket?"

- **Header:** "Scan path"
- **Options** (use these labels and descriptions verbatim):
  - A) **Index this smaller branch - /Assets/Isaac/6.0/Isaac/** —
    Isaac asset library is well-populated with common warehouse items,
    and fast to index.
  - B) **Index a smaller branch of my choice** — Specify your own
    sub-path under the bucket (e.g. /Projects/..).
  - C) **Index the whole bucket** — Scan everything. Will produce a
    much larger OpenSearch index with warehouse items and robots, and
    will take much longer.
- Free-form input is always available — the user can type their own
  answer — so don't add an explicit "Other" option manually.

The chosen path becomes `DEEPSEARCH_CRAWLER_PATH` in L5.

If the user picks **B (Custom S3)**, follow up asking for:
- Bucket name
- Region — if the user also provides a custom endpoint URL (below),
  try to infer region from the hostname before asking. Common patterns:
  `pdx` → `us-west-2`, `iad` / `iad1` → `us-east-1`,
  `fra` → `eu-central-1`, `sin` → `ap-southeast-1`,
  `syd` → `ap-southeast-2`. If the hostname contains a recognizable
  region code, suggest it as the default rather than presenting a
  generic pick list. If unrecognizable, ask normally.
- Whether credentials are needed. **Never ask for the access key or
  secret itself.** Instead, tell the user to export their credentials
  as environment variables in their shell, and ask them to paste only
  the **names** of those variables — e.g. `DS_STAGING_AWS_ACCESS_KEY_ID`
  and `DS_STAGING_AWS_SECRET_ACCESS_KEY`. At invocation time, map them
  to the prefixed canonical names the stack reads:
  `S3_STORAGE_AWS_ACCESS_KEY_ID="$DS_STAGING_AWS_ACCESS_KEY_ID"
  S3_STORAGE_AWS_SECRET_ACCESS_KEY="$DS_STAGING_AWS_SECRET_ACCESS_KEY"
  docker compose …`. The `S3_STORAGE_` prefix is mandatory — see
  "Indirect credentials" below.
- **Custom endpoint URL** — if the bucket is on an S3-compatible store
  (MinIO, Ceph, s3proxy, Cloudflare R2, etc.) rather than real AWS,
  ask for the endpoint URL (e.g. `https://pdx.s8k.io`). Set
  `S3_STORAGE_AWS_ENDPOINT_URL=<url>`. If on real AWS, omit this var.
- Whether the bucket is **read-only** for this deployment. Pose the
  question with this wording verbatim: "Is this bucket read-only (no
  IAM permission to write objects), or can the workers write back to
  it (e.g. for thumbnails under `.thumbs/`)?"
  - **Header:** "Bucket writes"
  - **Options:**
    - A) **Writable** — Workers will
      generate and upload thumbnails. Sets
      `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` in L5.
    - B) **Read-only** — Workers skip thumbnail uploads to avoid
      AccessDenied. Leaves `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=False`
      (the GPU-plugins overlay default, which matches the public
      quickstart bucket).
  Don't ask this for option A (Public S3) — the public bucket is
  always read-only and the compose default already covers it. Don't
  ask for C (Local filesystem) — s3proxy serves a writable local dir,
  so always set `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` for that
  branch.

**s3proxy auth-proxy (automatic for custom endpoints + GPU):** When a
custom S3 endpoint URL is provided AND GPU plugins are enabled (L3),
**automatically add** `docker-compose.s3proxy-auth.yml` to the compose
chain. Do not ask — this is required. Kit's native client library
cannot authenticate to non-AWS S3 endpoints (hostnames not matching
`*.s3.*.amazonaws.com` fall back to the base HTTP provider which
ignores credentials). The overlay deploys s3proxy as a credential-
translating reverse proxy: it authenticates to the upstream using the
same `S3_STORAGE_AWS_*` host env vars, and exposes the bucket locally
at `http://s3proxy:80` with `S3PROXY_AUTHORIZATION=none`. All services
are redirected through it for consistency. Without this overlay,
rendering-job and graph-builder silently fail to open USD files from
authenticated non-AWS endpoints.

If the user picks **E (Nucleus)**, follow up asking for:
- **OV_SERVER** — the user's own Nucleus server hostname or IP. Do not
  suggest a specific server. Also follow up with a crawler-path
  question (same pattern as S3-public).
- **OV_USERNAME** (env-var **name** only).
- **OV_PASSWORD** (env-var **name** only).

**Important — Nucleus gateway gates APIs with Basic Auth.** When
`STORAGE_BACKEND_TYPE=nucleus`, every gateway-proxied API requires
HTTP Basic Auth using the same `OV_USERNAME:OV_PASSWORD`. The smoke
step (L6) **must** set `BASIC_AUTH=$OV_USERNAME:$OV_PASSWORD`.
Otherwise every endpoint comes back 401 and the smoke reports a full
failure that's nothing to do with the stack actually being broken.

If the user picks **C (Local filesystem)**, follow up asking for the
**local path** to their assets directory. There is no default — the env
var `LOCAL_FS_DATA_DIR` is required by the compose overlay. Accept any
absolute path (e.g. `/path/to/my-assets`).

After receiving the path, verify the directory exists and count files:

```bash
if [ -d "<PATH>" ]; then
  echo "DIR=ok ($(find "<PATH>" -type f | wc -l) files)"
else
  echo "DIR=missing"
fi
```

- **Directory missing:** Warn the user. Suggest `mkdir -p <path>` and
  copying assets in. Block — the compose overlay will fail to start
  if `LOCAL_FS_DATA_DIR` points to a nonexistent path.
- **Directory empty:** Note that the stack will start but nothing will
  be indexed until files are added. The fs-watcher will auto-trigger
  reindexing when new files appear.

Set `LOCAL_FS_DATA_DIR=<path>` and `DEEPSEARCH_CRAWLER_PATH=/` (always
scans the whole bucket).

If the user picks **D (Storage API)**, follow up asking for:
- **gRPC endpoint** (`STORAGE_API_GRPC_ENDPOINT`) — required, in
  `host:port` form. It **must be reachable from inside the containers**.
  Bare `localhost`/`127.0.0.1` will not work (it points at the container
  itself) — reject it and ask again. For a service running on the Docker
  host, use `host.docker.internal:50051` (on Linux this also needs
  `extra_hosts: ["host.docker.internal:host-gateway"]`, which the base
  compose does not set — prefer the host's LAN IP or an external DNS
  `host:port` to avoid that caveat). For an external service, use its
  real hostname/IP and port.
- **Base URI** (`STORAGE_API_BASE_URI`) — optional but recommended. It
  sets the prefix that crawler paths resolve against and the key shown by
  `/info/backend/storage` (unset → the key serializes as `null`).
- **SSL** (`STORAGE_API_SSL`) — optional `true`/`false` (default false).
- **Auth (optional).** Never ask for raw secret values — only env-var
  **names** (same rule as the Custom-S3 / VLM credential pattern). Offer
  two mutually exclusive modes:
  - **Bearer token** — ask for the env-var name holding the token (e.g.
    `MY_STORAGE_TOKEN`) and map it at invocation:
    `STORAGE_API_TOKEN="$MY_STORAGE_TOKEN"`.
  - **OpenID client credentials** — ask for the env-var names of the
    client id and secret, plus the literal token URL / scope / grant
    type, and map to `STORAGE_API_OPENID_CLIENT_ID="$..."`,
    `STORAGE_API_OPENID_CLIENT_SECRET="$..."`,
    `STORAGE_API_OPENID_TOKEN_URL=<url>`, `STORAGE_API_OPENID_SCOPE=<scope>`,
    `STORAGE_API_OPENID_GRANT_TYPE=<grant>`.
- **Crawler path** — follow up with the same crawler-scope question used
  for Public S3 / Nucleus. The chosen value becomes `DEEPSEARCH_CRAWLER_PATH`
  (relative to `STORAGE_API_BASE_URI` when set).

Unlike Nucleus, the Storage API backend does **not** gate the gateway
with HTTP Basic Auth — smoke and curl calls need no `-u` / `BASIC_AUTH`.

## L3: GPU plugins — DO NOT ASK BY DEFAULT

GPU plugins (real SigLIP2 embeddings + USD rendering for thumbnail
generation and rendering-to-embedding) are **enabled by default whenever
a GPU was detected in L1**. Do not present this as a question — assume
"yes" and add `docker-compose.gpu-plugins.yml` to the overlay chain.

Only skip GPU plugins in two cases:

1. **No GPU detected in L1** — automatic. Use CPU-mock embeddings.
2. **The user explicitly asked for CPU-only / no-GPU mode** — e.g.
   "without GPU plugins", "CPU only", "skip rendering". Mention in the
   summary box that GPU plugins were skipped on user request.

## L4: VLM plugins

Ask the user a structured question. Pose the question with this wording verbatim:
"Enhance search quality by enabling VLM metadata generation?

(VLM metadata generation enhances search quality by generating rich,
searchable descriptions and tags from images using a remote VLM
API.)"

- **Header:** "VLM plugins"
- **Options** (use these labels and descriptions verbatim):
  - A) **Yes, enable VLM metadata** — Requires an API key.
  - B) **No, skip VLM** — No API key needed - fastest way to get started.
- Free-form input is always available — the user can type their own
  answer — so don't add an explicit "Other" option manually.

If the user picks A, ask for the **name of the environment variable**
that holds their API key (e.g. `USDSEARCH_LLM_API_KEY`). Never ask for
the raw key. Optionally ask for `USDSEARCH_LLM_BASE_URL` if they want a
non-default endpoint (the stack ships pointed at NVIDIA Inference Hub by
default; any OpenAI-API-compatible server works).

The VLM overlay also enables **LLM query parsing**
on the same shared connection: the API parses free-text queries into
structured filters via `POST /llm_parse/query` (filter discovery via
`GET /llm_parse/fields`). It is on whenever the overlay is included —
`USDSEARCH_LLM_PARSING_ENABLED=true`, model override via
`USDSEARCH_LLM_PARSING_MODEL` (defaults to the application's built-in
model, see `services/deepsearch_api/deepsearch_api/llm_parse/config.py`).
In the base stack (no overlay) it is disabled and `/llm_parse/*`
returns 503 — clients fall back to plain hybrid search, so nothing
breaks either way.

## L4.5: Explorer WebUI (optional)

Ask the user a structured question:

- **Header:** "WebUI"
- **Options** (use these labels and descriptions verbatim):
  - A) **Skip WebUI** — Smallest stack. API + Swagger
    docs only. `http://localhost:8080/` lands on the API docs.
  - B) **Enable WebUI** — Adds the Explorer React front-end at
    `http://localhost:8080/ui/`. Requires an extra image build
    (`docker/Dockerfile.explorer`).
- Free-form input is always available — the user can type their own
  answer — so don't add an explicit "Other" option manually.

If the user picks B, add `docker-compose.web-ui.yml` to the compose
chain in L5 and set `WEB_UI=on` for the smoke step in L6.

## L5: Build the compose command

**Variables to set (as env exports before the command):**

| Selection | Environment variables |
|-----------|---------------------|
| Public S3 | `DEEPSEARCH_CRAWLER_PATH={chosen path}` |
| Custom S3 | `S3_STORAGE_BUCKET_NAME`, `S3_STORAGE_REGION_NAME`, optionally `S3_STORAGE_AWS_ACCESS_KEY_ID`, `S3_STORAGE_AWS_SECRET_ACCESS_KEY`, `S3_STORAGE_AWS_ENDPOINT_URL` (if custom endpoint), `DEEPSEARCH_CRAWLER_PATH`. **If the user said the bucket is writable**, also set `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` (the GPU-plugins overlay defaults to `False`, matching the public read-only bucket). Note: when the s3proxy-auth overlay is used, the host-level `S3_STORAGE_AWS_ENDPOINT_URL` is the **upstream** endpoint (read by s3proxy's `JCLOUDS_ENDPOINT`); the overlay overrides all services to use `http://s3proxy:80` internally. |
| Nucleus *(deprecated)* | `STORAGE_BACKEND_TYPE=nucleus`, `OV_SERVER`, `OV_USERNAME`, `OV_PASSWORD`. Plus `BASIC_AUTH="$OV_USERNAME:$OV_PASSWORD"` for the smoke step. |
| Local filesystem | `LOCAL_FS_DATA_DIR={path}`, `DEEPSEARCH_CRAWLER_PATH=/`, `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` (s3proxy serves a writable local dir). |
| Storage API | `STORAGE_BACKEND_TYPE=storage_api`, `STORAGE_API_GRPC_ENDPOINT={container-reachable host:port}`, optionally `STORAGE_API_BASE_URI`, `STORAGE_API_SSL`, and either `STORAGE_API_TOKEN="$VARNAME"` or the `STORAGE_API_OPENID_*` set, `DEEPSEARCH_CRAWLER_PATH={chosen path}`. No gateway Basic Auth. Uses base + standard overlays (no dedicated compose file). |
| VLM enabled | `USDSEARCH_LLM_API_KEY`. Optional: `USDSEARCH_LLM_BASE_URL` (non-default endpoint), `USDSEARCH_VISION_METADATA_MODEL`, `USDSEARCH_LLM_PARSING_MODEL` (LLM query parser; the overlay enables `/llm_parse/*` on the shared connection). |

**Compose files to include:**

| Selection | Files |
|-----------|-------|
| Base (always) | `docker-compose.yml` |
| WebUI enabled | `+ docker-compose.web-ui.yml` |
| GPU plugins | `+ docker-compose.gpu-plugins.yml` |
| Custom S3 endpoint + GPU plugins | `+ docker-compose.s3proxy-auth.yml` |
| VLM plugins | `+ docker-compose.vlm-plugins.yml` |
| Local filesystem overlay (last) | `+ docker-compose.local-fs.yml` |

**Final command pattern:**
```bash
docker compose -f docker-compose.yml \
  [-f docker-compose.web-ui.yml] \
  [-f docker-compose.gpu-plugins.yml] \
  [-f docker-compose.s3proxy-auth.yml] \
  [-f docker-compose.vlm-plugins.yml] \
  [-f docker-compose.local-fs.yml] \
  up -d --build
```

**Save the invocation prefix.** Every later docker compose command you
surface to the user (`ps`, `logs`, `down`, `up --force-recreate`,
`restart`, `exec`) **must** reuse this exact prefix — same `-f` chain,
same env vars. A bare `docker compose down` after starting with
overlays is a footgun.

Print a summary box, then run the compose command in background. Tell
the user:

- **Monitor progress:** `<PREFIX> logs -f`
- **When ready:**
  - WebUI enabled: Open http://localhost:8080/ui/ (Explorer)
  - WebUI skipped: Open http://localhost:8080/docs/ (Swagger UI)
- **API docs:** http://localhost:8080/docs/
- **Stop the stack:** `<PREFIX> down`

For Nucleus configs, the gateway gates every endpoint with HTTP Basic
Auth. The browser will prompt; users enter the same
`OV_USERNAME` / `OV_PASSWORD` used to start the stack.

For Local filesystem configs, also mention:
- **Live reindexing:** Drop new files into `LOCAL_FS_DATA_DIR` — the
  fs-watcher detects changes and triggers reindexing automatically.
- **s3proxy S3 API:** http://localhost:9000
- **Paths in API responses:** Already rewritten to local filesystem
  paths (e.g. `/path/to/assets/scene.usd`), not `s3://` URIs.

## L6: Health check + smoke

After starting, wait ~10s, then:

```bash
<PREFIX> ps --format 'table {{.Name}}\t{{.Status}}'
```

The stack takes 30–60s to fully start. Once gateway, deepsearch-api,
info-endpoint, opensearch, and siglip2-triton are healthy, run:

```bash
./scripts/quickstart-smoke.sh
```

If the user enabled the WebUI overlay, also pass `WEB_UI=on` so the
smoke script asserts `/ → /ui/` and `/ui/ → 200`:

```bash
WEB_UI=on ./scripts/quickstart-smoke.sh
```

For Nucleus configs:

```bash
BASIC_AUTH="$OV_USERNAME:$OV_PASSWORD" ./scripts/quickstart-smoke.sh
# combine with WEB_UI=on if the overlay is enabled
```

On full pass, set `USD_SEARCH_API_URL=http://localhost:8080` and return
control to the caller. On any failure:
- `/search` 0 hits → crawler still warming, wait 30s and re-run
- `/search` 0 hits (Local filesystem) → crawler may still be scanning.
  Check: `<PREFIX> logs deepsearch-crawler`. Files added after startup
  are picked up by the fs-watcher within ~2s and appear as priority
  jobs. Check: `<PREFIX> logs usdsearch-fs-watcher`
- `/search_hybrid` 0 hits → siglip2-triton still warming (~20s)
- `/info/backend/storage` fails → info-endpoint not healthy yet
- `/asset_graph/usd/prims` "no graphed hits" → `worker-ags` hasn't
  finished its first scene yet, wait ~60s
- 5xx anywhere → check `<PREFIX> logs <service>`

### L6 Deep diagnostics: Prometheus metrics

If the smoke script shows 0 hits and you need to determine pipeline
state precisely, scrape the internal Prometheus endpoints via
`docker exec`. Metrics are NOT exposed on host ports — only reachable
inside the container network.

**Crawler — stream queue state:**
```bash
docker exec usdsearch-crawler curl -s localhost:8000/metrics \
  | grep -E "^omnideepsearch_deepsearch_crawler_(stream_length|group_read|group_processed)" \
  | grep -v "^#"
```
Key metrics:
- `stream_length` — items in the Redis stream (total discovered)
- `group_read` — items read by consumer group (per `stream_group` label)
- `group_processed` — items acknowledged (per `stream_group` label)
- `group_read - group_processed` = items still pending

**Monitor-crawler — plugin dispatch progress:**
```bash
docker exec usdsearch-monitor-crawler curl -s localhost:8000/metrics \
  | grep -E "^omnideepsearch_(deepsearch_monitor_(queued|processed|queue_progress)|plugin_items_processed|plugin_tasks_queue_size|results_queue_size)" \
  | grep -v "^#"
```
Key metrics:
- `queue_progress` — % complete (processed / read × 100)
- `queued` — items dispatched but not yet processed by workers
- `plugin_items_processed{plugin_name="..."}` — files processed per plugin
- `plugin_tasks_queue_size{plugin_name="..."}` — per-plugin backlog
- `results_queue_size` — results awaiting write to OpenSearch

**Workers — per-plugin throughput:**
```bash
docker exec usdsearch-worker-img2emb curl -s localhost:8011/metrics \
  | grep -E "^omnideepsearch_worker_(processed_items|plugin_tasks_count)" | grep -v "^#"
```
Repeat for `usdsearch-worker-thumb2emb`, `usdsearch-worker-ags`.

**Pipeline is idle when all of these are zero simultaneously:**
`stream_length=0`, `queued=0`, all `plugin_tasks_queue_size=0`,
`results_queue_size=0`.
