---
name: inspect-asset
description: |
  Deep inspection of a specific 3D asset: retrieve its metadata,
  thumbnails from multiple angles, indexing status, scene graph data,
  and dependencies. Use when the user wants a detailed report on one
  asset, asks "tell me more about this", "inspect", or follows up on
  a /search result.
---
# USD Search - Inspect Asset

Deep-inspect one 3D asset by URL. Fetch thumbnails, indexing status,
scene graph details, dependencies, and a visual report.

## Environment

Required:
- `USD_SEARCH_API_URL` - base URL for USD Search. If unset, run
  `/quickstart` or `/search` first.

Assume the unified API gateway is in front of every request — it
proxies `/images`, `/info`, `/asset_graph/...`, and
`/dependency_graph/...` from one host. The Info Endpoint and Asset
Graph Service are internal interfaces; never address them directly.

Optional:
- `USD_SEARCH_API_TOKEN` - bearer-style token or API key. Empty or `x`
  means unauthenticated.
- `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` - HTTP Basic
  auth. Basic auth takes precedence over token auth.

Before asking for any `*_API_KEY`, token, or password, grep
`~/.zshrc ~/.zshenv ~/.zprofile ~/.profile ~/.bashrc ~/.bash_profile
~/.env*` for `export <NAME>=`. If absent, ask the user to export it
themselves and pass back only the env-var name. Never accept a pasted
secret value.

Use this setup pattern for every command:

```bash
set -euo pipefail

API="${USD_SEARCH_API_URL%/}"

AUTH_ARGS=()
if [ -n "${USD_SEARCH_API_USERNAME:-}" ] && [ -n "${USD_SEARCH_API_PASSWORD:-}" ]; then
  AUTH_ARGS=(-u "${USD_SEARCH_API_USERNAME}:${USD_SEARCH_API_PASSWORD}")
elif [ -n "${USD_SEARCH_API_TOKEN:-}" ] && [ "${USD_SEARCH_API_TOKEN}" != "x" ]; then
  AUTH_SCHEME=Bearer
  AUTH_HEADER_NAME=Authorization
  AUTH_ARGS=(-H "${AUTH_HEADER_NAME}: ${AUTH_SCHEME} ${USD_SEARCH_API_TOKEN}")
fi
```

## Workflow

### 1. Identify the asset

- URL provided: use it directly (`s3://...`, `omniverse://...`, or a
  local filesystem path returned by local-FS mode).
- Name or description provided: run `/search` first, then inspect the
  best matching URL from `./search-results/<slug>/manifest.json`.

Set:

```bash
ASSET_URL='<ASSET_URL>'
OUT_DIR="./search-results/inspect-$(printf '%s' "$ASSET_URL" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-80)"
mkdir -p "$OUT_DIR"
```

### 2. Fetch thumbnails

Fetch up to four rendered views. A `404` means that offset is not
available; keep any earlier images.

```bash
for offset in 0 1 2 3; do
  code=$(curl -sS -G "${API}/images" \
    "${AUTH_ARGS[@]}" \
    --data-urlencode "asset_url=${ASSET_URL}" \
    --data-urlencode "img_offset=${offset}" \
    -o "${OUT_DIR}/thumb_${offset}.jpg" \
    -w '%{http_code}' || true)
  case "$code" in
    2*) ;;
    404) rm -f "${OUT_DIR}/thumb_${offset}.jpg" ;;
    *) rm -f "${OUT_DIR}/thumb_${offset}.jpg"; printf 'thumbnail offset %s returned HTTP %s\n' "$offset" "$code" ;;
  esac
done
```

### 3. Visually inspect thumbnails

For each saved thumbnail, invoke Codex with the image attached:

```bash
for image in "$OUT_DIR"/thumb_*.jpg; do
  [ -s "$image" ] || continue
  codex exec --json --skip-git-repo-check \
    --dangerously-bypass-approvals-and-sandbox \
    --image "$image" \
    -- "Describe this 3D asset thumbnail in detail: object identity, colors, materials, quality, artifacts, and likely use cases." \
    | grep -o '"text":"[^"]*"' | tail -1
done
```

Report what is visible. Do not claim details that are not supported by
the thumbnail.

### 4. Check indexing status

```bash
curl -sS -G "${API}/info/indexing/asset/status" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "url=${ASSET_URL}" \
  --data-urlencode "return_asset_metadata=true"
```

Interpret plugin status values:
- `in_sync` - processed and current
- `out_of_sync` - asset changed since processing
- `not_found` - not processed

Also report `storage_backend_info.asset_status` when present.

### 5. Get scene graph data

```bash
curl -sS -G "${API}/asset_graph/usd/scene_summary/" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${ASSET_URL}"

curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${ASSET_URL}" \
  --data-urlencode "root_prim=true"

curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${ASSET_URL}" \
  --data-urlencode "default_prim=true"

curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${ASSET_URL}" \
  --data-urlencode "prim_type=Mesh"
```

The scene-summary response yields:
- `n_prims` — total number of prims (objects/nodes) in the scene
- `prim_types` — count per type (Mesh, Xform, Material, Scope, etc.)
- `total_polygon_count` — scene geometry complexity
- `unique_property_keys` — available USD attributes
- `referenced_assets` — external files referenced
- `scene_mpu` — meters per unit (for real-world scale)
- `scene_up_axis` — coordinate system (Y-up or Z-up)
- `default_prim` — entry-point prim for this asset

Use prim responses for hierarchy, mesh count, dimensions, semantic
properties, and source asset references.

### 6. Get dependencies

```bash
curl -sS -G "${API}/dependency_graph/flat" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "root_node_url=${ASSET_URL}"

curl -sS -G "${API}/dependency_graph/inverse/flat" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "root_node_url=${ASSET_URL}"
```

### 7. Present the report

Include:
- Visual description from thumbnail inspection
- Asset URL and available metadata
- Indexing state by plugin
- Scene summary, root/default prims, mesh prims, dimensions, and
  polygon counts
- Forward and inverse dependencies
- Quality/readiness assessment and any gaps caused by missing
  thumbnails or warming index state
