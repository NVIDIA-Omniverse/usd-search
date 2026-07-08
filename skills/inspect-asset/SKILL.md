---
name: inspect-asset
license: Apache-2.0
version: 1.0.0
description: |
  Deep-inspect a single 3D asset by URL. Fetches multi-view thumbnails,
  per-plugin indexing status, USD scene summary (prim counts, geometry,
  scale, up-axis, default prim), prim hierarchy, forward + inverse
  dependency graphs, and optionally runs VLM relevance validation
  against a description. Use when the user asks to inspect / deep-dive /
  describe / learn about / report on a specific asset, or asks "what's
  in this USD", "tell me about this asset", "where is this asset used",
  "what does this asset reference", "is this asset indexed".
triggers:
  - inspect asset
  - inspect-asset
  - deep dive asset
  - tell me about this asset
  - describe this asset
  - what's in this usd
  - what is in this usd
  - asset details
  - asset report
  - where is this asset used
  - what does this asset reference
  - dependencies of this asset
  - is this asset indexed
  - indexing status for
allowed-tools: Bash, Read
---

# /inspect-asset — deep-inspect a USD asset

## What this skill does

Deep inspection of one 3D asset addressed by a URL
(`s3://bucket/key`, `omniverse://server/path`, or a local filesystem
path when running in local-FS mode). Produces a single comprehensive
report covering visual, structural, geometric, semantic, and indexing
dimensions of the asset.

Fires when the user has (or can supply) a specific asset URL and wants
to understand that one asset in depth — as opposed to `/search` (find
candidates) or `/search-in-scene` (spatial queries inside a scene).

## Environment

Required:
- `USD_SEARCH_API_URL` — base URL of the USD Search API (e.g.
  `https://search.simready.omniverse.nvidia.com` or
  `http://localhost:8080`)

Auth — pick whichever is set, in this priority order:
1. `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` -> Basic auth
2. `USD_SEARCH_API_TOKEN` set and not `x` -> bearer-style auth header
3. None set / token is `x` -> no auth header (public/unauth deployments)

All endpoints go through the unified nginx API gateway
(`http://localhost:8080`, NVIDIA-hosted): `/images`, `/info`,
`/asset_graph/...`, `/dependency_graph/...`. The Info Endpoint and
Asset Graph Service are internal interfaces; do not address them
directly.

## Endpoints used

| Purpose | Endpoint |
|---|---|
| Indexing status (+ optional storage metadata) | `GET /info/indexing/asset/status?url=<URL>&return_asset_metadata=true` |
| Thumbnails (multi-view, offsets 0..N) | `GET /images?asset_url=<URL>&img_offset=N` |
| Scene overview (prim counts, geometry, MPU, up-axis) | `GET /asset_graph/usd/scene_summary/?scene_url=<URL>` |
| Prim enumeration / filter / hierarchy | `GET /asset_graph/usd/prims?scene_url=<URL>&...` |
| Forward dependencies (what this references) | `GET /dependency_graph/flat?root_node_url=<URL>` |
| Inverse dependencies (what references this) | `GET /dependency_graph/inverse/flat?root_node_url=<URL>` |
| VLM relevance check vs. a description (optional) | `POST /vlm_validate/search_result` |

## Workflow

Set up the base URL and auth once. Basic auth takes precedence over
token auth; an empty or `x` token means unauthenticated. Before asking
for any token or password, grep `~/.zshrc ~/.zshenv ~/.zprofile
~/.profile ~/.bashrc ~/.bash_profile ~/.env*` for `export <NAME>=`; if
absent, ask the user to export it themselves and pass back only the
env-var name — never accept a pasted secret.

```bash
set -euo pipefail

API="${USD_SEARCH_API_URL%/}"

AUTH_ARGS=()
if [ -n "${USD_SEARCH_API_USERNAME:-}" ] && [ -n "${USD_SEARCH_API_PASSWORD:-}" ]; then
  AUTH_ARGS=(-u "${USD_SEARCH_API_USERNAME}:${USD_SEARCH_API_PASSWORD}")
elif [ -n "${USD_SEARCH_API_TOKEN:-}" ] && [ "${USD_SEARCH_API_TOKEN}" != "x" ]; then
  AUTH_ARGS=(-H "Authorization: Bearer ${USD_SEARCH_API_TOKEN}")
fi
```

### 1. Identify the asset

- URL provided: use it directly (`s3://...`, `omniverse://...`, or a
  local filesystem path returned by local-FS mode).
- Name or description provided: run `/search` first, then inspect the
  best matching URL from `./search-results/<slug>/manifest.json`.

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

### 3. Visual inspection

Inspect each saved image and report object identity, visual
characteristics, material/texture, quality, artifacts, scale impression,
and likely use cases. If multiple views are available, compare them and
assess 3D completeness.

### 4. Check indexing status

```bash
curl -sS -G "${API}/info/indexing/asset/status" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "url=${ASSET_URL}" \
  --data-urlencode "return_asset_metadata=true"
```

Interpret plugin status values:
- `in_sync` — processed and current
- `out_of_sync` — asset changed since processing
- `not_found` — not processed

Also report `storage_backend_info.asset_status` when present.

On deployments with VLM metadata generation enabled, the index also
carries per-asset generated fields (caption, description, object_type,
category, tags, colors, materials, style, scale, state, and more — the
full schema is `packages/llm-client/llm_client/metadata/metadata_fields.yaml`).
Retrieve them with a `/search_hybrid` request filtered to this asset
(`file_name` + `return_vision_generated_metadata=true`) and fold them
into the report. The two quality flags are booleans:
- `is_high_quality` — complete, properly textured, clean geometry
  (**renamed from `is_sim_ready`** — assets indexed before the rename
  may still carry the old key; treat both as the same signal)
- `has_issues` — visible defects present

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
properties, and source asset references. Note `prims` use
`response_model_exclude_none=true`, so a non-default prim omits the
`default_prim` key entirely — read it defensively.

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

See **Output** below for the report layout.

Invoking this skill — or typing `/inspect-asset <url-or-description>`
as a slash command — runs this workflow; it also auto-invokes when the
user's natural-language request matches the triggers above.

## Output

Comprehensive report: thumbnail(s) with detailed visual description,
identity (URL / size / timestamps), scene structure (prim tree, types,
default prim), geometry (polygon count, bounding box in real-world
scale using `scene_mpu`), semantic properties / labels, forward + inverse
dependencies, per-plugin indexing status, and an overall quality
assessment.

## Related skills

- `/search` — find candidate assets first if the user gave a
  description rather than a URL
- `/search-in-scene` — for spatial / scene-graph queries inside a USD
  scene rather than a single-asset deep dive
