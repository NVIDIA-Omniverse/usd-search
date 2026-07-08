<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Discovering & enabling USD-property filters (`/usd-property-catalog`)

This guide explains how to find out which USD properties your indexed corpus
actually carries, and how to turn them into filters that natural-language search
and the Explorer can use. It covers the `/usd-property-catalog` skill end to end:
what it does, how to run it, how to wire its output into a deployment, and the
exact behavior to expect in the UI and the LLM parser.

- **Skill:** [`skills/usd-property-catalog/SKILL.md`](../skills/usd-property-catalog/SKILL.md)
- **Related:** the filter system overview in
  [`docs/search-filters.md`](search-filters.md); the LLM connection in
  [`docs/models-and-config.md`](models-and-config.md).

## TL;DR

```bash
# 1. Discover what the corpus carries + audit the properties you care about
/usd-property-catalog            # (or run references/build_catalog.py directly)

# 2. Review the generated stanzas, keep the ones you want, and point the API at them
export USDSEARCH_LLM_PARSING_FIELDS_FILEPATH=/path/search_fields.yaml
export USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH=/path/usd_property_catalog.yaml  # optional grounding

# 3. Verify a query maps to the property
curl -s "$USD_SEARCH_API_URL/llm_parse/query" -H 'Content-Type: application/json' \
  -d '{"query":"props with a convex-hull collision"}'
```

## Why this exists

USD Search can filter on USD properties (`filter_by_properties`,
`filter_by_properties_numeric`, the generic `usd_property` field), but **which
properties a given corpus carries is invisible** until you ask, and the curated
filter catalog (`search_fields.yaml`) is generic. The generic `usd_property`
field is also intentionally conservative: the parser is told **not to guess**
property keys, because a guessed key silently matches nothing and can empty out
a result set (see `_build_property_keyvalue` in
`services/deepsearch_api/deepsearch_api/llm_parse/fields.py`).

The result: real, indexed properties (e.g. `physics:approximation`,
`simready_metadata_validation__profile`, vendor keys) were unreachable from
natural language unless an operator already knew them and hand-edited YAML.

This skill closes that gap by reading the corpus inventory and turning it into
(a) ready-to-use filter definitions and (b) optional grounding for the parser.

## What the skill produces

The skill calls **`GET /search/stats/usd_properties`** — the full corpus
inventory: every property key, value, and `key=value` pair, each with an
`asset_count`, sorted by coverage — and writes these files under
`./usd-property-catalog/<host-slug>/`:

| File | What it is | Used for |
|---|---|---|
| `usd_property_catalog.yaml` | Ranked inventory: key, inferred type, cardinality, top values, `asset_count` | Portable client/CLI artifact **and** the parser **grounding** source |
| `search_fields.generated.yaml` | Derived filter stanzas for the top properties by coverage (capped at top-N) | First-class filters — review, then point `FIELDS_FILEPATH` at them |
| `search_fields.p0.yaml` | Ready-to-merge stanzas for the **present audit targets**, named by concept, **coverage-independent** | The set you actually wire up to make target properties filterable |
| `p0_gap_report.md` | Present/absent table for the audit targets, with sample assets | The artifact to share with the data team for the missing ones |
| `audit_matched.json` | Machine-readable matches | Lets the skill fetch sample asset URLs |

> `search_fields.generated.yaml` is capped to the highest-coverage properties, so
> a wanted-but-thin property can fall out of it. `search_fields.p0.yaml` is the
> opposite: it always emits a stanza for every **present** audit target,
> regardless of how few assets carry it.

## Using the skill

### Prerequisites

- `USD_SEARCH_API_URL` set (via `/quickstart` or `/deploy-usdsearch`).
- Auth, if the deployment requires it: `USD_SEARCH_API_TOKEN` (Bearer) **or**
  `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` (Basic).
- **Aggregations enabled** on the API (`enable_aggregations`); the stats endpoint
  returns `403` otherwise.

### Run it

Invoke `/usd-property-catalog`, or run the bundled transform directly (it is
network-free — fetch the stats with `curl`, then transform):

```bash
curl -s ${AUTH:+-H "$AUTH"} "$USD_SEARCH_API_URL/search/stats/usd_properties" -o stats.json
uv run --no-project --with pyyaml python \
  skills/usd-property-catalog/references/build_catalog.py \
  --stats stats.json --out-dir ./out --source "$USD_SEARCH_API_URL" \
  --audit skills/usd-property-catalog/references/p0_targets.yaml
```

### The gap audit (`--audit`)

