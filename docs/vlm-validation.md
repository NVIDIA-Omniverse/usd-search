<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# VLM Result Validation

A Vision Language Model double-checks search results against the query: each
hit's thumbnails are shown to the VLM, which returns a structured verdict —
`is_match` (bool), `confidence` (0–1), `similarity_score` (0–100), and a
one-sentence `reasoning`. The verdict is attached to the hit as
`query_relevance`; **nothing is deleted or re-ordered server-side**. Clients
decide what to do with it: the Explorer partitions results into
*Validated* / *Lower relevance* sections (a reranking signal — the lower-relevance
cards stay visible unless the "Only VLM-validated" toggle hides them).

## Where it runs

| Path | Trigger | Behavior |
|---|---|---|
| Batch, inline with search | `validate_results=true` on [`POST /search_hybrid`](../services/deepsearch_api/deepsearch_api/routers_v3/search_v3.py) | Validates every hit in the response; bounded by `max_concurrent`. |
| Per asset, on demand | `POST /vlm_validate/search_result` | Validates one asset (by `image_keys` — fast path — or `asset_url`); used by the Explorer to validate progressively as results render. Returns the active `model` identifier so clients can cache verdicts per model. |

The validation prompt and output schema live in
[`validation_fields.yaml`](../packages/llm-client/llm_client/validation/validation_fields.yaml)
(llm-client); strictness is shaped by the deployment's *domain context* (see below).

## Server configuration

Env prefix `USDSEARCH_VISION_VALIDATION_` ([`validation/config.py`](../services/deepsearch_api/deepsearch_api/validation/config.py)).
The model runs on the shared LLM connection (`USDSEARCH_LLM_API_KEY` /
`USDSEARCH_LLM_BASE_URL` — see [models-and-config.md](models-and-config.md)).

| Setting | Env var | Default | Notes |
|---|---|---|---|
| Enabled | `..._ENABLED` | `true` (code) / `false` in the quickstart base stack | The vlm-plugins compose overlay re-enables it; helm: `ngsearch.microservices.search_rest_api.validation.enabled`. |
| Model | `..._MODEL` | `gcp/google/gemini-3.5-flash` | helm: `validation.model`. |
| Concurrency | `..._MAX_CONCURRENT` | 10 | One semaphore per API process, shared across all in-flight validations. helm: `validation.max_concurrent_requests`. |
| Per-call timeout | `..._TIMEOUT_SECONDS` | 30 | A timed-out hit gets no verdict; the batch continues. |
| Retries | `..._MAX_TRIES` | 1 | No retries by default. |
| Domain context | `..._DOMAIN_CONTEXT_FILEPATH` | none | Free-text strictness/context instructions; helm ships a strict 3D-asset context in `validation.domain_context`. |

## Explorer behavior

- Results render immediately; validation happens **asynchronously after
  render** via per-hit `POST /vlm_validate/search_result` calls
  ([`useAsyncValidation.js`](../services/explorer/src/hooks/useAsyncValidation.js)).
- Verdicts are cached client-side for 24h keyed by (query, hit, model), so
  re-running a search doesn't re-pay the VLM cost.
- The **"Only VLM-validated"** toggle (Display Options drawer) hides rejected
  cards; off by default.
- Client knobs (CRA build-time env, [`config.jsx`](../services/explorer/src/config.jsx)):
  `REACT_APP_VALIDATION_MAX_CONCURRENT` (default 8),
  `REACT_APP_VALIDATION_MAX_RETRIES` (3),
  `REACT_APP_VALIDATION_RETRY_DELAY_MS` (5000),
  `REACT_APP_VALIDATION_TIMEOUT_MS` (30000).

## Cost & latency considerations

- Validation costs **one VLM call per result** (up to 8 thumbnails attached).
  A `limit=50` search with `validate_results=true` is 50 VLM calls, throttled
  to `max_concurrent`; expect roughly `ceil(N / max_concurrent) ×
  per-call-latency` added to the response when batch-validating inline.
- For interactive use prefer the Explorer's pattern: return the unvalidated
  results immediately and validate per-hit in the background.
- Validation only sees thumbnails — geometry/rig/material quality beyond what
  renders in the views is invisible to it. Treat verdicts as a relevance
  signal, not an asset-quality audit (the indexed `is_high_quality` /
  `has_issues` metadata flags cover visual quality).
- When the VLM endpoint is unreachable the endpoints return 503; the Explorer
  shows a banner and degrades to unvalidated results.

For using validation as a relevance judge in ranking experiments, see the
[search research playbook](search_research_playbook.md).
