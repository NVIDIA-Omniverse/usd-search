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
| **Validation** (rerank results) | per result, opt-in | `gcp/google/gemini-3.5-flash` | [validation prompt](../packages/llm-client/llm_client/validation/validation_prompt.txt) | [`validation_fields.yaml`](../packages/llm-client/llm_client/validation/validation_fields.yaml) | [`validation/config.py`](../services/deepsearch_api/deepsearch_api/validation/config.py) |
| **Metadata gen** (tag assets) | batch, crawl time | `gcp/google/gemini-3.1-pro-preview` | [metadata prompt](../packages/llm-client/llm_client/metadata/metadata_prompt.txt) | [`metadata_fields.yaml`](../packages/llm-client/llm_client/metadata/metadata_fields.yaml) | [`metadata_generation.py`](../packages/llm-client/llm_client/metadata/metadata_generation.py) |

¹ must support structured output (json_schema). Failure modes are surfaced in the
503 `details` (timeout vs token limit vs schema mismatch) — a model that keeps
hitting its completion token limit needs a higher `USDSEARCH_LLM_PARSING_MAX_TOKENS`
or a different model.

Env prefixes: `USDSEARCH_LLM_PARSING_*`, `USDSEARCH_VISION_VALIDATION_*`,
`USDSEARCH_VISION_METADATA_*`. Each supports `_MODEL`, `_PROMPT_FILEPATH`,
`_MAX_TOKENS`, `_TEMPERATURE`, `_MAX_TRIES`, `_REASONING_EFFORT` (+ search: `_ENABLED`,
`_TIMEOUT_SECONDS`, `_CACHE_SIZE`, `_BASE_URL`, `_API_KEY`; validation: `_ENABLED`,
`_MAX_CONCURRENT`, `_TIMEOUT_SECONDS`, `_DOMAIN_CONTEXT_FILEPATH`). See each config
file for the full list.

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

## Precedence

built-in default → file / YAML → environment variable. The connection is read once and reused by every role.

## See also

- [`search-filters.md`](search-filters.md) — what the LLM query parser's filter catalog exposes to users and how to extend it.
- [`vlm-validation.md`](vlm-validation.md) — the validation role end-to-end (endpoints, Explorer behavior, cost).
- [`configuration-map.md`](configuration-map.md) — every feature's config file / env var / helm value in one table.
