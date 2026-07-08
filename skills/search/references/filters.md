# Filters & query parsing

Read this only when the query carries constraints (file types, dates,
sizes, physics, tags) — plain object/category queries ("yellow forklift")
don't need any of it.

## Filter-heavy queries: parse first

When the query mixes a subject with constraints — "usda forklifts
modified after 2024 under 5000 polygons" — don't guess the filter params.
Ask the deployment to parse it:

```bash
curl -s -X POST "$USD_SEARCH_API_URL/llm_parse/query" \
  -H "Content-Type: application/json" \
  -d '{"query": "low-poly usda forklifts under 5000 polygons"}'
```

Response contains the structured interpretation plus ready-to-use request
fields:

```json
{
  "interpreted_query": {"semantic_query": "forklift", "filters": [...], "unmapped_constraints": []},
  "search_params": {
    "hybrid_text_query": "forklift",
    "file_extension_include": "usda",
    "filter_by_properties_numeric": "__polygon_count<5000"
  },
  "dropped_filters": [],
  "unmapped_constraints": []
}
```

Merge `search_params` into the text-mode body (they are `/search_hybrid`
body fields) and use the parsed `semantic_query` — not the raw user text —
for both `hybrid_text_query` and `vector_queries[].query`. See the jq
merge recipe in `references/request-templates.md`.

**Surface what was not applied** — never let a constraint vanish silently:
- `dropped_filters` — matched a known field but couldn't be applied
  (unsupported operator / bad value); each has a `reason` and `message`.
- `unmapped_constraints` — match **no** filter field this deployment has
  (e.g. "Isaac version between 5 and 6"); each has verbatim `text` + a
  `note`. Not searched on at all.

If either is non-empty: run the search you can, then say e.g. "I searched
for pallets but couldn't filter on 'Isaac version between 5 and 6' — this
deployment has no such field."

`GET /llm_parse/fields` lists which filters the deployment understands
(name, type, operators, examples) — probe once per deployment if needed;
it works even when the parse LLM is down.

**Fallback contract:** `/llm_parse/query` returns **503** when the feature
is disabled or its LLM is unreachable (**404** on pre-LLM-parsing
deployments). On any non-200, fall back to plain hybrid search with the
raw text — never block the search on the parser.

## Optional filters (apply when the request implies them)

- **Size**: `min_bbox_x/y/z`, `max_bbox_x/y/z`
- **Path scope**: `search_path` (e.g. `/NVIDIA/Assets/Vehicles/`)
- **Properties**: `filter_by_properties` (e.g. `class=vehicle,material=metal`)
  - Comma-separated `key=value` tokens. `key=value` is exact; **`key=~*value*`**
    is a case-insensitive wildcard (substring) match — use it for partial /
    free-text values on any property, dropdown-listed or not
    (e.g. `wikidata_class=~*rack with shelves*`). `key=` matches existence.
    Also: `filter_by_properties_include_any` (OR), `exclude_filter_by_properties`
    (NOT), `filter_by_properties_numeric` (ranges, e.g. `__polygon_count<5000`).
  - In the Explorer's USD Properties input the same is typed as `key=value`
    (exact) or `key:: value` (pattern → `key=~*value*`).
- **Date**: `created_after`, `modified_after` (`YYYY-MM-DD`)
- **Dedup**: `deduplicate_by_hash: true`
- **File type**: `file_extension_include: "usd*"` (default)

Discover available USD properties:
```bash
curl -s "${USD_SEARCH_API_URL}/search/stats/usd_properties?search_query=<term>"
```

For a reusable, version-controllable inventory (and ready-to-use filter config),
run `/usd-property-catalog` — it turns that endpoint into a local
`usd_property_catalog.yaml` whose `properties[].key` / `.top_values[].value`
let scripts build `filter_by_properties` tokens without re-querying stats.

On SimReady-indexed corpora a deployment may also expose dedicated physics
filters — `physics_rigid_body`, `has_collider`, `object_class`
(→ `wikidata_class`), `physics_mass`, `physics_density` (opt-in catalog;
not on by default). Prefer them over raw `filter_by_properties` strings
when present; check `GET /llm_parse/fields` for what this deployment
understands. Full reference: `docs/search-filters.md`.
