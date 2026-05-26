---
name: search
description: |
  Search USD Search for 3D assets via /search_hybrid + /images.
  Three input modes — text query, reference image, or both. Validates
  hits via server-side is_match, then VLM validator, then visual
  inspection of thumbnails. Use whenever the user wants to find a 3D
  model, find similar assets, search visually, or get "more like
  this."
---
# Search USD Search

Take the user's **text and/or image** input, run hybrid search
against the USD Search API, and present ranked thumbnails. One
skill, three input modes.

**Be terse.** Run the query, save thumbnails, show them, stop. No
per-curl narration. Before asking for any `*_API_KEY`, grep
`~/.zshrc ~/.zshenv ~/.zprofile ~/.profile ~/.bashrc ~/.bash_profile
~/.env*` for `export <NAME>=`; if absent, ask the user to `export` it
themselves — never accept a pasted secret.

## Environment

Required:
- `USD_SEARCH_API_URL` — set by `/quickstart` or `/deploy-usdsearch`.
  If unset, redirect the user to `/quickstart` first.

Optional auth (mutually exclusive — pick whichever matches the deployment):
- `USD_SEARCH_API_TOKEN` — Bearer JWT or plain API key
- `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` — HTTP Basic

Routes — assume the unified API gateway is in front of every request.
Use the unversioned paths shown in the examples below: `/search_hybrid`,
`/images`, `/search/stats/...`. The Asset Graph Service and Info
Endpoint are internal interfaces; never address them directly.

**Auth header logic** (same as the previous skills):
- `USERNAME` + `PASSWORD` set → `Authorization: Basic $(echo -n "$U:$P" | base64)`
- `TOKEN` non-empty and not `x` → `Authorization: Bearer $TOKEN`
- Otherwise → no Authorization header (unauthenticated, e.g. simready)

## Determine input mode

Inspect `$ARGUMENTS` and any files the user referenced:

| Mode | Input | Endpoint body |
|---|---|---|
| **Text** | A short noun phrase ("yellow forklift") | `hybrid_text_query` + `vector_queries[query_type=text]` |
| **Image** | A local file path or asset URL | `image_similarity_search: ["data:image/jpeg;base64,…"]` |
| **Hybrid** | Both, or "more like this but red" | All three fields together |

If the user said "find similar to rank 4" and a search manifest
exists at `./search-results/*/manifest.json`, look up the local
thumbnail path from there — don't re-query.

## Build the request

Keep text queries SHORT (2-5 words). SigLIP2 is CLIP-style — concise
descriptions beat verbose ones.

