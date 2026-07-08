---
name: search-in-scene
license: Apache-2.0
version: 1.0.0
description: |
  Spatial and scene-graph queries inside a USD scene via the Asset
  Graph Service. Answers: what's near a point or prim (radius), what's
  inside a bounding box, what prims of a given type or property exist
  in this scene, what does this scene reference, where is this asset
  used, what's the prim hierarchy. Optionally chains to /search_hybrid
  with image_similarity_search to find assets similar to a prim's
  source asset. Use when the user has a scene URL plus a spatial,
  structural, or dependency question.
triggers:
  - search in scene
  - search-in-scene
  - what's near
  - what is near
  - find objects near
  - prims within
  - prims of type
  - inside this scene
  - what's in this scene
  - spatial query
  - bounding box query
  - scene graph query
  - where is this asset used
  - dependencies of this scene
  - prim hierarchy
allowed-tools: Bash, Read
---

# /search-in-scene — spatial & scene-graph queries

## What this skill does

Queries the structure of a single USD scene rather than the global
asset catalog. Powered by the Asset Graph Service (AGS) and the
dependency graph endpoints. Answers questions about spatial proximity,
spatial regions, prim types, prim properties, scene hierarchy, and
asset reuse.

Fires when the user has a scene URL (or can pick one) and asks a
question that is scoped to *inside that scene* rather than across the
whole index.

## Environment

Required:
- `USD_SEARCH_API_URL` — base URL of the USD Search API

Auth — pick whichever is set, in this priority order:
1. `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` -> Basic auth
2. `USD_SEARCH_API_TOKEN` set and not `x` -> bearer-style auth header
3. None set / token is `x` -> no auth header

All endpoints go through the unified nginx API gateway:
`/asset_graph/...`, `/dependency_graph/...`, `/search_hybrid`. The
Asset Graph Service is an internal interface; do not address it
directly.

## Endpoints used

| Purpose | Endpoint |
|---|---|
| Scene overview — prim counts, types, MPU, up-axis, references | `GET /asset_graph/usd/scene_summary/?scene_url=<URL>` |
| Proximity — prims within radius of a point or another prim | `GET /asset_graph/usd/prims/spatial?scene_url=<URL>&...` |
| Region — prims inside a bounding box | `GET /asset_graph/usd/prims/spatial_bbox?scene_url=<URL>&...` |
| Filter / enumerate — by type, property, path prefix, bbox size | `GET /asset_graph/usd/prims?scene_url=<URL>&...` |
| Forward dependencies — what this scene references | `GET /dependency_graph/flat?root_node_url=<URL>` |
| Full dependency graph (nodes + edges) | `GET /dependency_graph/graph?root_node_url=<URL>` |
| Inverse — what references this scene/asset | `GET /dependency_graph/inverse/flat?root_node_url=<URL>` |
| Similar to a prim's source asset (chain to global search) | `POST /search_hybrid` with `image_similarity_search=[<base64>]` |

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

### 1. Determine the query type

- Proximity: "objects near X" → spatial radius query
- Region: "objects in area Y" → spatial bounding-box query
- Enumeration: "what's in this scene" → scene summary plus prim list
- Hierarchy: "show the prim tree" → prims by root/path prefix
- Dependencies: "what does this reference" or "where is this used" →
  dependency graph

If the user gives only a description, run `/search` first and use a
scene URL from `./search-results/<slug>/manifest.json`.

```bash
SCENE_URL='<SCENE_URL>'
```

### 2. Start with scene summary

```bash
curl -sS -G "${API}/asset_graph/usd/scene_summary/" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}"
```

The response yields:
- `n_prims` — total number of prims (objects/nodes) in the scene
- `prim_types` — count per type (Mesh, Xform, Material, Scope, etc.)
- `total_polygon_count` — scene geometry complexity
- `unique_property_keys` — available USD attributes (use these to drive
  property filters in step 5)
- `referenced_assets` — external files referenced by the scene
- `scene_mpu` — meters per unit (combine with coordinates when the user
  asks in real-world units)
- `scene_up_axis` — coordinate system (Y-up or Z-up)
- `default_prim` — entry-point prim for this asset

### 3. Proximity queries

By coordinate:

```bash
curl -sS -G "${API}/asset_graph/usd/prims/spatial" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "center_x=10" \
  --data-urlencode "center_y=0" \
  --data-urlencode "center_z=5" \
  --data-urlencode "radius=20"
```

By reference prim:

```bash
curl -sS -G "${API}/asset_graph/usd/prims/spatial" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "center_prim_usd_path=/Root/Table" \
  --data-urlencode "radius=5"
```

Report prim path, type, distance, vector, bbox, and relevant properties.

### 4. Bounding-box queries

```bash
curl -sS -G "${API}/asset_graph/usd/prims/spatial_bbox" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "min_bbox_x=0" \
  --data-urlencode "min_bbox_y=0" \
  --data-urlencode "min_bbox_z=0" \
  --data-urlencode "max_bbox_x=10" \
  --data-urlencode "max_bbox_y=5" \
  --data-urlencode "max_bbox_z=10"
```

Use the user's requested coordinates when provided. If the user asks in
real-world units, combine coordinates with `scene_mpu` from the scene
summary.

### 5. Prim enumeration and filters

```bash
# Root prims
curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "root_prim=true"

# Mesh prims
curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "prim_type=Mesh"

# Property filter
curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "properties_filter=class=vehicle"

# Children of a path
curl -sS -G "${API}/asset_graph/usd/prims" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "scene_url=${SCENE_URL}" \
  --data-urlencode "usd_path_prefix=/Root/Kitchen"
```

### 6. Dependency analysis

```bash
# Forward dependencies
curl -sS -G "${API}/dependency_graph/flat" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "root_node_url=${SCENE_URL}"

# Full graph
curl -sS -G "${API}/dependency_graph/graph" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "root_node_url=${SCENE_URL}"

# Reverse dependencies
curl -sS -G "${API}/dependency_graph/inverse/flat" \
  "${AUTH_ARGS[@]}" \
  --data-urlencode "root_node_url=${SCENE_URL}"
```

### 7. Combined search plus scene workflow

For requests such as "find a table in the scene and show what's around
it":

1. Run `/search` if the scene URL is unknown.
2. Use scene summary and prim filters to locate candidate prims.
3. Run proximity or bbox query around the selected prim.
4. If a prim has `source_asset_url`, offer `/inspect-asset` for that
   asset.

Invoking this skill — or typing `/search-in-scene <scene-url-and-question>`
as a slash command — runs this workflow; it also auto-invokes when the
user's request matches the triggers above.

## Output

Depends on the query type:
- **Proximity** — list of prims with distance and direction vectors
  from the query center
- **Region** — list of prims whose bounding boxes intersect the query
  box
- **Enumeration** — prim list with type, path, transform, bbox, and
  properties
- **Dependencies** — flat or graph view of referenced or referring
  assets
- **Hybrid** — scene summary plus the relevant filtered prim list

Every prim response includes `usd_path`, `prim_type`, `translate`,
`bbox_min/max/midpoint`, `bbox_dimension_x/y/z`, `properties`, and
`source_asset_url` when the prim is a reference — enabling immediate
hand-off to `/inspect-asset` on a specific source asset.

## Related skills

- `/inspect-asset` — drop into a specific asset URL after a scene
  query identifies an interesting prim's `source_asset_url`
- `/search` — find a scene URL first if the user only described the
  scene rather than naming it