`--audit TARGETS.yaml` answers "which of these properties exist, and where's the
sample data?". The default
[`p0_targets.yaml`](../skills/usd-property-catalog/references/p0_targets.yaml)
targets five SimReady fields (License, Isaac Sim/Lab Version, SimReady Profile,
Physics backend, Collision type); copy + edit it to audit any set. Each target is
a `concept` + regex `patterns` (matched against the corpus keys — namespace
aware, because real keys hide under names like
`simready_metadata_validation__profile`) + a `field_name` (for the generated
stanza) + a `recommended_key` + a `note`.

The skill marks each target present/absent, pulls a few sample asset URLs for the
present ones, and emits both `p0_gap_report.md` and ready stanzas in
`search_fields.p0.yaml`.

## Making properties filterable

There are two independent levers, both picked up at API startup:

| Lever | Effect | Wire via |
|---|---|---|
| **Filter fields** (`search_fields.yaml`) | First-class filters: parsed from natural language and advertised on `GET /llm_parse/fields` | `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` / Helm `…llm_parsing.fields` |
| **Grounding catalog** (`usd_property_catalog.yaml`) | Makes the generic `usd_property` filter reliable for the long tail (parser stops guessing keys) | `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH` / Helm `…llm_parsing.property_catalog` |

### Step 1 — assemble your `search_fields.yaml`