**Pick `limit` based on query breadth.** The default is 20 — enough
for any specific query ("blue forklift", "tomato soup can", "Fanuc
m900ib280") and keeps validation work bounded. For broad single-class
category queries ("kitchenware", "robots", "warehouse panels",
"graspable objects") that span many variants, bump to 30 so subcategories
don't all get crowded out by the most prototypical variant in SigLIP2
rankings. Only raise to 100 when the user explicitly asks for an
exhaustive list ("find every robot", "all conveyor belts") — large
limits multiply context cost across validation turns.

**Text mode** (standard template):
```json
{
  "hybrid_text_query": "<2-5 word description>",
  "vector_queries": [{
    "field_name": "siglip2-embedding.embedding",
    "query_type": "text",
    "query": "<same description>"
  }],
  "file_extension_include": "usd*",
  "return_metadata": true,
  "return_usd_dimensions": true,
  "return_usd_properties": true,
  "return_vision_generated_metadata": true,
  "return_images": true,
  "limit": 20,
  "scoring_config": {
    "rrf_config": {"rank_constant": 60},
    "hybrid_text": {
      "enabled": true, "weight": 1.0, "cross_field_operator": "or",
      "fields": [
        {"field":"name","weight":2,"match_type":"fuzzy","wildcard":true},
        {"field":"path","weight":1,"match_type":"fuzzy","wildcard":true}
      ]
    },
    "vector_fields": {
      "siglip2-embedding.embedding": {
        "enabled": true, "weight": 1,
        "field_name": "siglip2-embedding.embedding", "dimension": 1536
      }
    }
  }
}
```

`__VISION_METADATA_FIELDS__` is a server-side placeholder that the API
expands to the live list of VLM-generated metadata fields at request
time (see `_get_vision_metadata_fields` in
`services/deepsearch_api/.../search_backend/main.py`). Keep it verbatim
in the request body. This mirrors the helm chart's default scoring
config at `helm/usdsearch/charts/ngsearch/values.yaml`.

`scoring_config` is mandatory on bare-API deployments — the stub
default returns `422 "Field siglip2-embedding.embedding not found in
scoring config"`.

**Image mode**: replace the text fields with
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
thumbnail with `curl … /images?asset_url=<url> | base64`.

**Hybrid mode**: include `hybrid_text_query`, `vector_queries`, AND
`image_similarity_search` in the same body.

## Optional filters

Apply when the user's request implies them:

- **Size**: `min_bbox_x/y/z`, `max_bbox_x/y/z`
- **Path scope**: `search_path` (e.g. `/NVIDIA/Assets/Vehicles/`)
- **Properties**: `filter_by_properties` (e.g. `class=vehicle,material=metal`)
- **Date**: `created_after`, `modified_after` (`YYYY-MM-DD`)
- **Dedup**: `deduplicate_by_hash: true`
- **File type**: `file_extension_include: "usd*"` (default)

Discover available USD properties with:
```bash
curl -s "${USD_SEARCH_API_URL}/search/stats/usd_properties?search_query=<term>"
```

## Execute and save thumbnails

Run the search, then fetch thumbnails for the top 5–10 hits via the
`/images` endpoint. Images are NEVER inlined — fetch each separately:

```bash
curl -s "${USD_SEARCH_API_URL}/images?asset_url=<source.base_key>" \
  --output "$DIR/0N_<sanitized-name>.jpg"
```

Save to a slug-named directory (idempotent across re-runs):

```bash
SLUG=$(printf '%s' "$Q" | tr '[:upper:]' '[:lower:]' \
       | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')
DIR="./search-results/$SLUG"
mkdir -p "$DIR"
```

Write a `manifest.json` with `name`, `url`/`base_key`, `rrf_score`,
local filename per rank. `/inspect-asset` and follow-on `/search`
calls consume it directly without re-querying.

Skip results where `hit.thumbnail_exists == false` — the field lives
at the **top level of each hit**, not inside `hit.source`. The
templates above set `return_images: true`, so the server populates the
field: `true` = renderable thumbnail available, `false` = no SigLIP2
embedding (so `/images` would 404). If a caller omits `return_images`
the field is `null` — fall back to fetching `/images` defensively
instead of pre-skipping.

Use `img_offset=0,1,2…` to grab alternate views of the same asset when
useful.

## Relevance validation (mandatory)

Every hit must be confirmed to match the query before it appears in
the output. Drop non-matches — do not pad the result list with
near-misses or "interesting" extras.

**Validate one hit at a time, one decision per turn.** Do NOT batch
multiple hits into a single response. Pick the next unresolved hit,
gather its captions / VLM verdict / thumbnail, commit a keep/drop
verdict, then move to the next. This keeps the chain of reasoning
auditable and lets later hits clarify the intent of the query before
you finalize earlier ones.

**Step 0 — Free server-side validation, if present.** Some
deployments auto-run their VLM validator and attach `is_match` inside
each hit's `vision_generated_metadata` block. If that field is
present: `is_match=true` → keep, `is_match=false` → drop, no further
checks on that hit. If the field is absent on every hit (e.g.
simready staging silently ignores it), fall through to Steps 1–3.

**Step 1 — Filter on pre-computed VLM captions.** With
`return_vision_generated_metadata: true` (default), each hit *may*
carry two free VLM-generated captions in its `source`:
- `plugin_rendering_to_vision_metadata_metadata_vlm_generated[0].value_text` —
  caption from a full USD render
- `plugin_thumbnail_to_vision_metadata_metadata_vlm_generated[0].value_text` —
  caption from the asset's thumbnail

These are populated at indexing time, so reading them costs nothing extra.
**Coverage is incomplete** — older or non-SimReady assets (e.g. many
`/Isaac/Props/*`, `/Isaac/Robots/*` USDs) often have neither field, and
sometimes only one of the two is present. Always check before reading:

```python
src = hit["source"]
render_caption = (src.get("plugin_rendering_to_vision_metadata_metadata_vlm_generated") or [{}])[0].get("value_text")
thumb_caption  = (src.get("plugin_thumbnail_to_vision_metadata_metadata_vlm_generated") or [{}])[0].get("value_text")
```

Decide per hit:
- **Both captions present and agree** that the asset matches → keep
  without thumbnail. Example: both say "Photorealistic red apple…" for
  query "apple" — keep.
- **Both captions present and agree it does NOT match** → drop without
  thumbnail. Example: both say "blue forklift" for query "yellow
  forklift" — drop.
- **Both present but disagree** on a load-bearing attribute (one says
  "red apple", the other "green apple") → unresolved, fall to Step 2.
- **Only one caption present** → treat it as a single (less reliable)
  vote; if it cleanly matches/rejects, accept it; if uncertain, fall
  to Step 2.
- **Neither caption present** → no VLM signal at all, fall to Step 2.

Skipping Step 1 is also fine for tiny result sets (≤5 hits) where
thumbnail inspection is cheap.

**Step 2 — Try the server's VLM validator on the ambiguous hits.**
Some deployments don't expose `/vlm_validate/*` at all. **Probe once
before looping** — a single POST with the first unresolved hit. If the
response status is anything other than `200`, skip Step 2 entirely for
the whole query and go to Step 3. Common signals to detect:
- HTTP `200` + JSON body → endpoint live, proceed to per-hit calls
- HTTP `503` + body `"VLM validation is not enabled on this server"` →
  endpoint disabled in this deployment
- HTTP `404` + nginx HTML (`"<html>...404 Not Found...</html>"`) → the
  gateway doesn't proxy `/vlm_validate/*` on this deployment (this is
  the case on simready staging)

