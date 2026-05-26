---
name: search-in-scene
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
allowed-tools:
  - Bash
  - Read
---

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

This skill executes the recipe documented in
[`.claude/commands/search-in-scene.md`](../../commands/search-in-scene.md) —
that file is the single source of truth for the exact `curl`
invocations, query-type dispatch (proximity vs. region vs.
enumeration vs. dependency), prim-response field interpretation, and
the combined search-plus-scene flow.

Typing `/search-in-scene <scene-url-and-question>` runs the same
workflow with `$ARGUMENTS` substitution; this skill auto-invokes when
the user's request matches the triggers above.

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
