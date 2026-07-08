# DeepSearch Explorer

React 18 + Chakra UI front-end for the DeepSearch / USD Search stack. Talks to
`services/deepsearch_api` over HTTP for search, asset details, dependency
graphs, and on-demand processing.

## Features

- Text / image / hybrid search with plain-language filters and a VLM Validated / Lower relevance split.
- Asset modal with a zoomable image preview (wheel-zoom + drag-pan) and a zoomable, pannable dependency graph.
- Queued download manager for assets and their dependencies.

## Quick start (with the rest of the stack)

From the repo root:

```bash
docker compose \
  -f infra/compose/opensearch.yml \
  -f infra/compose/deepsearch-api.yml \
  -f infra/compose/explorer.yml \
  up --build
```

Then open http://localhost:3000. The nginx server proxies `/api/*` to
`deepsearch-api:8000` at the same origin.

## Local dev (without docker)

```bash
cd services/explorer
npm install
REACT_APP_API_URL=http://localhost:8000 npm start
```

Requires `services/deepsearch_api` running on `:8000` (or set
`REACT_APP_API_URL` to wherever the API lives).

## Production build

The image is built by `docker/Dockerfile.explorer` (multi-stage:
`node:20-alpine` → `nginx:1.27-alpine`). Build context is the repo root:

```bash
docker build -f docker/Dockerfile.explorer -t deepsearch-explorer:dev .
```

## Configuration (`REACT_APP_*` build args)

All configuration is baked in at `npm run build` time — pass values as
`--build-arg` or via the compose file's `args:`.

| Variable | Default | Purpose |
|---|---|---|
| `REACT_APP_API_URL` | `""` (relative) | Base URL of the deepsearch-api. Use `/api` behind the nginx proxy. |
| `REACT_APP_DEFAULT_EMBEDDING_FIELD_NAME` | `siglip2-embedding.embedding` | OpenSearch nested field for kNN. |
| `REACT_APP_DEFAULT_EMBEDDING_DIMENSION` | `1536` | Embedding dim. SigLIP2 = 1536, CLIP = 1024. |
| `REACT_APP_SERVER_MAPPING` | `{}` | JSON map of nucleus/S3 server → `{name, apiUrl, embedding_config}`. |
| `REACT_APP_ENABLE_FEEDBACK_MODAL` | `false` | Show the in-app feedback modal. |
| `REACT_APP_ENABLE_NUCLEUS_AUTH` | `false` | Show Nucleus token auth. |
| `REACT_APP_ENABLE_API_KEY_AUTH` | `false` | Show API key auth. |
| `REACT_APP_ENABLE_BASIC_AUTH` | `true` | Show basic auth. |
| `REACT_APP_DUPLICATE_REMOVAL_THRESHOLD` | `0.0001` | Cosine distance below which results are deduped. |
| `REACT_APP_DEFAULT_CUTOFF_THRESHOLD` | `""` (none) | Default "Similarity Cutoff" pre-filled in the search form. Empty = no cutoff sent unless the user enters one. |
| `REACT_APP_DEFAULT_FILE_EXTENSION_INCLUDE` | `usd*` | Default "Include Extensions" filter (e.g. `usd*`, `usd*,usdz`, `*`). Explicit empty (`""`) = no extension filter (match all). |
| `REACT_APP_VALIDATION_MAX_CONCURRENT` | `50` | Parallel VLM-validation requests. |

See `src/config.jsx` for the full list.

### Building with overrides (`scripts/build-explorer.sh`)

`scripts/build-explorer.sh` bakes the default search-form values into the image
and tags it `<VERSION.md>-<short-sha>[-<suffix>]`. `--cutoff` / `--extensions`
accept both `--flag value` and `--flag=value` forms and allow empty values;
`--suffix` appends a trailing tag segment; `--push` pushes the image.

```bash
# CMS team: no extension filter, 0 cutoff, "-cms"-suffixed tag, pushed to the
# CMS NGC registry
REGISTRY=nvcr.io/m3sujtetvf5w/usdsearch \
  ./scripts/build-explorer.sh --extensions "" --cutoff 0 --suffix=cms --push
```

## Vendored dependencies

`_packages/` contains three NVIDIA Omniverse JS clients referenced as
`file:_packages/...` in `package.json`:

- `@omniverse/auth` — Nucleus auth client
- `@omniverse/discovery` — service discovery client
- `@omniverse/idl` — protobuf/IDL bindings

These are not on any public npm registry and must travel with the source.
