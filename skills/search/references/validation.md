# Relevance validation — escalation detail

SKILL.md covers the principle (prefer text signals, batch verdicts) and
Step 1 (pre-computed captions), which resolves most hits. Read this when
hits are **unresolved** — captions absent or disagreeing — or when you
need thumbnail inspection, plus the quality rules and the iterate/empty
handling.

Order of escalation: **Step 0 (free server verdict) → Step 1 (captions,
in SKILL.md) → Step 2 (VLM validator) → Step 3 (sub-agent thumbnails).**
Every step is text-only except Step 3, and Step 3 keeps images out of the
main context.

## Step 0 — Free server-side validation, if present

Some deployments auto-run their VLM validator and attach `is_match` inside
each hit's `vision_generated_metadata` block. If present: `is_match=true`
→ keep, `is_match=false` → drop, no further checks on that hit. If absent
on every hit (e.g. simready staging silently ignores it), fall through.

## Step 2 — Server VLM validator on the ambiguous hits

Some deployments don't expose `/vlm_validate/*` at all. **Probe once
before looping** — a single POST with the first unresolved hit. If the
status is anything other than `200`, skip Step 2 for the whole query and
go to Step 3. Signals:
- HTTP `200` + JSON body → live, proceed to per-hit calls
- HTTP `503` + `"VLM validation is not enabled on this server"` → disabled
- HTTP `404` + nginx HTML → gateway doesn't proxy it (the simready staging case)

Use `curl -w '%{http_code}'` or `-o /tmp/body -D /tmp/headers` to inspect
the status. Don't repeat the call if the first probe came back non-200.

When live, POST each unresolved hit:

```bash
curl -s -X POST "${USD_SEARCH_API_URL}/vlm_validate/search_result" \
  -H "Content-Type: application/json" \
  -H "$AUTH_HEADER" \
  -d '{"query_text":"<query>","asset_url":"<source.base_key>"}'
```

Response: `{is_match, confidence, similarity_score, reasoning}`. Keep only
`is_match=true`.

## Step 3 — Delegate thumbnail inspection to a sub-agent

Only when captions disagree AND the server VLM validator is unavailable.
Reading JPEGs directly into *this* conversation is the single largest
token sink — each image (~4K tokens) then rides in context and is re-read
on every later turn. Hand the visual check to a sub-agent whose context is
discarded afterwards.

Spawn ONE sub-agent for all unresolved hits via `Task`
(`subagent_type: general-purpose`). The saved thumbnails already live on
disk under `$DIR`, so the sub-agent only needs `Read` — no network. Prompt
template:

    Query: "<query>".
    Judge each thumbnail: does the asset match the query?
    Files (rank -> path):
      1  ./search-results/<slug>/01_<name>.jpg
      2  ./search-results/<slug>/02_<name>.jpg
      ...
    For each rank return one line, exactly:
      <rank> <keep|drop> — <what it is: object, colour, material>
    Keep only clear matches; drop partials and mismatches. If the
    query names a single object, drop thumbnails showing a generic
    scene (warehouse / room / test stage) that merely contains it,
    unless the query itself is scene-shaped. Return only those lines,
    nothing else. Do not fetch anything.

Only the verdict lines re-enter the main context — no JPEG ever does. This
still yields one decision per hit, just computed in a disposable context.
If your harness lets you pin a cheaper model (e.g. Haiku) for the
sub-agent, do so — thumbnail matching is a bounded task and the
context-isolation win applies regardless of model.

**Degenerate case:** if only one or two thumbnails are unresolved near the
end of a short run, a direct `Read` in the main context is fine — the
sub-agent's fixed startup overhead isn't worth it for a single image. When
you do read directly, issue all the `Read` calls in **one** response
rather than one per turn, and don't reflexively pull alternate views
(`img_offset` / a second `_v2` render) — fetch one only when the first
thumbnail is genuinely ambiguous. Every extra image read into this
conversation is re-read on every later turn.

## Quality rules

**Be honest.** If rank 1 is a pure name-match but visually wrong (e.g.
`stencil_vehicles.usd` for "vehicle"), drop it. The user is staring at the
same thumbnails.

**Object queries must return objects, not scenes.** When the query names a
single object class — "anymal", "robot", "concrete floor tile", "forklift"
— drop hits whose thumbnails show a generic warehouse / test / placeholder
/ room scene that merely *contains* (or might contain) the queried object.
Path/name signals: `scene*`, `stage*`, `test*`, `warehouse*`, `room*`,
`_layout`, `_environment`, multi-object compositions. The user wants the
object as an isolated asset. Only return scene-level results when the
query itself is scene-shaped ("warehouse with anymals", "factory floor",
"kitchen interior").

## Empty case & iterating

If validation drops everything, return an empty result list and tell the
user explicitly: *"No matching assets found on `${USD_SEARCH_API_URL}`."*
Don't substitute near-misses to avoid an empty answer.

If the top-N is all mismatched but the index plausibly has matches further
down, iterate before declaring empty — try a synonym, broaden or narrow
the phrase, or take the closest partial and re-run in image mode against
its thumbnail (Round 2 below).

## Iterative similarity (Round 2)

The strongest result for "find me more like this" is rarely the first
query — it's image similarity run on a **good intermediate match**:

1. Round 1: text search → 20 hits, rank 7 is the best visual match.
2. Fetch rank 7's thumbnail, base64-encode it.
3. Round 2: image-similarity search using that thumbnail (see image mode
   in `references/request-templates.md`).

Round 2 reliably surfaces assets that text search alone never finds. Set
`deduplicate_by_hash: true` to avoid the same asset under different paths.
This is the single biggest quality lever for "more like this".
