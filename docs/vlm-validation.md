<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# VLM Result Validation

A Vision Language Model judges each hit's thumbnails against the query and
attaches a verdict as `query_relevance`: `is_match` (bool), `confidence` (0-1),
`similarity_score` (float 0-100, the one relevance number and the `rerank`
sort key), `reasoning`. The **method** (`USDSEARCH_VISION_VALIDATION_METHOD`)
computes the verdict; the **mode** (`USDSEARCH_VISION_VALIDATION_MODE`) decides
what the server does with it. They are independent.

## Validation methods: generative, log-prob

| Method | How | Cost | Requires |
|---|---|---|---|
| `generative` (default) | The VLM generates the structured JSON verdict. | One generation per verdict. | Any OpenAI-compatible VLM. |
| `logprob` | Asks the one-word Yes/No question below; reads `P(Yes)` vs `P(No)` from the first-token log-probs. | One scored token per verdict. | A provider returning `top_logprobs` (e.g. self-hosted vLLM). |

| Field | `generative` | `logprob` |
|---|---|---|
| `similarity_score` | generated whole number | `P(Yes) x 100`, unrounded |
| `is_match` | generated | `P(Yes) > 0.5` |
| `confidence` | generated | `P(Yes)` |
| `reasoning` | generated sentence | `P(Yes)=...` |

A generated `similarity_score` outside 0-100 is a parse failure for that hit
(fail-open). Both methods use the shared LLM connection and `model`.

**Log-prob prompt.** The whole user text, no system prompt (the generative
method keeps
[`validation_prompt.txt`](../packages/llm-client/llm_client/validation/validation_prompt.txt)):

> You are a visual relevance judge for a 3D-asset search. Query: "{query}". Does
> the rendered asset match the query? Answer with exactly one word: Yes or No.

Image queries name the query image (and any text query); the query image is
sent first. An image query with a text query and one asset view (the default
view budget) asks instead (`..._LOGPROB_IMAGE_TEXT_QUERY`, default `true`):

> You are a visual relevance judge for a 3D-asset search. Query: "{query}",
> together with the first image, which shows what the user is looking for. The
> other image shows a candidate asset. Does the candidate asset match the
> query? Answer with exactly one word: Yes or No.

