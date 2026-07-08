# Search Research Playbook

How to run retrieval experiments against USD Search and evaluate ranking
changes without fooling yourself. This is the search-specific companion to the
generic deep-research tooling: it tells you **what to vary, what to hold
fixed, and how to score the result**.

## 1. System map — what actually produces a ranking

A `/search_hybrid` request fans out into parallel OpenSearch "legs", fused
client-side with weighted Reciprocal Rank Fusion (RRF):

| Leg | Signal | Built in |
|---|---|---|
| `hybrid` (text) | BM25 over names, paths, tags, USD properties, VLM metadata — one `bool/should` of per-field match + wildcard clauses | `_build_hybrid_text_query`, [`search_backend/main.py`](../services/deepsearch_api/deepsearch_api/search_backend/main.py) |
| `text_to_vector` / `image_similarity` / `vector_N` | SigLIP2 cosine similarity against multi-view thumbnail embeddings (best view wins, `score_mode: max`) | `_build_vector_queries`, same file |

Fusion: `rrf_score = Σ_legs weight × 1/(rank_in_leg + k)`, `k = rank_constant`
(default 60). All knobs live in `ScoringConfig`
([`search_backend/models.py`](../services/deepsearch_api/deepsearch_api/search_backend/models.py)):
per-field text weights, per-leg weights, `rank_constant`, `window_size`.

**The single most useful property for experiments**: `scoring_config` is a
**per-request body field**. You can A/B any ranking configuration against a
live deployment without redeploying anything — same index, same embeddings,
two request bodies.

Natural-language queries add a pre-step, not a ranking change:
`POST /llm_parse/query` extracts filters + a `semantic_query`
([`llm_parse/`](../services/deepsearch_api/deepsearch_api/llm_parse/)); the
mapped params feed the same `/search_hybrid` pipeline.

## 2. Comparing embeddings

The vector legs are only as good as the embedding model
([`services/siglip2-triton`](../services/siglip2-triton/) serves it;
[`packages/siglip2-triton-client`](../packages/siglip2-triton-client/)
consumes it). When comparing embedding variants:

- **Reindex per variant.** Query-side and index-side embeddings must come from
  the same model — you cannot hot-swap the text tower only. Stand up one index
  per variant (`opensearch_index_name` is per-deployment config) and crawl the
  same corpus into each.
- **Compare both retrieval modes**: text→thumbnail (cross-modal, what users
  type) and image→image (`image_similarity_search`, "more like this"). Models
  rank differently on the two; report them separately.
- **Hold the text leg fixed** (or disable it: `hybrid_text.enabled=false`) so
  you measure the embedding, not the fusion.
- Known CLIP-family weaknesses to probe deliberately: attribute binding
  ("red plastic robot" returning blue robots on red floors), file-name-like
  strings (pure noise in embedding space), long sentences (the text tower
  degrades past short phrases — keep queries 2–5 words).

## 3. Controlled retrieval experiments

Rules that keep results interpretable:

1. **One variable per experiment.** A run that changes `rank_constant` *and*
   field weights tells you nothing. Sweep one knob across runs:
   `rank_constant` ∈ {10, 20, 60}, `window_size`, `hybrid_text.weight`,
   a single field's weight, vector leg on/off.
2. **Freeze the corpus.** Pause crawlers (or record the index doc count
   before/after) — an index that grows mid-experiment invalidates comparisons.
3. **Record the full request body** next to every result set. The
   `scoring_config` you *think* you sent and the one the server *used* can
   differ (server env defaults fill omitted blocks — see
   `HYBRID_SEARCH_SCORING_CONFIG_*` in [`docker-compose.yml`](../docker-compose.yml)).
4. **Use the explanation plumbing** instead of guessing: every hit carries
   `metadata.explanations` (per-leg score, rank, matched terms/vectors) and
   `original_ranks`. `return_inner_hits=true` shows which nested field or
   which thumbnail view matched. This tells you *which leg* caused a ranking,
   which is the difference between "k=20 helped" and "k=20 helped because the
   text leg stopped drowning exact name matches".
5. Tag every query in your set with a **query class** — exact asset name,
   object category, style, material/color, functional/scene, long free-text — and
   report metrics per class. Config changes routinely help one class and hurt
   another; a single averaged number hides exactly the regressions you care
   about.

## 4. Evaluating ranking changes

Two existing layers, plus the gap between them:

- **Agent-level benchmark** — [`benchmark/`](../benchmark/README.md):
  `isaac-benchmark.yaml` holds ~30 natural-language queries with
  expected-asset ground truth; `run.py` drives a sandboxed agent through the
  `/search` skill and scores precision / recall / MRR (plus cost and latency).
  This measures the *whole journey* (agent + skill + API + ranking) — great
  for release sign-off, too noisy and too slow for ranking iteration. Mind the
  sandbox-masking rules in its README (ground truth must stay invisible to the
  agent).
- **API-level evaluation** — for ranking work, hit `POST /search_hybrid`
  directly with a config matrix over the same labeled query set and compute
  recall@k / MRR / NDCG@10 per query class. No agent variance, seconds per
  config, exact reproducibility. The benchmark YAML's `queries:` +
  `expected:` lists are directly reusable as ground truth.
- **Fusion-level unit tests** — pin ranking *semantics* (leg weights applied,
  fusion order) with stubbed OpenSearch responses so refactors can't silently
  change scoring. MR !98 introduces this pattern
  (`services/deepsearch_api/tests/test_rrf_scoring.py`).

When reporting a ranking change, always include: baseline vs candidate config
(full JSON), per-class metric deltas, and 2–3 example queries where the
ranking moved — with the per-leg explanation of *why*.

## 5. Using VLM validation as a relevance judge

For corpora without hand-labeled ground truth, the built-in validator is an
automatic judge:

- Per result set: `validate_results=true` on `/search_hybrid` annotates each
  hit with `query_relevance` (`is_match`, `confidence`, `similarity_score`
  0–100, `reasoning`).
- Per single asset: `POST /vlm_validate/search_result`
  ([`routers_v3/search_v3.py`](../services/deepsearch_api/deepsearch_api/routers_v3/search_v3.py)) —
  the response includes the active `model` identifier.

Methodology:

- Treat `is_match` as binary relevance and `similarity_score` as graded
  relevance for NDCG.
- **Cache judgments keyed `(query, asset, model)`** — judgments are
  reusable across every config you sweep, so a 20-config matrix costs the
  same VLM budget as one run. The returned `model` identifier is the
  cache-busting key when the deployment's validator model changes.
- Judge the **union** of top-k results across all configs under comparison,
  not each config's list separately — otherwise the judge sees a different
  pool per config and the comparison is biased.
- Caveats: the judge sees thumbnails only (geometry/rig quality is invisible);
  strictness follows the deployment's domain context
  (`validation.domain_context` in the helm values); VLM judges share the
  CLIP-family blind spots, so spot-check ~10% of verdicts by eye before
  trusting a sweep.

## 6. Known pitfalls (learned the hard way)

- **Disconnected weights.** Weighted fusion is only as correct as the mapping
  from config to leg. The RRF weight-resolution bug (vector-leg weights
  silently ignored because leg *names* couldn't be mapped back to
  `vector_fields` keys) shipped unnoticed for a long time — every "vector
  weight" experiment in that window measured nothing. Fix + regression tests:
  MR !98. Moral: before sweeping a knob, prove the knob is connected (one
  fusion-level test with stubbed legs).
- **Dead field names.** OpenSearch silently returns nothing for unmapped
  fields — a typo like `path.tree_reverse` (index has `path.tree_reversed`)
  is a permanently dead scoring clause, not an error. Validate configured
  field names against the live index mapping.
- **Raw-score thresholds don't mean what you think.** `cutoff_threshold`
  applies to engine scores, and for `innerproduct` kNN OpenSearch maps
  `ip ≥ 0 → 1 + ip` — so for normalized SigLIP2 embeddings the usable scale
  is ~[1.0, 2.0]. A threshold of `0.7` is a no-op that *looks* like a tuned
  value.
- **Empty text legs are match-all.** A `bool/should` with zero clauses
  matches every document with score 0 — a misconfigured field list doesn't
  fail, it injects `window_size` arbitrary docs as a full-strength RRF leg.
- **kNN legs never come back empty.** Vector search always returns the k
  nearest neighbors, however dissimilar — for out-of-vocabulary or
  file-name queries the vector leg is pure noise with full voting power.
  Watch per-leg `explanations` for low `vector_similarity` across the board.
- **Eval through the agent when you mean to eval the API.** Agent benchmarks
  add prompt/skill/model variance on top of ranking changes; never attribute
  an agent-level metric delta to a ranking change without an API-level
  confirmation.
