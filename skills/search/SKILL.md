---
name: search
license: Apache-2.0
version: 1.0.0
description: |
  Search USD Search for 3D assets. One skill, three input modes:
  text query, reference image, or both combined. Hits
  POST /search_hybrid + GET /images. Iterates on intermediate matches
  for visual-similarity refinement when the user wants "more like this".
  Use when: "search assets", "find a 3D model", "find a USD",
  "find similar", "more like this", "visually similar".
triggers:
  - search
  - search assets
  - find an asset
  - find a 3d model
  - find a usd
  - find similar
  - more like this
  - visually similar
  - similar asset
allowed-tools: Bash, Read, Task
effort: low
---

# /search — query USD Search

Stage 3 → 4 → 5 of the `/quickstart` journey: take the user's
**text and/or image** input, run hybrid search against the USD Search
API, and present ranked thumbnails.

**Be terse.** Run the query, save thumbnails, show them, stop. No
per-curl narration. Before asking for any `*_API_KEY`, grep
`~/.zshrc ~/.zshenv ~/.zprofile ~/.profile ~/.bashrc ~/.bash_profile
~/.env*` for `export <NAME>=`; if absent, ask the user to `export` it
themselves — never accept a pasted secret.

**Progressive detail.** This file is the happy path. Read a reference
only when you hit its case (each is in this skill's `references/` dir —
its absolute path is shown in the skill-load header above, call it
`$SKILL`):
- `references/request-templates.md` — image/hybrid bodies, `scoring_config`
  rationale, `limit` tuning, merging parsed filters.
- `references/filters.md` — queries with constraints (file types, dates,
  sizes, physics, tags): `llm_parse/query` + the filter catalog.
- `references/validation.md` — escalation past captions: server VLM
  validator, the thumbnail sub-agent, scene-vs-object rules, iterate/empty.

## Environment

Tooling: this skill shells out to `curl` and `python3` only (both
standard; `python3` builds the request body and parses responses). No
`jq` or other extra dependency.

Required:
- `USD_SEARCH_API_URL` — set by `/quickstart` or `/deploy-usdsearch`.
  If unset, redirect the user to `/quickstart` first.

Optional auth (mutually exclusive):
- `USD_SEARCH_API_TOKEN` — Bearer JWT or plain API key
- `USD_SEARCH_API_USERNAME` + `USD_SEARCH_API_PASSWORD` — HTTP Basic

Assume the unified API gateway is in front of every request; use the
unversioned paths (`/search_hybrid`, `/images`, `/search/stats/...`). The
Asset Graph Service and Info Endpoint are internal — never address them.

**Auth header:**
- `USERNAME` + `PASSWORD` → `Authorization: Basic $(echo -n "$U:$P" | base64)`
- `TOKEN` non-empty and not `x` → `Authorization: Bearer $TOKEN`
- Otherwise → no Authorization header (unauthenticated, e.g. simready)

## Determine input mode

| Mode | Input | Body |
|---|---|---|
| **Text** | A short noun phrase ("yellow forklift") | `hybrid_text_query` + `vector_queries[query_type=text]` |
| **Image** | A local file path or asset URL | `image_similarity_search: ["data:image/jpeg;base64,…"]` |
| **Hybrid** | Both, or "more like this but red" | All three fields together |

If the user said "find similar to rank 4" and a manifest exists at
`./search-results/*/manifest.json`, look up the local thumbnail there —
don't re-query.

## Build & run the request (text mode)

Keep text queries SHORT (2–5 words) — SigLIP2 is CLIP-style; concise
descriptions beat verbose ones. Default `limit` is 20; see
`references/request-templates.md` for when to bump it.

The full request body (with the mandatory `scoring_config`) lives at
`$SKILL/references/search-body.json` with `__QUERY__` placeholders — fill
it with `python3` and POST, so the boilerplate never enters your context:

```bash
Q="blue forklift"                       # the 2–5 word query
SLUG=$(printf '%s' "$Q" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')
DIR="./search-results/$SLUG"; mkdir -p "$DIR"
python3 -c 'import json,sys; d=json.load(open(sys.argv[2])); d["hybrid_text_query"]=d["vector_queries"][0]["query"]=sys.argv[1]; print(json.dumps(d))' \
  "$Q" "$SKILL/references/search-body.json" > /tmp/body.json
curl -s -X POST "$USD_SEARCH_API_URL/search_hybrid" \
  -H "Content-Type: application/json" $AUTH_HEADER \
  -d @/tmp/body.json > "$DIR/response.json"
```

(For broad category queries add `d["limit"]=30` in the python before the
`print`.)

