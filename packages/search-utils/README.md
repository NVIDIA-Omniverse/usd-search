# search-utils

Foundational utility layer shared by every USD Search service. Storage
clients, Redis stream workers, OpenSearch/Elasticsearch helpers, caching,
observability, and the ASGI middleware that powers the local-filesystem
backend.

## What's inside

| Module | Purpose |
|---|---|
| `storage_client/` | Async storage backends — `s3`, `nucleus`, `storage_api`. |
| `streams/`, `redis/` | Redis-stream consumer groups, `DeepSearchConsumer`, stream worker base classes. The crawler and monitor both build on these. |
| `cache_utils/` | Redis-backed caches. |
| `elastic_utils.py`, `opensearch_utils.py` | Shared OpenSearch / Elasticsearch query helpers. |
| `database_utils.py` | Backend-agnostic database client factory. |
| `local_fs_middleware.py` | ASGI middleware that bidirectionally rewrites `s3://<bucket>/...` ↔ local paths when running the local-filesystem compose overlay. |
| `observability_utils.py`, `prometheus_utils.py`, `telemetry_utils.py`, `log_utils.py` | Metrics, tracing, structured logging. |
| `config_utils.py`, `service_config_utils.py` | `pydantic-settings` helpers used by every service. |
| `tools/` | `fire`-based CLI utilities (`uv run --package search-utils python -m ...`). |
| `omni_microservice.py` | FastAPI bootstrap shared by services. |

## Install

Workspace member, installed via `uv sync`:

```bash
uv sync --package search-utils
```

### Optional extras

| Extra | Adds |
|---|---|
| `search-backend` | `opensearch-py`, `elasticsearch` (needed by `storage_client/*` against ES backends and by `ngsearch-backend`). |
| `storage-api` | `storage-api` workspace package + `authlib` + `httpx` (Omniverse Storage API gRPC client). |
| `pillow` | `pillow` for thumbnail handling. |
| `tools` | `tqdm` for the CLI tools. |

### Mandatory pre-build step

`search-utils` force-includes pre-compiled Omniverse protobuf packages into
its wheel. Before the first `uv sync`, run:

```bash
./build/build_search_utils.sh
```

This populates `packages/search-utils/_build/{discovery.client.py,
idl.py, omniverse_connection, omniverse.auth.client.py, tag_idl_client}/`,
which are referenced by `[tool.hatch.build.targets.wheel.force-include]`
in `pyproject.toml`. Skipping it produces:

```
FileNotFoundError: Forced include not found:
.../packages/search-utils/_build/discovery.client.py/omni
```

`_build/` is `.gitignored`; the script regenerates it on demand. The same
script runs inside `docker/Dockerfile.usdsearch`, so the Docker and local
paths share the mechanism.
