---
name: usd-property-catalog
license: Apache-2.0
version: 1.0.0
description: |
  Discover which USD properties a USD Search deployment's corpus actually
  carries, and turn that into local config: hits
  GET /search/stats/usd_properties, then builds a ranked
  usd_property_catalog.yaml (the grounding source for the built-in LLM query
  parser) plus ready-to-use search_fields.generated.yaml filter stanzas. Has a
  P0 "gap audit" mode that reports which target properties are present/absent
  and pulls sample assets for parsing validation.
  Use when: "what USD properties can I filter on", "discover usd properties",
  "build a property catalog", "which metadata is in the index", "audit P0
  metadata", "ground the query parser on real properties".
triggers:
  - discover usd properties
  - usd properties available
  - what can i filter on
  - build property catalog
  - filterable properties
  - usd property catalog
  - audit p0 metadata
  - ground the query parser
allowed-tools: Bash, Read
---

# /usd-property-catalog — discover & catalog a corpus's USD properties

The USD Search index stores per-asset USD properties (`usd_properties`), but
which keys/values a given corpus carries is invisible until you ask. This skill
asks `GET /search/stats/usd_properties` (the full corpus inventory — every key,
value, and key=value pair with an `asset_count`) and turns it into local files
you can commit and wire into the deployment.

Human-facing setup & usage guide (how to enable filters, UI/parser behavior):
[`docs/usd-property-catalog.md`](../../docs/usd-property-catalog.md).

**Be terse.** Run the fetch, build the artifacts, show the summary + gap report,
stop. No per-curl narration.

## Environment

Required:
- `USD_SEARCH_API_URL` — set by `/quickstart` or `/deploy-usdsearch`. If unset,
  redirect the user to `/quickstart` first.

Optional auth (mutually exclusive — pick whichever matches the deployment):
- `USD_SEARCH_API_TOKEN` — Bearer JWT or plain API key
- `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` — HTTP Basic

Before asking for any credential, grep `~/.zshrc ~/.zshenv ~/.zprofile
~/.profile ~/.bashrc ~/.bash_profile ~/.env*` for `export <NAME>=`; if absent,
ask the user to `export` it themselves — never accept a pasted secret value.

Routes assume the unified API gateway: use the unversioned
`/search/stats/usd_properties` and `/search_hybrid`.

**Auth header logic** (same as `/search`):
- `USERNAME` + `PASSWORD` set → `Authorization: Basic $(printf '%s:%s' "$U" "$P" | base64)`
- `TOKEN` non-empty and not `x` → `Authorization: Bearer $TOKEN`
- Otherwise → no Authorization header

The stats endpoint requires aggregations to be enabled. A `403`
("Aggregations are disabled") means the deployment set
`enable_aggregations=false` — tell the user; there is no client-side fallback.

## 1. Fetch the inventory

```bash
SLUG=$(printf '%s' "$USD_SEARCH_API_URL" | sed -E 's#^https?://##; s#[^a-zA-Z0-9]+#-#g; s#-+$##')
DIR="./usd-property-catalog/$SLUG"; mkdir -p "$DIR"
# (build $AUTH per the logic above)
curl -s ${AUTH:+-H "$AUTH"} "$USD_SEARCH_API_URL/search/stats/usd_properties" -o "$DIR/stats.json"
```

Check the response is JSON with `unique_keys`/`unique_values`/`kv_pairs` (not a
401/403 HTML body) before continuing.

## 2. Build the catalog artifacts

The transform lives in `references/build_catalog.py` (pure, no network). Run it
with uv and `--no-project` so PyYAML is pulled in without building the workspace:

```bash
uv run --no-project --with pyyaml python \
  "$(dirname "$0")/references/build_catalog.py" \
  --stats "$DIR/stats.json" --out-dir "$DIR" --source "$USD_SEARCH_API_URL" \
  --audit "$(dirname "$0")/references/p0_targets.yaml"
```

