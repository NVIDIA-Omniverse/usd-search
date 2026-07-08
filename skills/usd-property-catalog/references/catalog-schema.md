<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Artifact schemas — `usd-property-catalog`

`references/build_catalog.py` reads a `GET /search/stats/usd_properties`
response and writes the files below. The stats response shape it consumes:

```json
{
  "unique_keys":   [{"key": "physics:approximation", "asset_count": 73}, ...],
  "unique_values": [{"value": "convexHull", "asset_count": 72}, ...],
  "kv_pairs":      [{"key": "physics:approximation", "value": "convexHull", "asset_count": 72}, ...]
}
```

## `usd_property_catalog.yaml` — the portable inventory (client/CLI + grounding source)

```yaml
generated_by: usd-property-catalog
source: https://…            # API URL or stats file the catalog was built from
totals: {unique_keys: 5519, unique_values: 6687, kv_pairs: 13573}
properties:                  # sorted by asset_count desc
  - key: physics:approximation
    asset_count: 73          # # of assets carrying the property
    type: number|boolean|string   # inferred (see heuristics)
    cardinality: 2           # # of distinct values
    top_values:              # most common values, capped by --max-values
      - {value: convexHull, asset_count: 72}
      - {value: none, asset_count: 1}
```

This is a **stable contract**. Consumers:
- the deepsearch_api LLM parser, via
  `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH`, renders a bounded block of
  `key` + `top_values` into the extractor prompt so the LLM grounds the generic
  `usd_property` filter on values that exist;
- clients/scripts read `properties[].key` / `.type` / `.top_values[].value` to
  construct `filter_by_properties` tokens for `/search_hybrid`.

## `search_fields.generated.yaml` — derived filter stanzas

Same shape as the shipped
[`search_fields.yaml`](../../../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml),
so it can be pointed at directly via `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH` or
merged in. One stanza per selected property:

```yaml
fields:
  - name: simready_metadata_validation_profile   # slug of the key (camelCase split, ns-flattened)
    type: string
    operators: [eq, contains]
    description: "Auto-generated from USD property '…' (N assets). Common values: …"
    examples: ['"… is X" -> … eq "X"']
    map: {kind: property_match, property: "simready_metadata_validation__profile"}
```

**Review before shipping** — generated names are mechanical, and the heuristics
are conservative, not authoritative.

### Selection & inference heuristics

| Inferred type | Condition | `map.kind` | operators |
|---|---|---|---|
| `number` | ≥ `--min-numeric-frac` (0.95) of values parse as float | `property_numeric` | gt/gte/lt/lte/eq |
| `boolean` | distinct values ⊆ {true,false,0,1,yes,no,on,off,t,f} | `property_exists` | eq/exists |
| `string` (low-card) | distinct values ≤ `--max-categorical-card` (25) | `property_match` | eq/contains |
| `string` (high-card) | otherwise | *(skipped)* — left to the generic `usd_property` field + grounding |

Fields are taken in `asset_count` order, capped at `--top-n-fields` (40). A slug
that collides with a built-in field name (or an earlier generated one) gets a
stable numeric suffix (`crc32(key) % 1000`) so it never shadows a curated field.

## `p0_gap_report.md` + `audit_matched.json` (with `--audit`)

`p0_gap_report.md` is a present/absent table for the target concepts in the
`--audit` file (default `p0_targets.yaml`), matched against `unique_keys` by
case-insensitive regex (namespace-aware — real keys hide under nested names like
`simready_metadata_validation__profile`). Present concepts list their matched
keys + sample assets (when `--samples` is supplied); absent ones are grouped
under a "raise with the data/SimReady team" section with the `recommended_key`.

`audit_matched.json` is the machine-readable form
(`{present: [{concept, top_key, token}], absent: [concept]}`) the SKILL.md uses
to fetch sample asset URLs for the present concepts.

`search_fields.p0.yaml` holds ready-to-merge `search_fields` stanzas for the
**present** targets, named by each target's `field_name` and filtering on its
`recommended_key` when that key is actually present (else the highest-coverage
match). Unlike `search_fields.generated.yaml` these are **coverage-independent**:
a wanted-but-thin property (e.g. `physics:approximation`, ~73 assets) still gets
a first-class filter. Merge the ones you want into the deployment's
`search_fields.yaml`.
