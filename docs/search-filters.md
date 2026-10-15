<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Search filters — discover & add what your deployment can filter on

USD Search understands plain-language queries, but it also lets you **filter** on
concrete properties of your assets — file type, size, creation date, physics
flags, polygon count, object class, custom USD properties, and anything else your
deployment chooses to expose. You don't have to memorize which properties exist
or how to phrase them: the Explorer shows an **"+ Add filter"** dropdown that
lists every filter this deployment supports, and whatever you add is folded into
the query that the LLM parses.

The available filters are **configurable per deployment** (see
[Configuring the catalog](#configuring-the-catalog-per-deployment)), so two
different USD Search instances can offer two different filter sets — each tuned to
the USD properties that actually exist in that catalog.

## For users: the "Add filter" dropdown

Next to the active-filter chips under the search bar there is an **"+ Add filter"**
pill. Click it to open a searchable dropdown of everything you can filter on. Each
row shows the filter's name and a short description of what it matches.

There are two kinds of filter:

- **On/off filters** (e.g. *rigid body physics*, *has collider*) — click the row
  once to add it. No value needed.
- **Value filters** (e.g. *file size*, *polygon count*, *dimensions*, *object
  class*) — type a value into the inline box and press **Enter** (the placeholder
  shows the expected form, e.g. *"over 10MB"*, *"under 10000"*, *"after
  2024-01-01"*).

You can also just **type** part of a filter's name into the dropdown's search box
to find it quickly.

### How a filter becomes a search

When you add a filter, the dropdown turns your choice into a short natural-language
phrase (for example *"file size over 10MB"* or *"rigid body physics"*) and appends
it to whatever is already in the search bar. The combined text is then sent to the
**LLM query parser**, which formats the whole thing into a valid structured query.

This matters: the dropdown is **guided discovery**, not a separate rigid filter
engine. Because the phrase goes through the same LLM that interprets your free-text
queries, your typed query and your picked filters are reconciled together into one
coherent search. You get the discoverability of a menu with the flexibility of
natural language.

> **Example.** You type *"red forklift"*, then add **file size** with the value
> *"over 5MB"* and click **rigid body physics**. The search bar becomes
> *"red forklift, file size over 5MB, rigid body physics"*, the LLM turns that into
> a structured query (`semantic_query="red forklift"` + a `file_size_greater_than`
> filter + a `physics:rigidBodyEnabled` property filter), and the results reflect
> all three constraints.

Added filters appear as removable **chips** under the search bar. Remove a chip to
drop that constraint; a new query never silently clears the filters you added.

### Availability

The dropdown depends on the **LLM query parser** being configured for the deployment
(it's what turns the picked phrase into a query). If no LLM is reachable, the
Explorer hides the "Add filter" pill and shows a banner explaining that
LLM query parsing is not active; plain semantic search still works. See
[`docs/models-and-config.md`](models-and-config.md) for how the LLM connection is
configured.

## Configuring the catalog (per deployment)

The filter catalog is **configuration, not code**. It is read from
[`search_fields.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml)
at startup. Point the API at a different file with
`USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` to ship a custom catalog without rebuilding
the image.

Editing the YAML updates **everything at once** — the dropdown's contents, the IR
schema the LLM emits, the system-prompt catalog the LLM is grounded on, and the
deterministic mapping onto real search-request fields. There is no separate
frontend list to keep in sync; the Explorer fetches the catalog from the API at
runtime via `GET /llm_parse/fields`.

### A field definition

Each entry declares a filter (the example below is one of the
[opt-in physics fields](#physics-and-dataset-filters-opt-in)):

```yaml
fields:
  - name: physics_rigid_body          # IR field name (also the dropdown label, humanized)
    type: boolean                     # string | number | boolean | date | array
    operators: [eq, exists]           # comparisons the LLM may use for this field
    description: >                    # shown in the dropdown and given to the LLM
      Whether the asset has rigid-body physics. true/exists -> require it;
      false -> exclude it.
    examples:                         # worked "phrase -> field op value" hints for the LLM
      - '"with rigid body physics enabled" -> physics_rigid_body eq true'
    map:                              # how the field maps onto the real search request
      kind: property_exists
      property: "physics:rigidBodyEnabled"
      property_env: USDSEARCH_LLM_PARSING_RIGID_BODY_PROPERTY   # optional env override
    group: Physics                    # optional, UI-only: the collapsible rail section
```

- **`name` / `type` / `operators` / `description` / `examples`** are what the
  dropdown and the LLM see. The description is the user-facing hint; the examples
  ground the LLM so it phrases the filter correctly.
- **`map.kind`** selects the builder that turns an interpreted filter into concrete
  `DeepSearchSearchRequestV2` fields. Built-in kinds include `file_extension`,
  `name`, `path`, `date_range`, `size_range`, `tag`, `passthrough`,
  `property_exists`, `property_match`, `property_keyvalue`, `property_numeric`, and
  `bbox`.
- **`map.property`** is the USD property key behind a semantic field. To re-point a
  field at *your* corpus's property key without editing the file, set its
  **`map.property_env`** environment variable
  (e.g. `USDSEARCH_LLM_PARSING_RIGID_BODY_PROPERTY=myCorp:isDynamic`).
- **`label` / `group`** (optional, flat siblings of `name:`/`map:`) are UI-only
  presentation hints served through `GET /llm_parse/fields`: `label` overrides the
  humanized field name in the Explorer rail, `group` names the collapsible rail
  section the control renders under (property-backed fields without a `group`
  share a default "USD Properties" section). Neither is shown to the LLM. The
  Explorer builds its rail controls from these entries by `map.kind`:
  `property_match` becomes a multi-select value facet (top-5 values with a
  filter box and "Show 5 more" paging) and `property_exists` a toggle — each
  shown only when the indexed corpus actually carries the property. Numeric
  and bbox fields get no rail control; they stay reachable through
  natural-language queries and the Advanced drawer.

To **add** a filter, append a new entry. To **remove** one, delete its entry. To
re-target an existing field's USD property, change `map.property` (or set its
`property_env`). No code, prompt, schema, or frontend edits are required.

### Default catalog

The shipped [`search_fields.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml)
defines:

| Filter | Type | Matches |
|---|---|---|
| `file_type` | array | File extension(s), e.g. `usd`, `usdc` |
| `name` | string | Asset file name / substring |
| `path_prefix` | string | Directory the asset lives under |
| `created_at` / `modified_at` | date | Creation / last-modified date (ISO `YYYY-MM-DD`) |
| `size` | string | File size with unit, e.g. `10MB` *(shown as "file size")* |
| `created_by` | string | Owner / creator ID |
| `tag` | string | Asset tag (or `key=value` pair) |
| `usd_property` | string | Generic exact USD property in `key=value` form (the Explorer input also accepts `key:: value` for a wildcard match — see below) |
| `polygon_count` | number | Mesh polygon count (geometry complexity) |
| `dimension` | number | Overall size in meters across all axes *(shown as "dimensions")* |

#### Generic `usd_property` — exact, plus `::` pattern matching in the Explorer

`usd_property` is the escape hatch for any property that doesn't have its own
named filter. As a natural-language / catalog filter it matches the value
**exactly** (`class=vehicle`).

The underlying `filter_by_properties` request param also supports a
case-insensitive **wildcard** operator (`key=~*value*`). The Explorer's **USD
Properties** input exposes both forms:

- `key=value` — exact match.
- **`key:: value`** — pattern (contains) match, sent as `key=~*value*`. A `*` /
  `?` you type yourself is honored as-is (so `name:: fork*` is a prefix match);
  otherwise the value is wrapped as `*value*`.

This works for any property, including ones not in the dropdown — e.g.
`wikidata_class:: rack with shelves`.

##### Examples

An Explorer **USD Properties** input and the raw `filter_by_properties` value it
sends:

| Explorer USD Properties input | `filter_by_properties` sent |
|---|---|
| `wikidata_class:: rack with shelves` | `wikidata_class=~*rack with shelves*` |
| `class=vehicle` | `class=vehicle` |
| `material:: metal` | `material=~*metal*` |
| `name:: fork*` | `name=~fork*` |
| `physics:rigidBodyEnabled=True` | `physics:rigidBodyEnabled=True` |

Raw API — wildcard a property the deployment doesn't expose as a named filter:

```bash
curl -s "${USD_SEARCH_API_URL}/search_hybrid" -H 'Content-Type: application/json' -d '{
  "hybrid_text_query": "warehouse shelving",
  "filter_by_properties": "wikidata_class=~*rack with shelves*",
  "return_usd_properties": true,
  "limit": 10
}'
```

Combine clauses with commas (AND), or use `filter_by_properties_include_any`
(OR) and `exclude_filter_by_properties` (NOT); numeric ranges go through
`filter_by_properties_numeric` (e.g. `__polygon_count<5000`).

### Physics and dataset filters (opt-in)

**Physics filters are SimReady/Isaac-only — not in the default catalog.**
`physics_rigid_body`, `has_collider`, `physics_mass`, and `physics_density`
only make sense for corpora that index the canonical `physics:`-prefixed
USD-schema properties (SimReady / Isaac content), so they ship opt-in — the
same way as the dataset-specific filters below — rather than by default. When
enabled they use the canonical `physics:`-prefixed property keys, and the
Explorer **corpus-gates** each control (via `GET /search/stats/usd_properties`)
under a collapsible "Physics" rail group: an index that carries no physics
metadata simply never shows the group — no dead filters.

**Opt-in filters live in a per-deployment catalog.** Physics fields and fields
tied to a corpus's own metadata conventions (`object_class`, categories,
profiles, …) only return results where the corpus carries those properties, so
they belong in a per-deployment catalog. A complete example (physics + SimReady
fields) ships next to the default as
[`search_fields.simready.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.simready.yaml);
the recommended path is **generating** one against your index with the
[`/usd-property-catalog` skill's filter-intent mode](#discovering-your-corpuss-properties),
which also fixes up the physics keys when your corpus spells them differently
(e.g. bare `mass` instead of `physics:mass`). Enable a custom catalog per
deployment:

- **Env** (e.g. docker-compose): point `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` at
  the file (the example ships in the application image).
- **Helm**: set the catalog inline via
  `ngsearch.microservices.search_rest_api.llm_parsing.fields` (the chart mounts
  it and sets the env var automatically).
- Each property-backed field also supports a per-field env override for the
  USD property key (e.g. `USDSEARCH_LLM_PARSING_RIGID_BODY_PROPERTY`), so the
  same catalog can be re-pointed at your corpus's property names.

Catalog filters are discoverable in the Explorer's **Add filter** picker,
editable in the advanced (raw) filter fields, driven from natural-language
queries, and rendered as filter-rail controls (grouped by their `group:` key;
ungrouped property fields share the default "USD Properties" section; all
groups start collapsed). Each writes a real `/search_hybrid` filter
(e.g. `filter_by_properties: physics:rigidBodyEnabled=`) using the catalog's
resolved `property`, so it behaves like a typed filter: it shows as a removable
chip and re-runs the search. Other catalog filters (e.g. `polygon_count`) work
the same way.

## Discovering your corpus's properties

> **Full setup & usage guide:** [`docs/usd-property-catalog.md`](usd-property-catalog.md)
> — how to run the skill, make properties filterable, and what to expect in the
> UI and the parser. The summary below is the short version.

The catalog above is only useful if it points at properties your assets actually
carry — which varies per corpus. **`GET /search/stats/usd_properties`** returns
the full inventory: every USD property key, every value, and every `key=value`
pair, each with the number of assets that carry it (`asset_count`), sorted by
coverage. (It requires aggregations enabled; returns `403` otherwise.)

#### Scoping the inventory to part of the corpus

The endpoint takes the same **filter** parameters as `/search` — `search_path`,
`file_name`, `file_extension_include`, `filter_by_properties`, `filter_by_tags`,
`filter_by_properties_numeric`, `filter_url_regexp`, the date / size / user
filters, the bbox dimensions, `vision_metadata`, and `search_in_scene`. Passing
none inventories the whole corpus, exactly as before.

```bash
# What do the vehicle assets carry?
curl "$API/search/stats/usd_properties?search_path=/Projects/Vehicles/&file_extension_include=usd*"

# Which properties co-occur with class=vehicle?
curl "$API/search/stats/usd_properties?filter_by_properties=class%3Dvehicle"

# What is in this scene?
curl "$API/search/stats/usd_properties?search_in_scene=s3://bucket/scene.usd"
```

Three things worth knowing:

- **Counts stay exact.** This is an aggregation over everything the filter
  matched, not a summary of one page of search results, so the numbers are the
  real totals for that subset however large it is.
- **Filtering is asset-scoped.** `filter_by_properties=class=vehicle` returns
  *every* property those assets carry, not just `class` — which is what makes it
  useful for drill-down ("given these assets, what else can I filter on?").
- **Search-only parameters are rejected** with a `422`. An aggregation has no
  ranking, so `description`, image/vector queries, `limit` and `offset` have
  nothing to apply to; failing loudly beats returning corpus-wide numbers that
  look filtered. Filter names are checked too, so a typo is a `422` rather than a
  silently ignored parameter.

Results describe the index, not the caller's readable subset: unlike `/search`,
these numbers are **not** access-filtered (with or without filters), since
visibility is resolved per asset against the storage backend and an aggregation
cannot consult it. Deployments that cannot accept that should set
`enable_aggregations=false`, which turns the endpoint off entirely (`403`).

The **`/usd-property-catalog` skill**
([`skills/usd-property-catalog/SKILL.md`](../skills/usd-property-catalog/SKILL.md))
turns that endpoint into local, committable files:

- **`usd_property_catalog.yaml`** — the ranked inventory (key, inferred type,
  cardinality, common values, `asset_count`). A stable client/CLI contract, and
  the grounding source below.
- **`search_fields.generated.yaml`** — derived [field stanzas](#a-field-definition)
  for high-signal properties, ready to point `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH`
  at (or to merge into the shipped catalog after review).
- A **gap report** (`--audit`) of which target properties are present/absent in
  the corpus, with sample assets for the present ones.

### Grounding the parser on real properties

The generic `usd_property` filter is a free-form `key=value` escape hatch, and
the parser is deliberately told *not* to guess property keys (a guessed key
silently matches nothing). To let natural language reach real properties, point
the parser at the catalog:

- **Env / compose:** `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH=/path/usd_property_catalog.yaml`
- **Helm:** `ngsearch.microservices.search_rest_api.llm_parsing.property_catalog`
  (paste the catalog mapping; the chart mounts it and sets the env var).

When set, the extractor's prompt is grounded on the real keys (and, for
enumerable properties, their common values) that exist in the corpus, so a query
like *"props with a convex-hull collision"* maps onto `physics:approximation`
instead of being dropped. Empty disables grounding (the default).

### Explorer UI (pattern)

The Explorer already fetches `GET /llm_parse/fields` for its filter dropdown and
rail. A deployment that wants **value autocomplete** in the USD Properties input
can fetch the catalog (or the live stats endpoint) the same way and suggest
`properties[].key` / `.top_values[].value` — no server change required. (Not
shipped in the Explorer today; documented here as an integration point.)

## APIs

- **`GET /llm_parse/fields`** — returns the catalog this deployment supports as
  `[{name, value_type, operators, description, examples, params, comma_join, kind,
  property, label, group}]`, where `params` is the request-field key(s) each
  filter maps to, `comma_join` flags whether those accumulate (union) rather than
  overwrite, `kind` is the `map.kind` builder behind the field, `property` is the
  resolved USD property key (env override applied) for property-backed fields
  (`null` otherwise), and `label`/`group` are the optional UI presentation hints
  (`null` when unset). Static metadata; works even when the LLM extractor is
  disabled. This is what the Explorer fetches to populate the dropdown, drive its
  filter merge, and generate the left-rail controls (grouped by `group`, one
  control per property-backed field the corpus carries).
- **`POST /llm_parse/query`** — body `{"query": "<free text + filter phrases>"}`;
  returns the structured interpretation plus the mapped search-request parameters.
  Returns `503` if the LLM query parser is not enabled or the LLM call fails.

> **Generated clients:** `interpreted_query.filters[].field` (and
> `dropped_filters[].filter.field`) is typed as a plain **string**, not an enum,
> because the field names are per-deployment configuration — a closed enum in the
> published spec would bake one deployment's catalog into every generated client
> and break deserialization against any other. Statically-typed clients should
> match on the string and enumerate the valid names at runtime from
> `GET /llm_parse/fields`.

### When the LLM query parser is offline

The filter **catalog** never depends on the LLM — `GET /llm_parse/fields` serves
the static `search_fields.yaml`, so the Explorer's "Add filter" picker stays
populated even with `USDSEARCH_LLM_PARSING_ENABLED=false` or an unreachable
model. What degrades is the **mapping**: without the parser, picked filter
phrases are applied as plain keywords in the text search instead of structured
filters (the Explorer shows "Query parsing offline. Manual filters are still
available."). Structured filtering resumes automatically
once `/llm_parse/query` responds again.

## URL-shaped filters on a deployment that publishes rewritten URLs

If a deployment publishes public asset URLs (`global.url_mapping`, see
[configuration-map.md](configuration-map.md#public-asset-urls) — e.g. `https://`
instead of `s3://`), most filters are unaffected: they match names, paths,
properties and dates, none of which carry a URL scheme. Two are worth knowing
about, because both are evaluated against the asset's **internal** storage URL:

- **`filter_url_regexp`** — translated for you *only* when the pattern begins
  with a **literal** public prefix. `https://assets.example.com/Vehicles/.*`
  works (escaped spellings like `https://assets\.example\.com/Vehicles/.*` too);
  `https://assets\..*/Vehicles/.*` does not, because a pattern has no single
  prefix to translate, and it will simply match nothing. The internal prefix is
  regexp-escaped when substituted, so a bucket name containing `.` stays literal.
  A whole-pattern exclusion is unwrapped and translated inside the complement, so
  `~(https://assets.example.com/temp/.*)` excludes what it says it does.
- **`search_path`** / **`exclude_search_path`** — scheme-less directory paths, so
  they are unaffected in the usual case. The exception is a rule that strips or
  adds a path prefix (publishing `s3://bucket/published/v3/` as
  `https://assets.example.com/`): the path stays relative to the *internal*
  layout, so filter on `/published/v3/Vehicles/`, not `/Vehicles/`.

The safe habit either way is to write URL filters without a scheme/host prefix
(`.*[/]Vehicles[/].*`), which behaves identically on every deployment.

Everywhere else — `search_in_scene`, `asset_url` on `/images`, `/download/asset`
and `/vlm_validate/search_result`, `root_node_url` on the dependency-graph
endpoints, and asset URLs inside `image_similarity_search` / `vector_queries` —
both URL forms are accepted, so a URL copied straight out of a search response
always works.

## "More like this" / image similarity

Filters compose with **image-similarity search**, not just text. Every result
card has a *Find similar* action: the Explorer sends the asset's URL as an
image-type vector query (`vector_queries: [{query_type: "image", query:
"<asset-url>"}]`) and keeps the **currently active filters** — so "wooden
chairs under 2m" → *Find similar* on a hit returns visually similar assets
still constrained to the same size/type filters. The same works
programmatically with an uploaded image (`image_similarity_search:
["<base64>"]`) on `POST /search_hybrid`. Validation, when enabled, judges
similarity against the reference image instead of the query text.

## See also

- [`docs/models-and-config.md`](models-and-config.md) — the LLM connection, the
  Search-LLM role, and every config knob (including
  `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` and the per-field `*_PROPERTY` overrides).
- [`search_fields.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml)
  — the default catalog.
