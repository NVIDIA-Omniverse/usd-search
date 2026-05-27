---
name: deploy-usdsearch
description: |
  Stand up a USD Search deployment the user controls. Branches on
  local docker-compose vs. helm on Kubernetes. Local branch covers
  the full quickstart compose stack with GPU/VLM/storage-backend
  configuration. Helm branch covers the usdsearch chart at
  helm/usdsearch.
  Use when: "deploy usdsearch", "run the stack myself", "helm install
  usdsearch", "start the stack", "run usdsearch locally", "host my own".
---
# /deploy-usdsearch — stand up USD Search yourself

Branch once between **local docker-compose** and **helm on Kubernetes**,
then execute the matching runbook. Both branches end at "healthy and
smoke-tested" and set `USD_SEARCH_API_URL` so the calling skill (usually
`/quickstart`) can resume.

If the user only wants to *use* USD Search and doesn't care about
hosting it, redirect them to `/quickstart`.

**Be terse.** No preamble, no per-step narration, no recap. The user
reads the tool output. Codex can run `docker compose` non-interactively
— present each lane as a documented sequence and execute once all
required inputs are known.

**Indirect credentials — names only.** Before asking for any
`*_API_KEY`, AWS key, NGC token, or Nucleus password, grep `~/.zshrc
~/.zshenv ~/.zprofile ~/.profile ~/.bashrc ~/.bash_profile ~/.env*`
for `export <NAME>=`. If absent, ask the user to `export` it
themselves and pass back only the **name** of the env var. Never
accept a pasted secret value. Validate with a length/prefix check
(`printf 'len=%d prefix=%s\n' "${#VAR}" "${VAR:0:4}"`) and never
print more than the first 4 characters.

## Step 0 — Pick branch

Ask the user once: **local docker compose** (fastest,
laptop-friendly) or **Helm on Kubernetes** (production-shaped,
requires a GPU-equipped cluster)? The published USD Search images on
`nvcr.io/nvidia/usdsearch` are publicly pullable — no NGC API key
needed for the default install. Then proceed to the matching runbook
below.

---

# Local runbook (docker compose)

You are bringing up the full USD Search stack on this machine via the
top-level compose files at the repo root. Collect the configuration
choices in order, then start docker compose.

## L1: Pre-flight checks

Run all checks on the **host system**, not inside a restricted sandbox.
If using Codex tools, Docker and GPU checks must be run with escalated
host access when needed. Sandboxed execution can hide `/var/run/docker.sock`
or `/dev/nvidia*`, causing false `Docker unavailable` or `GPU=no`
results even when the user's normal terminal can use them.

Run all checks in a single Bash call. Each line of output is `KEY=VALUE`
so it parses directly:

```bash
# Docker CLI
if command -v docker >/dev/null 2>&1; then
  echo "DOCKER=ok ($(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,))"
else
  echo "DOCKER=missing"
fi

# Compose variant (prefer v2)
if docker compose version >/dev/null 2>&1; then
  echo "COMPOSE=docker compose ($(docker compose version --short 2>/dev/null))"
elif command -v docker-compose >/dev/null 2>&1; then
  echo "COMPOSE=docker-compose ($(docker-compose version --short 2>/dev/null))"
else
  echo "COMPOSE=missing"
fi

# Combined image
if docker image inspect usdsearch:latest >/dev/null 2>&1; then
  echo "IMAGE=ok ($(docker image inspect usdsearch:latest --format '{{.Size}}' | awk '{printf "%.1f GB", $1/1024/1024/1024}'))"
else
  echo "IMAGE=missing"
fi

# Git LFS — siglip2-triton image build COPYs ~7.2 GB ONNX weights from
# services/siglip2-triton/model_repo/ which are LFS-tracked. Without
# `git lfs pull`, the build silently succeeds with 134-byte pointer
# files and SigLIP2 fails at runtime.
if ! command -v git >/dev/null 2>&1; then
  echo "GIT_LFS=git-missing"
elif ! git lfs version >/dev/null 2>&1; then
  echo "GIT_LFS=missing (install git-lfs, then run 'git lfs install && git lfs pull')"
else
  total=$(git lfs ls-files 2>/dev/null | wc -l)
  pointers=$(git lfs ls-files 2>/dev/null | awk '$2=="-"' | wc -l)
  if [ "$total" -eq 0 ]; then
    echo "GIT_LFS=no-tracked-files"
  elif [ "$pointers" -gt 0 ]; then
    echo "GIT_LFS=not-pulled (${pointers}/${total} files are pointers; run 'git lfs pull')"
  else
    echo "GIT_LFS=ok (${total} files fetched)"
  fi
fi

# GPU
if nvidia-smi >/dev/null 2>&1; then
  echo "GPU=yes ($(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1))"
else
  echo "GPU=no"
fi

# Already-running quickstart containers
running=$(docker ps --filter "name=usdsearch-" --format '{{.Names}}' 2>/dev/null | wc -l)
echo "STACK_RUNNING=${running}"
```