- **Filter-heavy** query (constraints in the text) → parse first; read
  `references/filters.md`.
- **Image / hybrid** mode → read `references/request-templates.md`.

## Save thumbnails

Parse `$DIR/response.json` **once**: in a single script pull the fields
you need for every hit — rank, `name`, `base_key`, top-level
`thumbnail_exists`, the two VLM captions, scores — into one compact
summary. Don't re-open the JSON across turns to print keys, then hits,
then fields one at a time; each poke is a turn whose output rides in
context for the rest of the run.

Fetch thumbnails for the top 5–10 hits (images are NEVER inlined):

```bash
curl -s "${USD_SEARCH_API_URL}/images?asset_url=<source.base_key>" \
  --output "$DIR/0N_<sanitized-name>.jpg"
```

Write a `manifest.json` (`name`, `url`/`base_key`, `rrf_score`, local
filename per rank) so `/inspect-asset` and follow-on `/search` calls
resume without re-querying.

Skip hits with top-level `hit.thumbnail_exists == false` (no SigLIP2
embedding → `/images` 404s). If a caller omits `return_images` the field
is `null` — fetch `/images` defensively instead of pre-skipping.

## Relevance validation (mandatory)

Every hit must be confirmed to match the query before it appears in the
output. Drop non-matches — don't pad the list with near-misses.

**Prefer text-only signals; escalate to thumbnails only as a last
resort.** Cost is dominated by turns and by images pulled into context (a
thumbnail read early is re-read every later turn — the single largest
avoidable cost). Resolve as many hits as possible without loading a JPEG.

**Batch the work — don't spend one turn per hit.** Gather the evidence for
all unresolved hits, then emit the keep/drop verdicts together, reasoning
in rank order in one response. Thumbnail inspection is delegated to one
sub-agent that judges all unresolved hits at once — no JPEG enters this
conversation.

**Step 1 — pre-computed VLM captions (the common resolver).** With
`return_vision_generated_metadata: true` (default) each hit *may* carry two
free captions in its `source` (populated at indexing time — reading them
costs nothing):

```python
src = hit["source"]
render_caption = (src.get("plugin_rendering_to_vision_metadata_metadata_vlm_generated") or [{}])[0].get("value_text")
thumb_caption  = (src.get("plugin_thumbnail_to_vision_metadata_metadata_vlm_generated") or [{}])[0].get("value_text")
```

- **Both present & agree it matches** → keep without thumbnail.
- **Both present & agree it does NOT** → drop without thumbnail.
- **Disagree, only one present, or neither** → unresolved; escalate.

**Unresolved hits → read `references/validation.md`** and follow its
escalation (Step 0 server `is_match` → Step 2 VLM validator → Step 3
thumbnail sub-agent), plus its quality rules and iterate/empty handling.
Two rules that always apply, even on captions alone:
- **Objects, not scenes.** For a single-object query ("anymal", "forklift")
  drop hits whose thumbnail is a generic warehouse/room/test scene that
  merely *contains* it, unless the query is scene-shaped.
- **Empty is a valid answer.** If validation drops everything, say
  *"No matching assets found on `${USD_SEARCH_API_URL}`."* — don't
  substitute near-misses. (First consider iterating: synonym, or Round 2
  image-similarity on the best partial — see `references/validation.md`.)

## Present results

Show ONLY the validated matches. Compact list per match:
- thumbnail, asset URL / `base_key`
- `rrf_score` (+ `similarity_score`, `confidence` if VLM validation ran)
- one-line metadata (dimensions or key USD properties)
- how it was found (text / image / Round 2)

If empty, print one line: *"No matching assets found on
`${USD_SEARCH_API_URL}`."* and stop — no pointer list.

Otherwise end with a short pointer list (not a question):
- `/inspect-asset <asset_url>` — thumbnails, scene summary, dependencies
- `/search-in-scene <scene_url> "<spatial query>"` — spatial / prim filters
- `/search "<refined query>"` — iterate

## Important rules

- **Text queries: 2–5 words.** SigLIP2 is CLIP-style.
- **Build the body from `$SKILL/references/search-body.json`** (jq-fill) —
  the `scoring_config` is mandatory (bare-API stubs 422 without it) and
  stays out of your context this way.
- **Parse filter-heavy queries first** (`references/filters.md`); on any
  non-200 from `/llm_parse/query` fall back to plain hybrid search.
- **Fetch thumbnails via `/images` — never inlined.**
- **Validate before presenting.** Text signals first, thumbnails last
  (via the sub-agent). Return only matches; if none, say so.
- **Indirect credentials only.** Never accept pasted secrets.
- **Persist results** to `./search-results/<slug>/` with a manifest.
