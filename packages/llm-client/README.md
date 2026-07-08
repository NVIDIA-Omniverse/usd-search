# llm-client

A lean, OpenAI-compatible LLM/VLM client for USD Search.

All roles (search-query parsing, per-result validation, batch metadata generation)
share **one** OpenAI-compatible connection — a single `USDSEARCH_LLM_API_KEY` and
`USDSEARCH_LLM_BASE_URL`, set once and reused. The base URL defaults to NVIDIA
Inference Hub; override it to point at any OpenAI-API server (vLLM, LiteLLM, Azure
OpenAI, OpenAI, etc.). Each role only chooses a **model** (and its prompt / tuning);
it never carries its own API key. Because the endpoint is OpenAI-compatible, a single
`langchain_openai.ChatOpenAI`-backed `LLMClient` serves every role — there is no
provider selector.

This package intentionally does **not** include embeddings: SigLIP2 image/text
embeddings live in the standalone `siglip2-triton-client`.

## Layout
- `client.py` — `LLMClient` (structured output + text/image invoke) and the shared
  `LLMConnectionConfig`.
- `metadata/` — VLM metadata generation (file-based prompt + schema).
- `validation/` — VLM search-result validation (file-based prompt + schema).