Take the stanzas you want from `search_fields.p0.yaml` (and/or
`search_fields.generated.yaml`) and merge them into the catalog the deployment
loads. **Review them** — the generated `description`/`examples` are mechanical;
better text means better natural-language recall (see
[parser behavior](#how-the-llm-parser-uses-it)). Keep the set focused; a bloated
catalog inflates the parser prompt.

Example stanzas the skill produced for a SimReady corpus:

```yaml
fields:
  - name: collision_type
    type: string
    operators: [eq, contains]
    description: Collision approximation (convexHull / none / ...). OpenUSD MeshCollisionAPI.
    examples:
      - '"props with a convex-hull collision" -> collision_type eq "convexHull"'
    map: {kind: property_match, property: "physics:approximation"}

  - name: simready_profile
    type: string
    operators: [eq, contains]
    description: SimReady validation profile (Prop-Robotics-Isaac / -Physx / Robot-Body-Runnable / -Neutral).
    examples:
      - '"Robotics-Isaac profile props" -> simready_profile eq "Prop-Robotics-Isaac"'
    map: {kind: property_match, property: "simready_metadata_validation__profile"}
```

### Step 2 — enable it

- **docker-compose / env:**
  ```bash
  export USDSEARCH_LLM_PARSING_FIELDS_FILEPATH=/path/search_fields.yaml
  export USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH=/path/usd_property_catalog.yaml  # optional
  ```
  In the quickstart compose stack, the container also needs the generated file
  mounted. Since the catalog is per-deployment output (not committed), put both
  in a **local overlay** — e.g. `docker-compose.property-catalog.local.yml`,
  kept untracked via `.git/info/exclude` — rather than editing the committed
  compose files (a committed bind-mount of a file that doesn't exist would break
  `docker compose up` for everyone else):
  ```yaml
  services:
    deepsearch-api:
      environment:
        USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH: /usd_property_catalog.yaml
      volumes:
        - ./usd_property_catalog.yaml:/usd_property_catalog.yaml:ro
  ```
  Then add it to the stack: `docker compose -f docker-compose.yml -f docker-compose.vlm-plugins.yml -f docker-compose.property-catalog.local.yml up`
  (LLM parsing itself is enabled by the `vlm-plugins` overlay; the base compose
  disables it).
- **Helm:** paste the YAML inline; the chart mounts each file and sets the env var:
  ```yaml
  ngsearch:
    microservices:
      search_rest_api:
        llm_parsing:
          fields: [ ... ]                 # the search_fields.yaml `fields:` list
          property_catalog: { properties: [ ... ] }  # the usd_property_catalog.yaml mapping
  ```

### Step 3 — verify

```bash
curl -s "$USD_SEARCH_API_URL/llm_parse/fields"      # the new field appears in the catalog
curl -s "$USD_SEARCH_API_URL/llm_parse/query" -H 'Content-Type: application/json' \
  -d '{"query":"props with a convex-hull collision"}'   # -> filter_by_properties: physics:approximation=convexHull
```

## Worked example — the SimReady P0 fields

Auditing a SimReady corpus splits the five P0 fields into two groups:

**Present → filterable now.** `SimReady Profile`
(`simready_metadata_validation__profile`) and `Collision type`
(`physics:approximation`) are indexed. The skill emits their stanzas in
`search_fields.p0.yaml`; merge, enable, done.

**Absent → author, then enable.** `License`, `Isaac Sim/Lab Version`, and
`Physics backend` are not authored as queryable properties yet. A filter can't
return results until the data exists, so:

1. Ask the data team to author them under agreed keys (the `recommended_key`
   column of the gap report, e.g. `nvidia:license`, `isaac:version`,
   `physics:backend`).
2. **Pre-stage** the stanzas now so they light up the moment the data lands:
   ```yaml
   - {name: license,           type: string, operators: [eq, contains], map: {kind: property_match, property: "nvidia:license"}}
   - {name: isaac_sim_version,  type: string, operators: [eq, contains], map: {kind: property_match, property: "isaac:version"}}
   - {name: physics_backend,    type: string, operators: [eq, contains], map: {kind: property_match, property: "physics:backend"}}
   ```
   They degrade cleanly (no data → no matches) until then. **Re-running the skill**
   after the data is indexed moves them from "absent" to "present" automatically.
3. **Interim trick:** Physics backend is already encoded in the profile value
   (`-Physx` vs `-Isaac` vs `-Neutral`), so `simready_profile contains "Physx"`
   slices by backend today without waiting for a dedicated key.

## How it shows up in the UI

The sample Explorer has two filter surfaces, and they behave differently. **A new
catalog field is usable immediately, but does not get a bespoke rail control
without an Explorer code change.**

| Surface | New catalog field (e.g. `collision_type`) |
|---|---|
| **Natural-language search bar** → removable filter chip | ✅ works automatically (parsed via `POST /llm_parse/query`) |
| **Manual USD Properties input** (Advanced) — type `physics:approximation=convexHull` or `physics:approximation:: convex` | ✅ works for any property |
| **Left filter rail** — dedicated toggle/slider/picker | ❌ not automatic: rail sections are hardcoded to specific names (`object_class`, `physics_rigid_body`, `has_collider`, `physics_mass`, `physics_density`, `dimension`) in `HybridDeepSearchUI.jsx`. A new field needs an Explorer change to get a rail control. |

In short: applied filters always show as **active chips** regardless of how they
were added; but the rail only offers **ready-made controls** for the hardcoded
SimReady set. Making an arbitrary catalog field first-class in the rail (so it
auto-grows from `GET /llm_parse/fields`) is a follow-up Explorer enhancement.

## How the LLM parser uses it

Adding a field to `search_fields.yaml` wires it into the parser automatically
(`llm_parse/fields.py`):

- the `IRFieldName` enum is regenerated, so the LLM **can** emit the field;
- the field's `description` + `examples` are injected into the system-prompt
  catalog (`build_field_catalog`), so the LLM **knows** about it;
- the mapper turns it into a real request param (e.g. `property_match` →
  `filter_by_properties: <key>=<value>`).

Two things to keep in mind:

- **Parsing quality tracks the `description`/`examples`.** Auto-generated text
  handles direct phrasings; curate it for natural ones ("convex-hull collision",
  "rigid props") to improve recall.
- **The grounding catalog only helps the generic `usd_property` field**, not
  these dedicated fields — dedicated fields rely on their own catalog entry. Use
  grounding to cover the long tail of properties you did *not* give a dedicated
  field.

## Configuration reference

| Setting | Env var | Helm value |
|---|---|---|
| Filter catalog file | `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` | `ngsearch.microservices.search_rest_api.llm_parsing.fields` |
| Grounding catalog file | `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH` | `ngsearch.microservices.search_rest_api.llm_parsing.property_catalog` |
| Per-field USD key override | `USDSEARCH_LLM_PARSING_<FIELD>_PROPERTY` (via a field's `map.property_env`) | (set the env on the deployment) |

## Keeping it fresh

The corpus changes as you index. Re-run `/usd-property-catalog` periodically (or
after a big ingest) and re-diff the gap report; newly-authored properties show up
as "present" and drop into `search_fields.p0.yaml` ready to enable.

## See also

- [`docs/search-filters.md`](search-filters.md) — the filter system, the field
  schema, and the SimReady opt-in catalog.
- [`skills/usd-property-catalog/references/catalog-schema.md`](../skills/usd-property-catalog/references/catalog-schema.md)
  — exact schemas of the generated artifacts.
- [`docs/models-and-config.md`](models-and-config.md) — the LLM connection and the
  full config map.
