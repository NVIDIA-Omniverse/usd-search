# Architecture

USD Search is a set of cloud-native microservices that index and query
OpenUSD scenes, images, and other 3D assets using natural-language or
image-based input. This page is for anyone **deploying or operating** the
stack; if you're modifying the repo's source, see
[`development.md`](development.md)'s "Key architecture notes" instead — that
section covers package layout and code-level conventions this page doesn't.

## Capabilities at a glance

- **Natural-language search** — find USD assets and images from a plain-text
  description. See [`search-filters.md`](search-filters.md).
- **Image-based search** — find assets visually similar to a reference image.
- **Hybrid search** — the default mode: semantic (embedding) similarity
  blended with keyword matching over auto-generated captions and tags.
- **Search inside a scene** — spatial/bounding-box queries, prim and property
  filters, and forward/reverse dependency lookups within a single USD scene,
  served by the Asset Graph Service. See
  [`../services/asset-graph/README.md`](../services/asset-graph/README.md).
- **USD property queries** — filter by properties the corpus actually
  carries (PhysX, materials, custom schema attributes). See
  [`usd-property-catalog.md`](usd-property-catalog.md).
- **Metadata filtering** — file name, type, size, date, creator/modifier, and
  more. See [`search-filters.md`](search-filters.md).
- **Asset dependency tracking** — the same dependency graph used for in-scene
  search also answers "what does this asset reference" and "where is this
  asset used," useful for change-impact analysis, reuse discovery, and
  manifest generation across a library.

## Microservices

![USD Search architecture: storage backends feed the indexing services, which
drive rendering, embedding, and asset-graph extraction; results are stored in
OpenSearch, Neo4j, and Redis and served to clients through the REST API](architecture.svg)

| Service | Role |
|---|---|
| **Search** (`services/deepsearch_api`) | Serves `/search_hybrid`, `/images`, and the beta LLM query-parsing/download endpoints. The public REST surface. |
| **Rendering** (`services/rendering-job`) | GPU-accelerated: renders USD/MDL assets into preview thumbnails from a fixed set of orientations, plus any cameras authored in the asset itself. |
| **Embedding** (`packages/siglip2-triton-client` + `services/siglip2-triton`) | Extracts SigLIP2 embeddings from rendered previews and 2D assets (images, textures) for semantic search. |
| **Indexing** (`services/deepsearch-crawler`, `services/deepsearch-monitor`, `services/crawlers`) | Crawls storage backends, drives rendering/embedding/metadata generation per asset, and writes to the search index. |
| **Asset Graph Service** (`services/asset-graph`, `services/asset-graph-builder`) | Extracts prim hierarchies and asset dependency graphs (sublayers, references, materials, MDL) via an Omniverse Kit subprocess, and serves spatial/structural/dependency queries. |
| **Info endpoint** (`services/info-endpoint`) | Per-plugin indexing status and USD scene summaries for a single asset. |

Vision-language auto-tagging/captioning and result validation are optional
plugins layered on indexing and search respectively — see
[`vlm-validation.md`](vlm-validation.md) and
[`models-and-config.md`](models-and-config.md).

## Data stores

| Store | Holds |
|---|---|
| **OpenSearch** | The search index: embeddings, captions/tags, and filterable metadata. |
| **Neo4j** | The asset dependency graph and per-scene prim hierarchy, used by the Asset Graph Service. |
| **Redis** | Caching, indexing-progress tracking, and Redis Streams for crawler/monitor coordination. See `development.md`'s "Redis logical database allocation" for the DB layout. |

## Supported storage backends

Assets are discovered and indexed from:

- Amazon S3 and S3-compatible providers (via
  [s3proxy](https://github.com/gaul/s3proxy) for non-AWS backends)
- Azure Blob Storage and Google Cloud Storage (via
  [s3proxy](https://github.com/gaul/s3proxy), which fronts them with an
  S3-compatible API)
- Omniverse Nucleus
- Omniverse Storage API
- Local filesystem (via [s3proxy](https://github.com/gaul/s3proxy) — see
  `development.md`'s "Local filesystem backend (s3proxy)")

See [`helm/usdsearch/README.md`](../helm/usdsearch/README.md)'s Deployment
section for the per-backend Helm configuration, or
[`local-deployment.md`](local-deployment.md) for docker-compose recipes.

## Container images

Each microservice above ships as (or runs from) one of a small set of
published images — see [`containers.md`](containers.md) for the full
inventory, build args, and registry/tagging scheme.

## Deployment shape

There is one deployment shape documented and supported by this repo: the
full stack (all microservices above), run either via docker-compose for local
evaluation ([`local-deployment.md`](local-deployment.md)) or via the Helm
chart for production Kubernetes
([`helm/usdsearch/README.md`](../helm/usdsearch/README.md)). There is no
"pre-rendered, pre-indexed, no-rendering/no-indexing" reduced deployment
variant in this repo.
