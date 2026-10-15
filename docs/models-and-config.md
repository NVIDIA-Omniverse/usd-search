<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Models & configuration

One shared **OpenAI-compatible** connection (NVIDIA Inference Hub by default) powers
three LLM/VLM **roles**. Each role just picks a *model*, a *prompt*, and (where it
applies) a *fields schema* — all editable files, no per-role keys. The links below
go straight to the source so you can read what each file does.

## Connection — set once

| Env var | Default |
|---|---|
| `USDSEARCH_LLM_API_KEY` | `""` |
| `USDSEARCH_LLM_BASE_URL` | `https://inference-api.nvidia.com` (NVIDIA Inference Hub) |
| `USDSEARCH_LLM_DEFAULT_HEADERS` | `{}` — JSON object of extra HTTP headers sent on every request (e.g. `{"X-HF-Bill-To":"my-org"}`) |

USD Search talks to **any OpenAI-API-compatible LLM/VLM serving system** and ships
pointed at NVIDIA Inference Hub by default. Set `USDSEARCH_LLM_API_KEY` to use the
default endpoint; point `USDSEARCH_LLM_BASE_URL` at any other OpenAI-API server
(OpenAI, Azure OpenAI, vLLM, LiteLLM, etc.) to switch. There is no provider
selector — just the one key + base URL.

Client + connection: [`llm_client/client.py`](../packages/llm-client/llm_client/client.py) — `ChatOpenAI` under the hood; reasoning off, `max_tokens` 4096 by default.

## Roles — and the files behind each

