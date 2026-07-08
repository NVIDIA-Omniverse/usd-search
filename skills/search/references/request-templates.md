# Request templates & body construction

Detail for building the `/search_hybrid` body. SKILL.md covers the
common text path; read this when you need image/hybrid mode, the
`scoring_config` rationale, or `limit` tuning.

## The text/hybrid body template

The full body lives at `$SKILL/references/search-body.json` (see
SKILL.md for the jq fill-and-POST recipe). It carries `__QUERY__`
placeholders in `hybrid_text_query` and `vector_queries[0].query`, plus
the mandatory `scoring_config`. Keeping it in a file means the ~1.5 KB
`scoring_config` never has to sit in the model's context on every turn.

### Why `scoring_config` is mandatory

`scoring_config` is required on bare-API deployments — the stub default
returns `422 "Field siglip2-embedding.embedding not found in scoring
config"`. The template mirrors the helm chart's default at
`helm/usdsearch/charts/ngsearch/values.yaml` (minus its two `modified_by`
owner-lookup entries).

`__VISION_METADATA_FIELDS__` is a **server-side placeholder** the API
expands to the live list of VLM-generated metadata fields at request time
(see `_get_vision_metadata_fields` in
`services/deepsearch_api/.../search_backend/main.py`). Keep it verbatim in
the body — do not substitute it.

The weight-5 `exact` legs on `name`/`name.standard` boost results whose
name matches the query exactly, so precise name hits are not buried by
results that merely appear in both the fuzzy-text and vector legs.

## `limit` tuning

Default is **20** — enough for any specific query ("blue forklift",
"tomato soup can", "Fanuc m900ib280") and keeps validation work bounded.

- Broad single-class category queries ("kitchenware", "robots",
  "warehouse panels", "graspable objects") that span many variants → bump
  to **30** so subcategories aren't crowded out by the most prototypical
  variant in SigLIP2 rankings.
- Only raise to **100** when the user explicitly asks for an exhaustive
  list ("find every robot", "all conveyor belts") — large limits multiply
  context cost across validation turns.

Override with jq when filling the template, e.g.
`… | .limit=30` (see SKILL.md recipe).

## Image mode

Replace the text fields entirely:

```json
{
  "image_similarity_search": ["data:image/jpeg;base64,<BASE64>"],
  "deduplicate_by_hash": true,
  "similarity_threshold": 0.1,
  "return_metadata": true,
  "return_images": true,
  "limit": 20
}
```

Encode local files with `base64 -i <path>`. Encode a remote asset's
thumbnail with `curl … /images?asset_url=<url> | base64`. Image mode has
no `scoring_config` requirement.

## Hybrid mode

Include `hybrid_text_query`, `vector_queries`, AND
`image_similarity_search` in the same body — start from the text template
(so you keep `scoring_config`) and add the `image_similarity_search` key.

## Merging parsed filters

For filter-heavy queries you first call `/llm_parse/query` (see
`references/filters.md`). Merge the returned `search_params` into the text
template as additional top-level keys, and use the parsed `semantic_query`
— not the raw user text — for both `hybrid_text_query` and
`vector_queries[0].query`. With `python3` (save the parsed
`search_params` object to `/tmp/search_params.json` first):

```bash
python3 -c 'import json,sys; d=json.load(open(sys.argv[3])); d.update(json.load(open(sys.argv[2]))); d["hybrid_text_query"]=d["vector_queries"][0]["query"]=sys.argv[1]; print(json.dumps(d))' \
  "$SEMANTIC" /tmp/search_params.json "$SKILL/references/search-body.json" > /tmp/body.json
```