Writes into `$DIR`:
- **`usd_property_catalog.yaml`** — ranked inventory (key, inferred type,
  cardinality, top values, `asset_count`). The portable client/CLI artifact and
  the grounding source for the LLM parser.
- **`search_fields.generated.yaml`** — derived filter stanzas for high-signal
  properties (review before use).
- **`p0_gap_report.md`** + **`audit_matched.json`** — present/absent verdict for
  the target concepts.
- **`search_fields.p0.yaml`** — ready-to-merge filter stanzas for the **present**
  target concepts, named by `field_name` (e.g. `collision_type`,
  `simready_profile`). Coverage-independent, so a thin-but-wanted property still
  gets a first-class filter (unlike `search_fields.generated.yaml`, which is
  capped to the top properties by coverage). These are what you wire up to make
  the target properties filterable.

Show the printed JSON summary and `cat "$DIR/p0_gap_report.md"`.

## 3. (Audit) Enrich the gap report with sample assets

For each present concept, fetch a few sample asset URLs (the sample data needed
to validate parsing), then re-run with `--samples` to fold them into the report:

```bash
python3 -c 'import json,sys;[print(x["top_key"]) for x in json.load(open(sys.argv[1]))["present"]]' \
  "$DIR/audit_matched.json" | while read -r KEY; do
    curl -s ${AUTH:+-H "$AUTH"} -X POST -H 'Content-Type: application/json' \
      -d "{\"description\":\"\",\"filter_by_properties\":\"${KEY}=\",\"return_usd_properties\":true,\"limit\":4}" \
      "$USD_SEARCH_API_URL/search_hybrid" \
    | python3 -c 'import json,sys;d=json.load(sys.stdin);print(json.dumps([ (h.get("source") or {}).get("url") or (h.get("source") or {}).get("base_key") for h in d.get("hits",[])]))' \
    | KEY="$KEY" python3 -c 'import json,os,sys;print(json.dumps({os.environ["KEY"]:json.load(sys.stdin)}))'
  done | python3 -c 'import json,sys;m={};[m.update(json.loads(l)) for l in sys.stdin];json.dump(m,open(sys.argv[1],"w"))' "$DIR/samples.json"
# re-run, folding samples into p0_gap_report.md
uv run --no-project --with pyyaml python "$(dirname "$0")/references/build_catalog.py" \
  --stats "$DIR/stats.json" --out-dir "$DIR" --source "$USD_SEARCH_API_URL" \
  --audit "$(dirname "$0")/references/p0_targets.yaml" --samples "$DIR/samples.json"
```

To audit a different set of properties, copy `references/p0_targets.yaml`, edit
the `targets` (each is a concept + regex `patterns` + `recommended_key` + `note`),
and pass it to `--audit`.

## 4. Wire it into the deployment

The catalog only changes behavior once a deployment points at it. Two seams (see
`docs/search-filters.md` and `docs/models-and-config.md`):

- **Ground the LLM parser on real keys/values** — point the parser at the
  catalog so it stops guessing property keys:
  - env / compose: `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH=/path/usd_property_catalog.yaml`
  - helm: `ngsearch.microservices.search_rest_api.llm_parsing.property_catalog`
- **Add first-class filter fields** — review `search_fields.generated.yaml`,
  keep the stanzas you want (merge into the shipped `search_fields.yaml` or use
  as-is), then:
  - env / compose: `USDSEARCH_LLM_PARSING_FIELDS_FILEPATH=/path/search_fields.generated.yaml`
  - helm: `ngsearch.microservices.search_rest_api.llm_parsing.fields`

Both are picked up at API startup; the Explorer's "+ Add filter" dropdown and
`GET /llm_parse/fields` reflect the field catalog automatically.

## Client / CLI usage

`usd_property_catalog.yaml` is a stable contract: `properties[].key` /
`.type` / `.top_values[].value` let any script build `filter_by_properties`
tokens for `/search_hybrid` without re-querying stats. `/search` reads it the
same way.