| Role | Runs | Default model | Prompt | Fields / schema | Config |
|---|---|---|---|---|---|
| **LLM query parser** (query → filters) | per query | `gcp/google/gemini-3.5-flash` ¹ | [system prompt](../services/deepsearch_api/deepsearch_api/llm_parse/prompts/llm_parsing_system_prompt.txt) | [`search_fields.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml) | [`llm_parse/config.py`](../services/deepsearch_api/deepsearch_api/llm_parse/config.py) |
| **Validation** (rerank results) | per result, opt-in | `gcp/google/gemini-3.1-flash-lite` | [validation prompt](../packages/llm-client/llm_client/validation/validation_prompt.txt) | [`validation_fields.yaml`](../packages/llm-client/llm_client/validation/validation_fields.yaml) | [`validation/config.py`](../services/deepsearch_api/deepsearch_api/validation/config.py) |
| **Metadata gen** (tag assets) | batch, crawl time | `azure/openai/gpt-5.6-sol` ² | [metadata prompt](../packages/llm-client/llm_client/metadata/metadata_prompt.txt) | [`metadata_fields.yaml`](../packages/llm-client/llm_client/metadata/metadata_fields.yaml) | [`metadata_generation.py`](../packages/llm-client/llm_client/metadata/metadata_generation.py) |

¹ must support structured output (json_schema). Failure modes are surfaced in the
503 `details` (timeout vs token limit vs schema mismatch) — a model that keeps
hitting its completion token limit needs a higher `USDSEARCH_LLM_PARSING_MAX_TOKENS`
or a different model.

² chosen by the 2026-08 metadata bake-off — see `deepsearch-evaluation/metadata_bakeoff/`.

### Metadata generation

The VLM metadata exists purely for search and retrieval — nothing in it is
user-facing. Every field is either distinctive searchable vocabulary (BM25 over
`value_text`) or a stable filter facet (`vision_metadata` k=v):

- Search vocabulary: `caption`, `object_type`, `queries`, `tags`, `environment`,
  `colors`, `materials`, `visible_text` (legibility-gated — only fully readable
  text is transcribed).
- Filter facets: `category`, `style` (representation-only), `scale`, `state`,
  `physical_attributes` (closed trait list; "rigid" is the implied default and
  not tagged). In the generic release `category` is free-text (nullable) — its
  corpus-derived 30-value vocabulary is **deployment-opt-in**: it ships
  commented out in `metadata_fields.yaml` and is enabled per deployment by
  uncommenting it or overriding
  `vision_endpoint.metadata_fields` in that deployment's helm values.
- Vocabulary enforcement is driven entirely by `allowed_values` in
  `metadata_fields.yaml` and comes in two flavors:
  - **Single-value fields** (`style`, `scale`, `state` — and `category` where
    a deployment enables its list) are nullable
    enums: the value is drift-normalized (case/spacing), and anything still
    off-vocabulary becomes **null** — never a forced wrong label.
  - **List fields** (`physical_attributes`) keep the good items and drop the
    bad: each item is drift-normalized, off-vocabulary items are **dropped and
    logged** (the log is the early-warning signal that the vocabulary may be
    missing a genuinely useful value), and the drop runs *before* the
    `max_items` truncation so junk items can never crowd out valid ones.
    Neither flavor ever fails validation or burns the one-shot repair re-ask.
  - For list bounds, `max_items` is enforced by truncating the least-relevant
    tail. `min_items` is prompt-only guidance: sparse lists remain valid so an
    otherwise useful asset is not discarded when the model finds fewer items.
  - The mechanism is YAML-generic: adding `allowed_values` to any list field
    (e.g. `colors`, `materials` later) enables the same behavior with no code
    change. Vocabularies are corpus-derived; the re-derivation runbook lives in
    the header of `packages/llm-client/llm_client/metadata/metadata_fields.yaml`.
- Removed as measured dead weight (2026-08): `use_cases` (top values applied to
  70-90% of all assets — zero-signal index bloat), `description` and
  `dense_description` (no query coverage beyond tags/queries), and the
  `is_high_quality`/`has_issues` booleans (stored as `value_bool`, unreachable
  by both the text leg and the k=v filter).

Env prefixes: `USDSEARCH_LLM_PARSING_*`, `USDSEARCH_VISION_VALIDATION_*`,
`USDSEARCH_VISION_METADATA_*`. Each supports `_MODEL`, `_PROMPT_FILEPATH`,
`_MAX_TOKENS`, `_TEMPERATURE`, `_MAX_TRIES`, `_REASONING_EFFORT`, `_EXTRA_BODY` (+ search: `_ENABLED`,
`_TIMEOUT_SECONDS`, `_CACHE_SIZE`, `_BASE_URL`, `_API_KEY`, `_PROBE_TTL_SECONDS` (default 120s — how long a
cached reachability-probe reading is trusted before `/llm_parse/query` re-probes; see
[llm-parse-probe-ttl-cache.md](plans/llm-parse-probe-ttl-cache.md)); validation: `_ENABLED`,
`_MODE`, `_METHOD` (`generative` | `logprob`), `_LOGPROB_*` (incl.
`_LOGPROB_DOMAIN_CONTEXT`), `_MAX_CONCURRENT`, `_MAX_IMAGES_PER_VALIDATION`,
`_TIMEOUT_SECONDS`, `_DOMAIN_CONTEXT_FILEPATH`; see
[vlm-validation.md](vlm-validation.md)). See each config file for the full list.

The LLM query parser may optionally run on **its own** endpoint: set
`USDSEARCH_LLM_PARSING_BASE_URL` / `USDSEARCH_LLM_PARSING_API_KEY` (helm:
`ngsearch.microservices.search_rest_api.llm_parsing.provider.*`) to override just
that field for the SEARCH role; leave both empty to share the connection above.
Validation and metadata always use the shared connection.

## Configure it — edit a file or set an env var

| To change… | Do this |
|---|---|
| The model for a role | set its `*_MODEL` |
| Endpoint / key | the connection env vars above (set once) |
| LLM query parsing on/off | `USDSEARCH_LLM_PARSING_ENABLED` — helm: `ngsearch.microservices.search_rest_api.llm_parsing.enabled` (model override: `.model`); quickstart compose: off in the base stack, enabled by the `docker-compose.vlm-plugins.yml` overlay. When off/unreachable, `/llm_parse/*` returns 503 and clients fall back to plain hybrid search |
| A role's prompt | edit its prompt file (linked above), or point `*_PROMPT_FILEPATH` at your own |
| Metadata tags / categories | edit [`metadata_fields.yaml`](../packages/llm-client/llm_client/metadata/metadata_fields.yaml) (model + prompt fields are generated from it) |
| Validation output fields | edit [`validation_fields.yaml`](../packages/llm-client/llm_client/validation/validation_fields.yaml) |
| **Which filters search understands** | edit [`search_fields.yaml`](../services/deepsearch_api/deepsearch_api/llm_parse/search_fields.yaml) — declare a field's `type`, `operators`, `description`, and a `map.kind`; drives the IR schema, prompt, and mapper |
| A field's USD property key | set `map.property` (or its `map.property_env`) in `search_fields.yaml` |

Override any `*_FILEPATH` to load your own copy instead of editing the shipped one.

## Embeddings (not an LLM role)

SigLIP2 on Triton via [`siglip2_triton_client/clip.py`](../packages/siglip2-triton-client/siglip2_triton_client/clip.py); env `CLIP_*` / `SIGLIP2_*` (e.g. `CLIP_TRITON_SERVER_URL`).

**Text queries are case-insensitive.** SigLIP2's reference preprocessing lowercases text before tokenization, so `"Red Chair"`, `"red chair"` and `"RED CHAIR"` produce the same embedding and the same results. Two layers enforce this: a `Lowercase` normalizer in the bundled `tokenizer.json`, and a lowercasing step in the client, which keeps the server-side (ensemble) path correct against a Triton container built before that normalizer was added. Set `SIGLIP2_LOWERCASE_TEXT=false` to disable the client-side layer and reproduce pre-fix behavior (`CLIP_LOWERCASE_TEXT` is the equivalent for a bare `CLIPConfig`; the services build a `SigLIP2Config`, whose prefix wins). Punctuation is *not* stripped (that is SigLIP v1 canonicalization, not v2). The keyword/BM25 legs were always case-insensitive — OpenSearch analyzers lowercase both sides — so this only ever affected the embedding leg.

## Precedence

built-in default → file / YAML → environment variable. The connection is read once and reused by every role.

## See also

- [`search-filters.md`](search-filters.md) — what the LLM query parser's filter catalog exposes to users and how to extend it.
- [`vlm-validation.md`](vlm-validation.md) — the validation role end-to-end (endpoints, Explorer behavior, cost).
- [`configuration-map.md`](configuration-map.md) — every feature's config file / env var / helm value in one table.