Use `curl -w '%{http_code}'` or `-o /tmp/body -D /tmp/headers` to
inspect the status. Don't repeat the call N times if the first probe
came back non-200 — that's wasted tokens.

When live, POST each unresolved hit:

```bash
curl -s -X POST "${USD_SEARCH_API_URL}/vlm_validate/search_result" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER" \
  -d '{"query_text":"<query>","asset_url":"<source.base_key>"}'
```

Response shape: `{is_match, confidence, similarity_score, reasoning}`.
Keep only hits with `is_match=true`.

**Step 3 — Fallback to thumbnail inspection (most expensive).** Only
when the captions disagree AND the VLM validator is unavailable.
`codex exec` is text-only at the CLI surface, so the agent shells
out to a single recursive `codex exec` call that attaches every
unresolved thumbnail at once and returns a structured verdict per
image. Do this as **one batched call**, not one call per hit — a
recursive call per thumbnail multiplies latency and per-call warm-up
cost, and JSONL grep parsing of intermediate reasoning events is
fragile (escaped quotes inside `text`, multi-line content, reasoning
turns mixed with the final reply).

Write the schema once per run:

```bash
cat > /tmp/verdict.schema.json <<'JSON'
{
  "type": "object",
  "additionalProperties": false,
  "required": ["verdicts"],
  "properties": {
    "verdicts": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["filename", "match", "reason"],
        "properties": {
          "filename": {"type": "string"},
          "match":    {"type": "string", "enum": ["yes","no","partial"]},
          "reason":   {"type": "string"}
        }
      }
    }
  }
}
JSON
```

Then one call for the whole batch. **Pipe the prompt via stdin and
pass `-` as the positional arg.** This is not optional —
`-i FILE...` is variadic (clap `num_args=1..`) and will greedily
consume the positional `[PROMPT]` as another image path, after which
codex prints `Reading prompt from stdin...` and hangs forever:

```bash
PROMPT="For each attached image, decide whether it shows '<query>'.
Reply ONLY with JSON matching the provided schema.
Filenames in order: 00_<name>.jpg, 01_<name>.jpg, 02_<name>.jpg."

echo "$PROMPT" | codex exec --skip-git-repo-check \
  --dangerously-bypass-approvals-and-sandbox \
  --output-schema /tmp/verdict.schema.json \
  --output-last-message /tmp/verdicts.json \
  -i "$DIR/00_<name>.jpg" -i "$DIR/01_<name>.jpg" -i "$DIR/02_<name>.jpg" \
  -
jq -r '.verdicts[] | "\(.filename)\t\(.match)\t\(.reason)"' /tmp/verdicts.json
```

Why this shape, not the older per-hit `codex exec --json ... | grep`:
- **Prompt over stdin + trailing `-`** is the only form that
  reliably survives `-i FILE...`. Inline-positional prompts
  (`-i img.jpg "prompt..."`) hang. Tested locally on codex v0.133.
- `--output-schema` forces a strict JSON reply — no prose, no
  reasoning trace mixed in, no escaped-quote parsing surprises.