Display a summary table using `✓` (present/ready), `⚠` (missing but
recoverable), `✗` (blocker):

```markdown
| Check          | Status | Detail                                  |
|----------------|--------|-----------------------------------------|
| Docker         | ✓      | 27.3.1                                  |
| Compose        | ✓      | docker compose v2.29.7                  |
| usdsearch:latest image | ✓ | 0.4 GB                               |
| Git LFS        | ✓      | 14 files fetched                        |
| GPU            | ✓      | NVIDIA RTX A6000                        |
| Stack running  | ✓      | not running                             |
```

After printing the table, branch on the results:

- **Docker or Compose missing (`✗`):** Before stopping, verify from the
  host system or rerun with escalated host access. If it still fails,
  stop and tell the user what to install or which Docker permission to fix.
- **Image missing (`⚠`):** Build it (this takes a few minutes):
  ```bash
  docker build --platform linux/amd64 \
    -f docker/Dockerfile.usdsearch -t usdsearch:latest .
  ```
- **Git LFS missing or `not-pulled` (`✗`):** Stop. The siglip2-triton
  image build needs the ONNX weights at
  `services/siglip2-triton/model_repo/`. Without them the image builds
  with 134-byte pointer files and SigLIP2 fails at runtime. Tell the
  user to run:
  ```
  git lfs install
  git lfs pull
  ```
  Re-run the L1 checks after they're done.
- **GPU missing (`⚠`):** Before skipping GPU plugins, verify from the
  host system or rerun `nvidia-smi -L` with escalated host access. If
  sandboxed execution failed but host execution sees a GPU, treat the
  deployment as GPU-enabled and add `docker-compose.gpu-plugins.yml`.
  Only skip GPU plugins when host-side verification also reports no
  usable GPU.
- **Stack already running (`STACK_RUNNING > 0`):** List the running
  containers and ask whether to leave them, restart (`down` then `up`),
  or just `up` over the top to reconcile changes.

### L1 Troubleshooting

If Docker-related checks fail, branch on the symptom:

- **Daemon won't start (no systemd):** On GKE-kernel or container-
  optimized hosts where `systemctl` is absent, `get.docker.com` installs
  Docker but the daemon never starts. Fallback:
  ```bash
  sudo dockerd &>/tmp/dockerd.log &
  ```
  For persistence across reboots: `@reboot sudo dockerd &>/tmp/dockerd.log`.

- **`permission denied` on `/var/run/docker.sock`:** The current user is
  not in the `docker` group. Fix:
  ```bash
  sudo usermod -aG docker "$USER"
  ```
  Then start a **new shell session** (group membership doesn't take
  effect in the current shell). Alternatively, prefix all docker commands
  with `sudo`.

- **NVIDIA runtime not found after `nvidia-ctk runtime configure`:**
  The running dockerd must be **fully restarted** (not just SIGHUP'd)
  for the nvidia runtime to be picked up. `kill -HUP` is insufficient.
  ```bash
  sudo systemctl restart docker        # systemd hosts
  sudo kill $(cat /var/run/docker.pid) && sudo dockerd &>/tmp/dockerd.log &  # no-systemd hosts
  ```
  Verify: `docker info | grep -i nvidia` should show the runtime.

## L2: Storage backend

Ask the user: "Which storage backend should USD Search index?"
Prefix each option's label with its conceptual group in square
brackets so the hierarchy is visible in the picker — the two groups
are `[Public Asset Library]` and `[Custom Library]`:

- **A) [Public Asset Library] Public S3** — Indexes NVIDIA's
  `omniverse-content-production` bucket - no credentials needed.
  Great for exploring sample USD assets.
