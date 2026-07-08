# Container Images & the Explorer

This repo builds and publishes several container images from CI. This doc
explains **what each image is, how it's built, and where it's pushed**. If
you've ever been unsure "which image is which and where does it come from,"
start here.

## Image inventory

| Image | Dockerfile | Build context | What it is | CI build job |
|---|---|---|---|---|
| `usdsearch` | `docker/Dockerfile.usdsearch` | repo root | Combined Python image — every workspace service (deepsearch-api, info-endpoint, monitor / plugin workers, asset-graph-service, deepsearch-crawler, ngsearch indexers, …) **except** `rendering-job`, `asset-graph-builder`, `siglip2-triton`. CMD is overridden per service. | `build-usdsearch` |
| `siglip2-triton` | `docker/Dockerfile.siglip2-triton` | `services/siglip2-triton` | Triton Inference Server with the SigLIP2 ONNX model bundled (7.2 GB of weights from Git LFS). | `build-siglip2-triton` |
| `usdsearch-kit-workflows` | `docker/Dockerfile.kit` | `services/rendering-job` (+ `graph-builder` build-context) | GPU-accelerated Omniverse Kit image. Reused for both the renderer and the asset-graph-builder sidecar (`MODE=graph-builder`). | `build-rendering-job` |
| `usdsearch-explorer` | `docker/Dockerfile.explorer` | repo root | Explorer React SPA, built and served as a **static bundle on bitnami nginx** (`/app`, port `:8080`, non-root). | `build-explorer` |

## Registry & tagging

Two registries are involved:

1. **Build stage → GitLab registry** (every pipeline). Each `build-*` job pushes
   an SHA-tagged image for downstream jobs to consume:
   `$CI_REGISTRY_IMAGE/<name>:$CI_COMMIT_SHORT_SHA`. These are intermediates, not
   releases — but you *can* pull them directly if you just want "the image from
   this commit" without waiting for a release.

2. **Publish stage → NGC** (`PUBLISH_REGISTRY`, currently
   `nvcr.io/omniverse/deeptag-internal`). The `publish-*` jobs re-tag the
   SHA image and push:
   `nvcr.io/omniverse/deeptag-internal/<name>:<version>`
   - `<version>` = the git tag if the pipeline is a tag push (e.g. `images-X.Y.Z`),
     otherwise `<VERSION.md>-<short-sha>`.
   - `:latest` is also pushed on the default branch.
   - **`publish-*` runs automatically only on a git tag; on normal MR/branch
     pipelines it's `when: manual`** (click it to publish a one-off).

Published image names: `usdsearch`, `siglip2-triton`, `usdsearch-kit-workflows`,
`usdsearch-explorer`.

To pull a published image you need NGC credentials with read access to
`omniverse/deeptag-internal`; for the GitLab-registry SHA images you need a
`docker login` to the GitLab container registry.

## Explorer in depth

The Explorer is a Create-React-App SPA. It's built with Node, then the static
bundle is copied into a **bitnami nginx** image (`bitnamilegacy/nginx`) which
serves `/app` on `:8080` as a non-root user — matching the `deepsearch-explorer`
Helm sub-chart (itself the bitnami nginx chart) and the established deployment
convention.

There is **no reverse-proxy inside the image**. The SPA reaches the API the same
way it always has: a build-time base URL plus the fronting gateway.

### Build args (`docker/Dockerfile.explorer`)

CRA **inlines `REACT_APP_*` env vars at build time**, so API-wiring is a
*build-time* decision.

| Arg | Default | Purpose |
|---|---|---|
| `REACT_APP_API_URL` | `""` | Base the SPA prefixes onto API calls. `""` → same-origin paths (`/search_hybrid`, `/images`, …), routed by the fronting gateway. Set it to a gateway base URL to call a specific instance directly (CORS permitting). |
| `REACT_APP_SERVER_MAPPING` | `""` | JSON map of server → `{name, apiUrl, embedding_config}` for a multi-server picker. |
| `REACT_APP_ENABLE_FEEDBACK_MODAL` | `""` | `"true"` enables the feedback modal. |
| `REACT_APP_DEFAULT_EMBEDDING_FIELD_NAME` | `siglip2-embedding.embedding` | Default embedding field (e.g. `clip-embedding.embedding` for the legacy CLIP index). |
| `REACT_APP_DEFAULT_EMBEDDING_DIMENSION` | `1536` | Default embedding dimension (CLIP = `1024`). |
| `REACT_APP_IMAGE_MAX_DIMENSION` | `1920` (Full HD) | Longest side (px) uploaded query images are downscaled to (aspect ratio preserved) before being sent to `/search_hybrid` and the per-hit VLM validator. `0` disables resizing. |
| `REACT_APP_VERSION` | from `VERSION.md` | Shown in the header. |

## Deployment scenarios

### Local stack with WebUI

The quickstart stack builds the Explorer with `REACT_APP_API_URL=""` and serves
it at `/ui` through the gateway, which routes the APIs:

```bash
docker compose -f docker-compose.yml -f docker-compose.web-ui.yml up -d --build
# open http://<host>:8080/ui/
```

The gateway proxies `/ui` → `explorer:8080`; the Explorer container only serves
static assets.

### Helm / Kubernetes

The chart's `deepsearch-explorer` sub-chart (the bitnami nginx chart) consumes
the prebuilt **`usdsearch-explorer`** image directly — no git-clone / build-at-startup
init container. Because the image is bitnami-native (`/app`, `:8080`, non-root),
no port or securityContext overrides are needed. See
`helm/usdsearch/values.yaml` (`deepsearch-explorer:` block). The api-gateway
serves the SPA at `/ui` and routes the APIs.

## Building & pushing manually

```bash
REG=nvcr.io/omniverse/deeptag-internal
VERSION=1.3.3
echo "$NGC_API_KEY" | docker login nvcr.io -u '$oauthtoken' --password-stdin

docker build -f docker/Dockerfile.explorer --build-arg REACT_APP_API_URL= \
  -t $REG/usdsearch-explorer:$VERSION .
docker push $REG/usdsearch-explorer:$VERSION
```

Run from the **repo root** — the Dockerfile's build context is `.`. Add other
`--build-arg REACT_APP_*` flags (server mapping, feedback modal, embedding
field) as needed for a particular deployment.

## See also

- `docs/local-deployment.md` — configuration recipes (CPU-only, custom S3, local
  filesystem, VLM auto-tagging, Explorer WebUI).
- `CLAUDE.md` (repo root) — Docker / compose / Helm / CI architecture notes.