- `--output-last-message` writes just the final agent reply to a
  file. Parse with `jq`, never grep `--json` events.
- One call covers N thumbnails: shared warm-up, shared prompt, the
  model sees all candidates in one pass which also helps it
  calibrate "which of these is the best yellow forklift" rather
  than each in isolation.

Keep only hits whose verdict is `yes`. Drop `partial` and `no`.

**Be honest.** If rank 1 is a pure name-match but visually wrong
(e.g. `stencil_vehicles.usd` for "vehicle"), drop it. The user is
staring at the same thumbnails.

**Object queries must return objects, not scenes.** When the query
names a single object class — "anymal", "robot", "concrete floor
tile", "forklift" — drop hits whose thumbnails show a generic
warehouse / test / placeholder / room scene that merely *contains*
(or might contain) the queried object. Path/name signals: `scene*`,
`stage*`, `test*`, `warehouse*`, `room*`, `_layout`, `_environment`,
multi-object compositions. The user wants the object as an isolated
asset; scenes are noise even when the named object appears inside.
Only return scene-level results when the query itself is scene-shaped
("warehouse with anymals", "factory floor", "kitchen interior").

**Empty case.** If validation drops everything, return an empty
result list and tell the user explicitly:
*"No matching assets found on `${USD_SEARCH_API_URL}`."*
Don't substitute near-misses to avoid an empty answer.

If the top-N is all mismatched but the index plausibly has matches
further down, iterate before declaring empty — try a synonym, broaden
or narrow the phrase, or take the closest partial and re-run in
**image mode** against its thumbnail (Round 2 below).

## Iterative similarity (Round 2)

The strongest result for "find me more like this" is rarely the
first query — it's image similarity run on a **good intermediate
match**. Example flow:

1. Round 1: text search → 20 hits, rank 7 is the best visual match.
2. Fetch rank 7's thumbnail, base64-encode it.
3. Round 2: image-similarity search using that thumbnail.

Round 2 reliably surfaces assets that text search alone never finds.
Set `deduplicate_by_hash: true` to avoid the same asset appearing
multiple times under different paths.

## Present results

Show ONLY the validated matches. Compact list per match:
- thumbnail path (saved JPEG in `$DIR`) — the user can open the file;
  the agent cannot inline images in the chat surface
- asset URL / `base_key`
- `rrf_score` plus, if VLM validation ran, `similarity_score` and
  `confidence`
- one-line metadata (dimensions or key USD properties)
- how it was found (text / image / Round 2)

If the filtered list is empty, print one line:
*"No matching assets found on `${USD_SEARCH_API_URL}`."*
Stop there — no pointer list, no near-miss suggestions.

Otherwise, end with a short pointer list (not a question):
- `/inspect-asset` — deep-dive a single hit
- `/search-in-scene` — spatial / scene-graph queries
- `/search "<refined query>"` — iterate

## Important rules

- **Text queries: 2–5 words.** SigLIP2 is CLIP-style.
- **Always inline `scoring_config` in text/hybrid mode.** The stub
  default 422s on bare-API endpoints.
- **Fetch thumbnails via `/images` — they're never inlined.**
- **Validate before presenting.** Use `/vlm_validate/search_result`
  when available; otherwise inspect thumbnails. Return only matches.
  If nothing matches, say so explicitly and return an empty list.
- **One batched `codex exec` for Step 3, not one per hit.** Use
  `--output-schema` + `--output-last-message` + `jq`. Never grep
  JSONL for `"text":"..."` — escaped quotes and reasoning turns
  break it.
- **Codex prompt goes through stdin, not inline.** `-i FILE...` is
  variadic and eats the positional prompt; codex then waits on
  stdin and hangs. Always `echo "$PROMPT" | codex exec ... -i a -i b -`.
- **Network fetches as top-level `curl` calls.** In prefix-approved
  sandbox environments, compound shells like `while ...; do curl
  ...; done` may not match the approved `curl` rule and fail with
  DNS/host-resolution errors. Keep each fetch as its own `curl`
  line. If a batched form is unavoidable and thumbnail fetches
  fail that way, rerun the same fetch step with escalated
  permissions before treating any image as missing.
- **Round 2 image similarity** on the best Round 1 intermediate is
  the single biggest quality lever for "more like this".
- **Indirect credentials only.** Never accept pasted secrets.
- **Persist results** to `./search-results/<slug>/` with a manifest
  so follow-up skills can resume without re-querying.