- **B) [Custom Library] S3 bucket** — Your own S3 bucket.
  You'll need bucket name, region, and credentials (if relevant).
- **C) [Custom Library] Local filesystem** — Search Your Own Local
  Files - no credentials needed. Mounts a local directory directly
  via s3proxy. Files appear in real time — no copy step, no cloud
  credentials. A file-watcher auto-triggers reindexing when you
  add/change assets.
- **D) [Custom Library] Nucleus (to be deprecated)** — NVIDIA
  Omniverse Nucleus server. Requires your own server hostname/IP
  plus `OV_USERNAME` / `OV_PASSWORD`. Note: Nucleus backend will be
  deprecated soon - S3 bucket is favorable.

If the user picks **A (Public S3)**, follow up with a crawler-scope
question — the public bucket is large so indexing it whole takes a
while:

- **A) Smaller branch — `/Assets/Isaac/6.0/Isaac/`** — well-populated
  with common warehouse items, fast to index.
- **B) A smaller branch of the user's choice** — accept any sub-path
  under the bucket (e.g. `/Projects/..`).
- **C) Whole bucket** — much larger OpenSearch index, much longer to
  index, but full coverage of warehouse items and robots.

The chosen path becomes `DEEPSEARCH_CRAWLER_PATH` in L4.

If the user picks **B (Custom S3)**, ask for:
- Bucket name
- Region — if the user also provides a custom endpoint URL (below),
  try to infer region from the hostname before asking. Common patterns:
  `pdx` → `us-west-2`, `iad` / `iad1` → `us-east-1`,
  `fra` → `eu-central-1`, `sin` → `ap-southeast-1`,
  `syd` → `ap-southeast-2`. If the hostname contains a recognizable
  region code, suggest it as the default rather than presenting a
  generic pick list. If unrecognizable, ask normally.
- Whether credentials are needed. **Never ask for the access key or
  secret itself.** The user exports their credentials as environment
  variables in their shell; they pass back only the **names** of those
  variables — e.g. `DS_STAGING_AWS_ACCESS_KEY_ID` and
  `DS_STAGING_AWS_SECRET_ACCESS_KEY`. At invocation time, map them to
  the prefixed canonical names the stack reads:
  ```bash
  S3_STORAGE_AWS_ACCESS_KEY_ID="$DS_STAGING_AWS_ACCESS_KEY_ID" \
  S3_STORAGE_AWS_SECRET_ACCESS_KEY="$DS_STAGING_AWS_SECRET_ACCESS_KEY" \
  docker compose …
  ```
  The `S3_STORAGE_` prefix is mandatory — see "Indirect credentials"
  above.
- **Custom endpoint URL** — if the bucket is on an S3-compatible store
  (MinIO, Ceph, s3proxy, Cloudflare R2, etc.) rather than real AWS,
  ask for the endpoint URL (e.g. `https://pdx.s8k.io`). Set
  `S3_STORAGE_AWS_ENDPOINT_URL=<url>`. If on real AWS, omit this var.
- Whether the bucket is **read-only** for this deployment. Ask:
  "Is this bucket read-only (no IAM permission to write objects), or
  can the workers write back to it (e.g. for thumbnails under
  `.thumbs/`)?"
  - **Writable** — Workers
    generate and upload thumbnails. Sets
    `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` in L5.
  - **Read-only** — Workers skip thumbnail uploads to avoid
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

If the user picks **D (Nucleus)**, ask for:
- **OV_SERVER** — the user's own Nucleus server hostname or IP. Do not
  suggest a specific server. Also ask the same crawler-path question
  as the public-S3 lane.
- **OV_USERNAME** (env-var **name** only).
- **OV_PASSWORD** (env-var **name** only).

