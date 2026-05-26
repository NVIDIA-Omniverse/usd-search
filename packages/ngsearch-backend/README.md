# ngsearch-backend

CLIP / SigLIP2 search backend for USD Search. Wraps an OpenSearch (or
Elasticsearch) index, talks to a Triton-hosted SigLIP2 encoder via
[`siglip2-triton-client`](../siglip2-triton-client/), and exposes the
indexing + query primitives used by `services/deepsearch_api`.

## What's inside

| Module | Purpose |
|---|---|
| `backend.py` | High-level backend facade — bulk index, query, delete. |
| `clip.py` | Embedding helpers (CLIP / SigLIP2). |
| `opensearch_backend.py`, `elasticsearch_backend.py` | Per-engine query construction and bulk ingestion. |
| `opensearchpy_patches.py`, `opensearch_serializers.py`, `opensearch_transport.py` | Workarounds + custom transport for `opensearch-py`. See the OpenSearch 3.x regexp `~` complement note in [CLAUDE.md](../../CLAUDE.md#known-workspace-limitations). |
| `omni_backend.py` | Omniverse-specific glue. |
| `data.py`, `utils.py`, `exceptions.py` | Shared models, helpers, exception types. |

## Install

This package is a `uv` workspace member:

```bash
uv sync --package ngsearch-backend
```

Pulls in `search-utils[search-backend]` (OpenSearch + Elasticsearch
clients) and `siglip2-triton-client` from the workspace.
