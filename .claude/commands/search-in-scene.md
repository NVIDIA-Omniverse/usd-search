# USD Search - Spatial & Scene Graph Queries

Query a single USD scene via the Asset Graph Service (AGS): proximity,
bounding boxes, prim filters, hierarchy, and dependency graphs.

## User Request

$ARGUMENTS

## Environment

Required:
- `USD_SEARCH_API_URL` - base URL for USD Search. If unset, run
  `/quickstart` or `/search` first.

Assume the unified API gateway is in front of every request — it
proxies `/asset_graph/...` and `/dependency_graph/...` from one host.
The Asset Graph Service is an internal interface; never address it
directly.

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

### 1. Determine the query type

- Proximity: "objects near X" -> spatial radius query
- Region: "objects in area Y" -> spatial bounding-box query
- Enumeration: "what's in this scene" -> scene summary plus prim list
- Hierarchy: "show the prim tree" -> prims by root/path prefix
- Dependencies: "what does this reference" or "where is this used" ->
  dependency graph

If the user gives only a description, run `/search` first and use a
scene URL from `./search-results/<slug>/manifest.json`.

Set:

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

## Output

For spatial queries, present object paths, types, coordinates, distances,
directions, bbox dimensions, properties, and source asset URLs. For
dependency queries, present forward/reverse references.
