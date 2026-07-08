---
name: explorer-remote-proxy
license: Apache-2.0
version: 1.0.0
description: |
  Run the locally-built Explorer UI against a REMOTE, fully-hosted USD
  Search instance by proxying every API call through the local gateway.
  No local deepsearch-api / OpenSearch / SigLIP2 / Asset Graph Service —
  only the Explorer + gateway run locally, so search, thumbnails,
  dependency graphs, and downloads all work exactly as on the hosted
  instance (which already has a populated index + AGS + storage).
  Use when: you want to test/demo the local Explorer with WORKING
  dependency graphs and downloads but don't want to (or can't) build a
  local index + Asset Graph Service. Default target is the public staging
  instance (api.staging.deepsearch-horde.nvidia.com).
triggers:
  - explorer against remote
  - proxy explorer to staging
  - test the ui with dependencies
  - show dependency graphs in the ui
  - run the explorer against the hosted instance
  - staging hybrid
  - reuse the staging setup
allowed-tools: AskUserQuestion, Bash, Read, Edit, Write
---

# /explorer-remote-proxy — local Explorer, remote backend

Stand up ONLY the redesigned Explorer + gateway locally and proxy the
entire API surface (`/search*`, `/images`, `/llm_parse`, `/vlm_validate`,
`/asset_graph`, `/dependency_graph`, `/download`, `/info`, `/process`) to a
hosted USD Search instance. The hosted instance already has a populated
index, a populated Asset Graph Service, and storage access, so the
features that need a backend — **dependency graphs and downloads** — work
with zero local infra.

**Why this exists.** A local *remote-index* (BYO-OpenSearch) stack only
borrows the search index; its local AGS is empty, so dependency graphs and
multi-file download bundles come back empty. Proxying straight to a fully
hosted instance sidesteps that — and avoids the `https://…s3….amazonaws.com`
(index) vs `s3://…` (AGS) base-key scheme mismatch, because the hosted
instance is internally consistent.

**Be terse.** No preamble, no per-step narration. Never accept a pasted
secret — for an authenticated target, accept only the NAME of an env var
that already holds the credential (grep `~/.zshrc ~/.zshenv ~/.zprofile
~/.profile ~/.bashrc` for `export <NAME>=`; if absent, ask the user to
export it themselves).

## Files (committed, reusable)

- `docker-compose.staging-hybrid.yml` — overlay: swaps the gateway conf and
  trims `gateway.depends_on` to `explorer` only (no local API).
- `infra/quickstart/gateway.staging-hybrid.conf` — nginx: every API
  `location` → `http://api.staging.deepsearch-horde.nvidia.com`; `/ui`,
  `/static`, `/` → local `explorer`.

To target a DIFFERENT hosted instance, copy those two files and change one
line in the conf: `set $remote <scheme>://<host>;` (and `$remote_host`).
For HTTPS targets add `proxy_ssl_server_name on;` per location. For an
AUTHENTICATED target, inject the header per location
(`proxy_set_header Authorization "Basic ${AUTH_B64}";`) and render the conf
from a `.template` via the nginx image's envsubst entrypoint — see the
gitignored `gateway.isaac-dev-hybrid.conf.template` for the pattern.

## Steps

### 1 — Pre-flight

```bash
cd <repo root>
docker compose version >/dev/null 2>&1 && echo COMPOSE=ok || echo COMPOSE=missing
docker image inspect usdsearch-explorer:latest >/dev/null 2>&1 && echo EXPLORER_IMG=ok || echo EXPLORER_IMG=missing
curl -s -o /dev/null -w "remote /search_hybrid: %{http_code}\n" --max-time 12 \
  -X POST http://api.staging.deepsearch-horde.nvidia.com/search_hybrid \
  -H 'Content-Type: application/json' -d '{"query":"box","limit":1}'
```

- `COMPOSE=missing` → stop, tell the user to install Docker Compose v2.
- `EXPLORER_IMG=missing` → build it first (it carries the redesigned UI):
  `docker compose -f docker-compose.yml -f docker-compose.web-ui.yml -f docker-compose.staging-hybrid.yml build explorer`
  (run in background; large CRA build).
- remote `/search_hybrid` not `200` → the hosted instance is unreachable
  (VPN? wrong host?); fix before continuing.

### 2 — Bring up (only explorer + gateway)

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.web-ui.yml \
  -f docker-compose.staging-hybrid.yml \
  up -d --wait --no-build explorer gateway
```

Reuse the exact same `-f` chain for every later compose command
(`down`, `logs`, `restart`).

### 3 — Verify end-to-end through the LOCAL gateway

```bash
KEY=$(curl -s -X POST http://localhost:8080/search_hybrid -H 'Content-Type: application/json' \
  -d '{"query":"pallet","limit":10}' | python3 -c 'import sys,json
for h in json.load(sys.stdin).get("hits",[]):
    k=h["source"].get("base_key","")
    if k.lower().endswith(".usd"): print(k); break')
ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$KEY")
curl -s "http://localhost:8080/dependency_graph/graph?root_node_url=$ENC&limit=200" \
  | python3 -c 'import sys,json;d=json.load(sys.stdin);print("nodes",len(d.get("nodes",[])),"edges",len(d.get("edges",[])))'
```

Expect `nodes` ≥ 2 for a graphed asset. The UI is at
**http://localhost:8080/ui/** — hard-refresh, search, open an asset, expand
**Dependencies**.

## Gotchas (seen in practice)

- **Empty results grid.** The UI defaults to "show only with previews"
  (`showOnlyWithPreviews=true`, filters `thumbnail_exists === true`). If the
  hosted search omits/false-flags `thumbnail_exists`, the grid looks empty
  even though `/images` works. Open with `?with_previews=false`
  (`http://localhost:8080/ui/?with_previews=false`) or toggle it off in
  Display Options.
- **A query returns nothing.** The search box runs through `/llm_parse`,
  which may emit a HARD filter (e.g. `category eq traffic_light` →
  `filter_by_properties=simready_metadata_type=traffic_light`) that excludes
  every asset lacking that property. Try a plainer term, or open Filters and
  clear the interpreted-query chip.
- **`thumbnail_exists` is null in raw curl** — it's only set when the
  request includes `return_images: true` (the UI sends it; ad-hoc curls
  usually don't). Not a bug.
- **Dependency graph empty for an asset.** That specific asset isn't graphed
  on the hosted instance (intermediate `_inst`/`_base` layers often are);
  pick the top-level `*.usd`.
- **Don't `--build` siglip2-triton here.** This stack never runs it; naming
  it in an `up --build` triggers an unrelated build failure. Only ever
  build/up `explorer` (+ `gateway`).

## Teardown

```bash
docker compose -f docker-compose.yml -f docker-compose.web-ui.yml \
  -f docker-compose.staging-hybrid.yml down
```