**Important — Nucleus gateway gates APIs with Basic Auth.** When
`STORAGE_BACKEND_TYPE=nucleus`, every gateway-proxied API requires
HTTP Basic Auth using the same `OV_USERNAME:OV_PASSWORD`. The smoke
step (L6) **must** set `BASIC_AUTH=$OV_USERNAME:$OV_PASSWORD`.
Otherwise every endpoint returns 401, which is misleading because the
stack itself is fine.

If the user picks **C (Local filesystem)**, ask for the **local
path** to their assets directory. There is no default — the env var
`LOCAL_FS_DATA_DIR` is required by the compose overlay. Accept any
absolute path (e.g. `/home/user/my-assets`).

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

Ask the user: "Enhance search quality by enabling VLM metadata
generation?

(VLM metadata generation enhances search quality by generating rich,
searchable descriptions and tags from images using a remote VLM
API.)" Two options:

- **A) Yes, enable VLM metadata** — Requires an API key (env-var name).
- **B) No, skip VLM** — No API key needed - fastest way to get started.

If the user picks A, ask for the **provider**:

- **A) `openai`** *(Recommended)* — Default model `gpt-4o`.
- **B) `inference_hub`** — NVIDIA Inference Hub, OpenAI-compatible.
  Default model `gcp/google/gemini-3-flash-preview`. Default base URL
  `https://inference-api.nvidia.com`.
- **C) `anthropic`** — Default model `claude-3-5-sonnet-latest`.
- **D) `nim`** — Default model `meta/llama-4-maverick-17b-128e-instruct`.

If the user wants a provider not in the list (`azure_openai`, `google`,
`qwen`, `qwen_alibaba`, `mistralai`), accept their free-text choice.

Then ask for the **name of the environment variable** that holds their
API key. Never ask for the raw key. The vision-endpoint convention is
`<PROVIDER_UPPERCASED>_API_KEY` (e.g. `INFERENCE_HUB_API_KEY`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `NIM_API_KEY`).

## L4.5: Explorer WebUI (optional)

Ask the user one short question with two options:

- **A) Skip WebUI** — Smallest stack. API + Swagger docs only.
  `http://localhost:8080/` lands on the API docs.
- **B) Enable WebUI** — Adds the Explorer React front-end at
  `http://localhost:8080/ui/`. Requires an extra image build
  (`docker/Dockerfile.explorer`).

If the user picks **B**, add `docker-compose.web-ui.yml` to the compose
chain in L5 and set `WEB_UI=on` for the smoke step in L6.

## L5: Build the compose command

**Variables to set (as env exports before the command):**

