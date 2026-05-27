# DeepSearch Explorer

React 18 + Chakra UI front-end for the DeepSearch / USD Search stack. Talks to
`services/deepsearch_api` over HTTP for search, asset details, dependency
graphs, and on-demand processing.

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
| `REACT_APP_VALIDATION_MAX_CONCURRENT` | `50` | Parallel VLM-validation requests. |

See `src/config.jsx` for the full list.

## Vendored dependencies

`_packages/` contains three NVIDIA Omniverse JS clients referenced as
`file:_packages/...` in `package.json`:

- `@omniverse/auth` — Nucleus auth client
- `@omniverse/discovery` — service discovery client
- `@omniverse/idl` — protobuf/IDL bindings

These are not on any public npm registry and must travel with the source.
