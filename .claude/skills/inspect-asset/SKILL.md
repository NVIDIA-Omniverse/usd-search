---
name: inspect-asset
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
allowed-tools:
  - Bash
  - Read
---

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

This skill executes the full 7-step recipe documented in
[`.claude/commands/inspect-asset.md`](../../commands/inspect-asset.md) —
that file is the single source of truth for the exact `curl`
invocations, response interpretation, fallback strategies (search by
name if only a description is given), and the final report layout.

Typing `/inspect-asset <url-or-description>` as a slash command runs
the same workflow verbatim with `$ARGUMENTS` substitution; this skill
auto-invokes when the user's natural-language request matches the
triggers above.

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