| Selection | Environment variables |
|-----------|---------------------|
| Public S3 | `DEEPSEARCH_CRAWLER_PATH={chosen path}` |
| Custom S3 | `S3_STORAGE_BUCKET_NAME`, `S3_STORAGE_REGION_NAME`, optionally `S3_STORAGE_AWS_ACCESS_KEY_ID`, `S3_STORAGE_AWS_SECRET_ACCESS_KEY`, `S3_STORAGE_AWS_ENDPOINT_URL` (if custom endpoint), `DEEPSEARCH_CRAWLER_PATH`. **If the user said the bucket is writable**, also set `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` (the GPU-plugins overlay defaults to `False`, matching the public read-only bucket). Note: when the s3proxy-auth overlay is used, the host-level `S3_STORAGE_AWS_ENDPOINT_URL` is the **upstream** endpoint (read by s3proxy's `JCLOUDS_ENDPOINT`); the overlay overrides all services to use `http://s3proxy:80` internally. |
| Nucleus *(deprecated)* | `STORAGE_BACKEND_TYPE=nucleus`, `OV_SERVER`, `OV_USERNAME`, `OV_PASSWORD`. Plus `BASIC_AUTH="$OV_USERNAME:$OV_PASSWORD"` for the smoke step. |
| Local filesystem | `LOCAL_FS_DATA_DIR={path}`, `DEEPSEARCH_CRAWLER_PATH=/`, `S3_STORAGE_ALLOW_NON_SYSTEM_WRITES=True` (s3proxy serves a writable local dir). |
| VLM enabled | `METADATA_GENERATION_VLM_SERVICE={provider}`; `{PROVIDER_UPPERCASED}_API_KEY`. For `inference_hub`, optional `INFERENCE_HUB_MODEL` / `INFERENCE_HUB_BASE_URL`. |

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

Print a summary box, then run the compose command. Tell the user:

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
  paths (e.g. `/home/user/assets/scene.usd`), not `s3://` URIs.

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

---

# Helm runbook (Kubernetes)

You are installing the `usdsearch` Helm chart at `helm/usdsearch/`.

## H1: Verify prerequisites

- Kubernetes cluster with GPU nodes (min 1 NVIDIA GPU for embedding;
  +1 RTX for rendering if enabled)
- Helm 3+
- S3 bucket name, region, and AWS credential env-var names (omit creds
  for an anonymous public bucket like `omniverse-content-production`)
- VLM API key env-var name if labeling/validation enabled
- Sufficient PV capacity (see `helm/usdsearch/values.yaml` for Redis,
  OpenSearch, Neo4j storage sizes)

The published USD Search images on `nvcr.io/nvidia/usdsearch` are
publicly pullable; **no NGC API key / docker-registry pull secret is
required for the default install.** Only create one if you've
re-mirrored the images to a private registry or are pulling pre-release
builds — see "Private registry" at the end of H5.

## H2: Required information

Collect the following from the user:

1. **S3 bucket + region.**
2. **Namespace** (default: `usdsearch` — or the user's currently active
   namespace if they specified one).
3. **AWS credentials env-var names** (`AWS_ACCESS_KEY_ID`-shaped names
   only; never the raw values). Skip this if the bucket is anonymous /
   public.
4. **Is the bucket read-only?** Use the same question pattern as the
   compose Custom S3 branch:
   - **Writable** — Default. Workers will upload
     thumbnails. Leaves `global.s3.allow_non_system_writes: true`
     (the chart default).
   - **Read-only** — Set `global.s3.allow_non_system_writes: false`
     in H5 so the thumbnail-generation worker short-circuits instead
     of attempting `PutObject` on every asset.

## H3: Optional features

Ask about each:

- **VLM Labeling** — generates descriptions, materials, colours per
  asset. Requires a VLM API key. If yes: provider
  (`openai` / `inference_hub` / `anthropic` / `nim`) + key env-var
  name + model name. Configures
  `deepsearch.vision_endpoint.vlm_service` and the selected
  `deepsearch.vision_endpoint.<provider>.*` block.
- **VLM Validation** — server-side result validation, agents can pass
  `validate_results=true` for confidence scores. Shares the labeling
  provider. Configures
  `ngsearch.microservices.search_rest_api.validation.enabled` and
  `ngsearch.microservices.search_rest_api.validation.vlm_service`.
- **Asset Graph Service** — spatial queries + dependency tracking.
  Requires Neo4j, adds ~4 GB RAM. Default: enabled. Toggle via
  `asset_graph_service_deployment.enabled`.
- **Rendering mode** — rendering is **always on**; the question is
  *how* the workers render. Two modes:
  - **Per-job `k8s_renderer` (default)** — every render request spawns
    a short-lived Kit-renderer Job. No persistent rendering pods,
    scales to zero between requests. **Do not add any of the
    `rendering_service_deployment` / `rendering_service` /
    `k8s_renderer` / `plugin_worker.rendering_settings` keys** —
    leaving them at chart defaults gives this mode.
  - **Persistent `rendering_service` (opt-in)** — keeps a Kit-renderer
    deployment hot for lower per-request latency at the cost of
    always-on GPU reservation. Only switch when the user explicitly
    asks for it. Requires adding the four-key block documented in H5
    (the `rendering_service_deployment.enabled: true` line **and** the
    three `deepsearch.microservices` overrides). Setting just one of
    them silently breaks routing.

## H4: Build dependencies

```bash
cd helm/usdsearch/
helm dependency update .
```

## H5: Create Kubernetes secrets and generate the values file

Use the env-var names the user supplied to create or reference
Kubernetes secrets. Do not put raw secret values in shell history,
values files, or chat. If the user already has equivalent secrets,
record their names and skip creation.

Skip the AWS-credentials secret entirely if the user picked an
anonymous / public bucket — set `global.s3.authentication_enabled:
false` in the values file instead.

Example secret creation pattern (authenticated S3 + VLM key):

```bash
AWS_ACCESS_KEY_ID_ENV='<AWS_ACCESS_KEY_ID_ENV_NAME>'
AWS_SECRET_ACCESS_KEY_ENV='<AWS_SECRET_ACCESS_KEY_ENV_NAME>'
VLM_API_KEY_ENV='<VLM_API_KEY_ENV_NAME>'   # e.g. INFERENCE_HUB_API_KEY
NAMESPACE=usdsearch

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

kubectl create secret generic deepsearch-s3-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=AWS_ACCESS_KEY_ID="${!AWS_ACCESS_KEY_ID_ENV}" \
  --from-literal=AWS_SECRET_ACCESS_KEY="${!AWS_SECRET_ACCESS_KEY_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -

# VLM key — name matches the chart default for the provider, e.g.
# inference-hub-vlm-api-key-secret, openai-vlm-api-key-secret, etc.
kubectl create secret generic <provider>-vlm-api-key-secret \
  --namespace "$NAMESPACE" \
  --from-literal=api-key="${!VLM_API_KEY_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Based on the user's answers, render `my-usdsearch-config.yaml` with
secret names, not secret values:

```yaml
global:
  accept_eula: true
  storage_backend_type: s3
  s3:
    bucket_name: "<USER_BUCKET>"
    region_name: "<USER_REGION>"
    # For anonymous / public buckets, set these three:
    #   authentication_enabled: false
    #   allow_system_writes: false
    #   allow_non_system_writes: false
    # and omit aws_credentials_secret_name + the access-key fields entirely.
    aws_credentials_secret_name: "deepsearch-s3-credentials"
    # Only include the next line when the user said the bucket is read-only
    # (H2 question 4). Omit it otherwise — the chart defaults to `true`.
    allow_non_system_writes: false
  secrets:
    create:
      auth: false
      registry: false
  embedding_deployment:
    type: "triton_server"

deepsearch:
  vision_endpoint:
    vlm_service: "openai"
    openai:
      api_key_secret_name: "<EXISTING_VLM_SECRET_NAME>"
      api_key_secret_field: "api-key"
      parameters:
        model: "<USER_VLM_MODEL>"

ngsearch:
  microservices:
    search_rest_api:
      validation:
        enabled: true
        vlm_service: "openai"
        openai:
          api_key_secret_name: "<EXISTING_VLM_SECRET_NAME>"
          api_key_secret_field: "api-key"

asset_graph_service_deployment:
  enabled: true
```

This default config uses **per-job `k8s_renderer` rendering** — the
chart's standard mode. Rendering itself is always on; workers spawn
short-lived Kit-renderer Jobs per request.

### Persistent rendering-service (opt-in)

Only add this block when the user explicitly asks for a persistent
in-cluster renderer instead of per-job pods. All four keys must move
together — setting any one without the others leaves the routing
broken (workers dispatch to `k8s_renderer` while the
`rendering-service` deployment sits idle, or vice versa).

```yaml
rendering_service_deployment:
  enabled: true
deepsearch:
  microservices:
    rendering_service:
      enabled: true
    k8s_renderer:
      enabled: false
    plugin_worker:
      rendering_settings:
        renderer_type: rendering_service
```

Merge into the main values file under the existing top-level
`deepsearch:` block (don't introduce a second `deepsearch:` key —
YAML deduplicates and the second wins).

### Private registry (optional)

Only needed when re-mirroring images to a private registry or pulling
pre-release builds that aren't published publicly on NGC. The default
public NGC images do **not** require this.

```bash
kubectl create secret docker-registry usdsearch-registry \
  --namespace "$NAMESPACE" \
  --docker-server=<your-registry> \
  --docker-username='<user>' \
  --docker-password="${!REGISTRY_TOKEN_ENV}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Then in `my-usdsearch-config.yaml`:

```yaml
global:
  registry: <your-registry>/<path>   # overrides default nvcr.io/nvidia/usdsearch
  ngcImagePullSecretName: "usdsearch-registry"
```

## H6: Dry-run, then install

```bash
helm install usdsearch . \
  --namespace usdsearch --create-namespace \
  -f my-usdsearch-config.yaml \
  --dry-run --debug
```

Verify the rendered output:
- Secret `deepsearch-s3-credentials` has the correct keys
- Storage connection-check job references the right bucket
- Image pull secret is created

Then install for real:

```bash
helm install usdsearch . \
  --namespace usdsearch --create-namespace \
  -f my-usdsearch-config.yaml \
  --timeout 15m
```

## H7: Verify

```bash
kubectl get pods -n usdsearch
kubectl logs job/usdsearch-s3-storage-connection-verification -n usdsearch
helm test usdsearch -n usdsearch
```

## H8: Set the API URL and return

Default service is `usdsearch-api-gateway` (ClusterIP). For local access:

```bash
kubectl port-forward svc/usdsearch-api-gateway -n usdsearch 8080:8080
```

Then `USD_SEARCH_API_URL=http://localhost:8080`. For external access,
override `api-gateway.service.type` to `NodePort` or `LoadBalancer`.

## Helm: source of truth

All configurable parameters live in `helm/usdsearch/values.yaml`. Read
that file for current defaults — do not rely on cached values.

| What you need | Where to look |
|---|---|
| All configurable parameters | `helm/usdsearch/values.yaml` |
| Sub-chart dependency conditions | `helm/usdsearch/Chart.yaml` `dependencies[].condition` |
| Secrets creation | `helm/usdsearch/templates/hooks/secrets.yaml` |
| S3 env vars injected into pods | grep `S3_STORAGE_` in `helm/usdsearch/charts/*/templates/` |
| API routes | `helm/usdsearch/templates/api_gateway_config_map.yaml` |
| Embedding service options | `global.embedding_deployment` |
| VLM provider config | `deepsearch.vision_endpoint` |
| Plugin enable/disable | `deepsearch.plugins` |
| Resource requests (GPU/RAM) | grep `resources:` in `helm/usdsearch/charts/*/templates/` |
| Crawler include/exclude | `deepsearch-crawler.crawler.extraConfig` |

## Helm: troubleshooting

- **Pre-install hook fails** → check
  `kubectl logs job/usdsearch-s3-storage-connection-verification -n usdsearch`
- **Image pull errors** → the public NGC images don't need a pull
  secret. If you do see `ErrImagePull` / `ImagePullBackOff`, check:
  network egress to `nvcr.io`, the tag actually exists at that path
  (`nvcr.io/nvidia/usdsearch/<image>:<tag>`), and `Chart.yaml`
  `appVersion` (or `global.appVersion` override) matches a published
  `images-X.Y.Z` tag. Only fall back to a pull secret if you've
  re-mirrored to a private registry — see "Private registry" in H5.
- **SignatureDoesNotMatch** → special chars in S3 secret not escaped;
  re-create the secret
- **Pods pending (GPU)** → check `nvidia.com/gpu` resources and
  tolerations on the node

---

# Important rules (both branches)

- **Indirect credentials — never accept pasted secret values.**
  Whenever the stack needs a credential (AWS keys, Nucleus passwords,
  VLM API keys, private-registry tokens), accept only the **name** of
  an env var that already holds the secret. Validate with a
  length/prefix check (`printf 'len=%d prefix=%s\n' "${#VAR}"
  "${VAR:0:4}"`) and never print more than the first 4 characters.
- **Never print secrets in full.**
- **Use the detected docker compose variant** (`docker compose` vs
  `docker-compose`) consistently.
- **Always show the full, copy-pasteable command.** Every follow-up
  docker compose action must include the same `-f <overlay>` chain
  and env vars used to bring the stack up.
- **Don't block on image builds.** Run them in the background where
  possible.
- **The minimal local config (Public S3 + CPU + no VLM)** works with
  zero configuration: `docker compose up -d --build`.
- **On success, set `USD_SEARCH_API_URL`** (`http://localhost:8080`
  locally, the port-forward URL for helm) and return control to the
  caller. The user's next step is almost always `/quickstart` (which
  in turn hands off to `/search`) so they can actually use the
  deployment.