`false` keeps the caption clause ("The first image is the query image and the
text query is …; the remaining images are rendered views of one asset"), which
lets the model judge the query image itself against the text. Measured on
Qwen3.6-35B-A3B-FP8 with 261 image + text queries (robot and IKEA product
names, descriptive queries, real search telemetry; 2,047 candidates), labelled
by the same judge's text-only and image-only verdicts: the question passed
99 % of the candidates that should pass (the caption clause 96 %) and failed
86 % of those that should fail (72 %); unrelated assets passed 1 of 255 times
(15). It is stricter when the words fit but the look differs (78 % pass, 84 %).
Several views keep the caption clause (unevaluated: the engines measured take
at most two images). Part of the cache identity when on: switching it off
gives back the verdicts cached before it.

**Domain context.** `..._DOMAIN_CONTEXT_FILEPATH` is always rendered into the
generative system prompt. The judge ignores it unless
`..._LOGPROB_DOMAIN_CONTEXT=true`, which sends it alone as the system prompt
(unevaluated, re-prefilled on every verdict, changes the cache identity).

**Asset facts.** `..._LOGPROB_ASSET_FACTS` lists the facts a text query's
judge reads between the query and the question, each from the request field
of the same name: `path` (the asset's file path, its last
`..._LOGPROB_ASSET_PATH_MAX_CHARS` = 300 characters):
`The candidate asset's file is "Robots/Unitree/H2/H2.usda".`, and
`vlm_metadata_caption` (its vision caption, the first
`..._LOGPROB_ASSET_CAPTION_MAX_CHARS` = 200 characters):
`Catalog description: "…".`. Unset (the default), an image query, or a
request without the facts judges the rendered views alone, so a deployment
whose file names mislead leaves it unset. `..._LOGPROB_ASSET_PATH_ROOTS`
lists regexes for a path's content root: the path fact keeps what follows the
first match, else the whole path. Both are JSON lists, e.g.:

```bash
USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_FACTS='["path", "vlm_metadata_caption"]'
# Isaac content (any release) and Hugging Face datasets (any revision):
USDSEARCH_VISION_VALIDATION_LOGPROB_ASSET_PATH_ROOTS='["/Isaac/[^/]+/Isaac/", "(?i)^(?:[a-z][a-z0-9+.-]*://)?huggingface\\.co/datasets/[^/]+/[^/]+/(?:(?:resolve|blob)/[^/]+/)?"]'
```

Evaluated in SimReady Central (2026-10-07): on 67 labelled queries nDCG@10
went from 0.78 to 0.92 with the path, and a model name such as "Unitree H2"
ranks its own asset first; the caption is ranking-neutral and lifts precision
among confident matches (76 → 80 %). Changes the cache identity.

**Abstain.** Yes/No mass below `logprob_cover_min` yields no verdict
(fail-open, like a timeout). `..._LOGPROB_ABSTAIN_AS_NO=true` treats it as
`is_match=false`.

| Setting | Env var | Default | Helm (`validation.`) |
|---|---|---|---|
| Method | `..._METHOD` | `generative` | `method` |
| Judge domain context | `..._LOGPROB_DOMAIN_CONTEXT` | `false` | `logprob.domain_context` |
| Image + text question (one view) | `..._LOGPROB_IMAGE_TEXT_QUERY` | `true` | `logprob.image_text_query` |
| Asset facts (text queries) | `..._LOGPROB_ASSET_FACTS` | unset (JSON list of `path`, `vlm_metadata_caption`) | `logprob.asset_facts` |
| Path content roots | `..._LOGPROB_ASSET_PATH_ROOTS` | unset (JSON list of regexes) | `logprob.asset_path_roots` |
| Path / caption fact length | `..._LOGPROB_ASSET_PATH_MAX_CHARS` / `..._CAPTION_MAX_CHARS` | `300` / `200` | `logprob.asset_path_max_chars` / `asset_caption_max_chars` |
| Abstain floor | `..._LOGPROB_COVER_MIN` | `0.2` | `logprob.cover_min` |
| Abstain as no-match | `..._LOGPROB_ABSTAIN_AS_NO` | `false` | `logprob.abstain_as_no` |
| Top-logprobs window | `..._LOGPROB_TOP_LOGPROBS` | `20` (max) | `logprob.top_logprobs` |
| Judge token cap | `..._LOGPROB_MAX_TOKENS` | `6` | `logprob.max_tokens` |
| Yes / No tokens | `..._LOGPROB_YES_TOKENS` / `..._LOGPROB_NO_TOKENS` | `["yes","y","true"]` / `["no","n","false"]` | env only |

## Validation modes: filter, rerank, annotate

| Mode | Effect |
|---|---|
| `filter` (default) | Drops hits with `is_match=false`. May return fewer than `limit` (no backfill); `total` unchanged. |
| `rerank` | Keeps every hit, sorts the page by `similarity_score` (ties keep retrieval order). |
| `annotate` | Attaches verdicts only; order and ranks unchanged. |

```
retrieval order:   A(score 80)   B(score 20)   C(no verdict)   D(score 95)

filter   ->  A  C  D
rerank   ->  D  A  C  B   (C keeps its slot)
annotate ->  A  B  C  D
```

A hit without a verdict (timeout, parse error, missing thumbnail) is never
demoted or dropped. `filter` and `rerank` renumber `metadata.rrf_rank`;
`rrf_score` keeps the retrieval score.

### `validate_results=true` is single-page

It judges the returned page only. Combined with a non-zero `offset` or a
`cursor` it returns `400`; a validated response never carries `next_cursor`.

**Who validates where.** One-page API and agent callers use
`validate_results=true`. Scrolling clients (the Explorer, SimReady Central) page
with `validate_results=false`, validate each hit via
`POST /vlm_validate/search_result` and reorder by `similarity_score` client-side
(infinite scroll with client-side reordering, decided 2026-09-15). Same verdict,
prompt and view on both paths.

## Where it runs

| Path | Trigger | Behavior |
|---|---|---|
| Inline with search | `validate_results=true` on [`POST /search_hybrid`](../services/deepsearch_api/deepsearch_api/routers_v3/search_v3.py) | Judges every hit of the page (a whitespace-only text query skips validation); bounded by `max_concurrent`. |
| Per asset | `POST /vlm_validate/search_result` | Judges one asset by `image_keys` (fast path), `asset_url` or `images`. Returns the active `model` so clients can cache per model. |
| Per page | `POST /vlm_validate/search_result_batch` | Judges up to 100 results in one request: `items` take the per-asset fields plus an `id`, with the same verdicts and cache. `stream` (default `true`) answers NDJSON as each lands — `{id, verdict}` or `{id, error}`, a blank heartbeat, `{fatal, error_type, retryable}` when the model is unreachable, `{done: {completed, errored}}` last; `false` answers one JSON body `{results, completed, errored}`. |

`images` is a list of raw base64 images (bare or `data:image/...;base64,`
URLs), judged with no index lookup (and shrunk like any other image when
`image_max_px` is set). Mutually exclusive with `asset_url` / `image_key` /
`image_keys` (`422`). The view budget applies; verdicts are cached by image
hash.

Prompt and output schema:
[`validation_fields.yaml`](../packages/llm-client/llm_client/validation/validation_fields.yaml).
A custom schema (`..._YAML_FILEPATH`) must keep the four verdict fields.

## Server configuration

Env prefix `USDSEARCH_VISION_VALIDATION_`
([`validation/config.py`](../services/deepsearch_api/deepsearch_api/validation/config.py));
LLM connection via `USDSEARCH_LLM_API_KEY` / `USDSEARCH_LLM_BASE_URL`
([models-and-config.md](models-and-config.md)).

| Setting | Env var | Default | Notes / Helm (`validation.`) |
|---|---|---|---|
| Enabled | `..._ENABLED` | `true` (code); `false` in the quickstart base stack | vlm-plugins overlay re-enables; `enabled` |
| Mode | `..._MODE` | `filter` | `mode` |
| Views per verdict | `..._MAX_IMAGES_PER_VALIDATION` | 1 | More than one view measured worse; >8 logs a warning. `max_images_per_validation` |
| Max image edge | `..._IMAGE_MAX_PX` | 0 (off) | Longest edge of the query image and every asset view sent to the VLM; shrink-only LANCZOS, aspect kept. 0 sends the stored size (the 1024-px thumbnail); 448 is the evaluated view. Part of the cache identity when > 0. `image_max_px` |
| Model | `..._MODEL` | `gcp/google/gemini-3.1-flash-lite` | `model` |
| Concurrency | `..._MAX_CONCURRENT` | 50 | One semaphore per API process. `max_concurrent_requests` |
| Per-verdict deadline | `..._TIMEOUT_SECONDS` | 30 | Counted from queueing, so it includes waiting for a slot; a late hit gets no verdict. |
| Retries | `..._MAX_TRIES` | 1 | Set `2` for self-hosted vLLM (5 s idle keep-alive; one try turns a stale connection into a whole-search 503). Part of the cache identity. `max_tries` |
| Domain context | `..._DOMAIN_CONTEXT_FILEPATH` | none | Helm ships a strict 3D-asset context in `domain_context`. |

## Server-side verdict cache

Key = fingerprint of the full validation config (model, sampling, method,
prompts, schema, endpoint) + query + asset image identity. Any config change
invalidates old verdicts; `mode`, concurrency and view budget are not part of
it. `image_max_px` joins the fingerprint only when set (> 0): turning it on or
changing it re-warms the cache, while leaving it at 0 keeps verdicts cached
before the setting existed.

Rows carry a format marker (`v: 2`). Unmarked rows (integer `similarity_score`)
still load; under `logprob` they are re-judged once so a rounded value never
sorts next to a float (the rounded verdict is served if the re-judge fails).
Interim rows with a 0-1 `score` load as `similarity_score = score x 100`.

- **L1** in-process LRU, always on; coalesces duplicate in-flight hits.
- **L2** Redis, opt-in; shared DB 0, prefix `usdsearch:vlmval:v1`
  ([Redis DB map](development.md#redis-logical-database-allocation)); approximate
  LRU cap; outage degrades to L1.

Only completed verdicts are cached; failures retry next request.

| Setting | Env var | Default | Helm (`validation.`) |
|---|---|---|---|
| L1 size | `USDSEARCH_VISION_VALIDATION_CACHE_SIZE` | 100000 (~256 MB); `0` disables | |
| L2 connection | `REDIS_URL` | unset = off | |
| L2 enabled | `..._CACHE_ENABLED` | `true` (needs `REDIS_URL`) | `cache.enabled` |
| L2 TTL | `..._CACHE_TTL_SECONDS` | none | `cache.ttl_seconds` |
| L2 max entries | `..._CACHE_MAX_ENTRIES` | 1000000 (~2 GB); `0` unbounded | `cache.max_entries` |

Metric: `vlm_validation_cache_events_total{outcome=l1_hit|l2_hit|miss}`.

## Explorer behavior

- Results render first; per-hit `POST /vlm_validate/search_result` follows
  ([`useAsyncValidation.js`](../services/explorer/src/hooks/useAsyncValidation.js)).
  The badge shows `similarity_score` rounded.
- Client cache: 24 h, keyed by (query, hit, model).
- "Only VLM-validated" toggle (Display Options) hides rejected cards; off by default.
- Build-time knobs ([`config.jsx`](../services/explorer/src/config.jsx)):
  `REACT_APP_VALIDATION_MAX_CONCURRENT` (8), `..._MAX_RETRIES` (3),
  `..._RETRY_DELAY_MS` (5000), `..._TIMEOUT_MS` (30000).

## Cost and latency

- One VLM call per judged hit, throttled to `max_concurrent`: about
  `ceil(N / max_concurrent) x per-call latency` added to an inline search.
- Verdicts see thumbnails only; they are a relevance signal, not a quality audit.
- VLM unreachable: 503; the Explorer shows a banner and keeps unvalidated results.

One L40S, vLLM 0.28.0, Qwen3.6-35B-A3B-FP8, `logprob`, 512 px images,
concurrency 24, nothing cached:

| Judge prompt | Verdicts/s | 50 verdicts | 150 verdicts |
|---|---|---|---|
| Question alone (shipped) | 42.9 | 1.46 s (p95) | 3.69 s |
| Question + generative system prompt (~700 tokens; what `logprob.domain_context: true` costs) | 18.3 | 2.95 s | 8.41 s |

The long prompt costs 2.4x at quality parity: the hybrid GatedDeltaNet model
does not prefix-cache a system prompt, so each verdict is prefill-bound.

The evaluated production view is 448 px (`image_max_px: 448`), so the 512 px
figures above are an upper bound. Left at 0, the validator sends the stored
1024-px thumbnail: about 1,077 prompt tokens per verdict on Qwen3.6, against
about 250 at 448 px.

## Error reporting

Validation failures return HTTP 503 with a structured body:

```json
{"detail": {"error_type": "configuration", "message": "...Logprobs is not supported for this model...", "model": "...", "retryable": false}}
```

- `error_type`: `configuration` for a permanent provider 4xx (`retryable: false`),
  `unreachable` for a transient network/5xx outage (`retryable: true`).
- `message` is the provider's error text (also logged).
- Inline `validate_results=true` returns the same 503; re-request without
  validation for unvalidated results.
- `method=logprob` runs a boot probe: it logs one error if the model rejects
  `logprobs` or returns no readable Yes/No mass (typical causes: raw instead of
  processed log-probs, or a preamble under a too-small token cap).

The Explorer shows `message` in its "VLM validation unavailable" banner; on a
non-retryable error pending hits become "unavailable".

## Measured quality

Evaluated on a frozen set of real production queries with judge-labeled top-10
slots. The query set and labels are unpublished, so no figures here. Findings:

- The VLM stage (`rerank`, `logprob`, float `similarity_score`, one view) is the
  largest gain over hybrid retrieval order, ahead of engine choice.
- Multiple views (2, 4, 8 or 2x2 sheets) hurt.
- Rounding `P(Yes) x 100` was the only resolution loss, hence the float.
- The short question matches the long prompt at 2.4x less GPU time.

Numbers, setup and rejected alternatives: internal decision record
`docs/internal/vlm-validation-findings-2026-09.md` (not in the public mirror).

### Recommended production configuration: Qwen log-prob rerank

Code defaults are unchanged; opting in is a deployment decision:

```bash
USDSEARCH_VISION_VALIDATION_ENABLED=true
USDSEARCH_VISION_VALIDATION_MODE=rerank
USDSEARCH_VISION_VALIDATION_METHOD=logprob
USDSEARCH_VISION_VALIDATION_LOGPROB_DOMAIN_CONTEXT=false
USDSEARCH_VISION_VALIDATION_MAX_IMAGES_PER_VALIDATION=1
USDSEARCH_VISION_VALIDATION_IMAGE_MAX_PX=448             # the evaluated view
USDSEARCH_VISION_VALIDATION_MAX_TRIES=2                  # vLLM idle keep-alive; 1 try = whole-search 503s
USDSEARCH_VISION_VALIDATION_MODEL=reranker               # served alias of Qwen3.6-35B-A3B-FP8
USDSEARCH_VISION_VALIDATION_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":false}}'
USDSEARCH_LLM_BASE_URL=<vLLM OpenAI-compatible base URL>
```

Helm: `validation.{mode,method,max_images_per_validation,image_max_px,max_tries,model,extra_body}`
and `validation.provider.base_url`; leave `logprob.*` at defaults. Set
`MAX_TRIES=2` and `IMAGE_MAX_PX=448` before the Redis cache warms (both are
part of the cache identity). The engine must return `top_logprobs` with
thinking disabled (the `extra_body` above; otherwise every verdict abstains).

Using validation as a relevance judge in ranking experiments:
[search research playbook](search_research_playbook.md).
