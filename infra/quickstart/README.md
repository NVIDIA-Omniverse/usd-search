# USD Search — Local Development Stack

Run the complete USD Search stack locally with one command.

## What's Included

| Service | Description |
|---------|-------------|
| **Explorer UI** | React web interface for searching 3D assets |
| **DeepSearch API** | FastAPI search backend (text + hybrid vector search) |
| **Asset Graph Service** | Neo4j-backed USD scene graph queries |
| **Indexing Pipeline** | Crawler → Redis stream → OpenSearch indexer |
| **OpenSearch** | Full-text + vector search index |
| **Redis** | Message streaming + caching |
| **Neo4j** | Graph database for asset relationships |

**Default storage backend**: Public S3 bucket `s3://omniverse-content-production` (no credentials required).

## Prerequisites

1. **Docker** with Docker Compose v2+

## Quick Start

```bash
# 1. Build the usdsearch Docker image (from repo root)
docker build --platform linux/amd64 \
  -f docker/Dockerfile.usdsearch -t usdsearch:latest .

# 2. Start the stack (explorer builds automatically)
docker compose up -d

# 3. Open in browser
open http://localhost:8080
```

## How It Works

```
Browser → :8080 (nginx gateway)
           ├── /ui             → Explorer React SPA (built from services/explorer/)
           ├── /search         → DeepSearch API (text search)
           ├── /search_hybrid  → DeepSearch API (vector search)
           ├── /images         → DeepSearch API (thumbnails)
           ├── /info           → Info Endpoint (plugins, status)
           ├── /asset_graph/   → Asset Graph Service
           └── /               → redirects to /ui

Indexing Pipeline:
  deepsearch-crawler (S3 scanner)
    → Redis stream
      → indexing-crawler
        → OpenSearch
```

## Configuration

### Different S3 bucket

Edit `docker-compose.yml` and change the `x-common-env` anchor:

```yaml
x-common-env: &common-env
  S3_STORAGE_BUCKET_NAME: your-bucket-name
  S3_STORAGE_REGION_NAME: your-region
  S3_STORAGE_AWS_ACCESS_KEY_ID: your-key      # add if private bucket
  S3_STORAGE_AWS_SECRET_ACCESS_KEY: your-secret # add if private bucket
```

### Vector search (optional)

To enable semantic/vector search with SigLIP2 embeddings:

```bash
docker compose --profile vector-search up -d
```

Then set `MOCK_EMBEDDING=false` on the `deepsearch-api` service and restart it.

## Ports

| Port | Service |
|------|---------|
| 8080 | Gateway (main entry point) |
| 9200 | OpenSearch (direct access) |
| 6379 | Redis |
| 7474 | Neo4j Browser |
| 7687 | Neo4j Bolt |

## Troubleshooting

### Indexing is slow

The `omniverse-content-production` bucket is large. The crawler scans from `/` by default. To limit scope:

```yaml
deepsearch-crawler:
  environment:
    DEEPSEARCH_CRAWLER_PATH: /NVIDIA/Assets/Isaac/6.0  # scan only a subtree
```

### OpenSearch out of memory

Increase heap size in the compose file:

```yaml
opensearch:
  environment:
    - "OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g"
```

### Resetting everything

```bash
docker compose down -v
```

This removes all data volumes (OpenSearch index, Redis, Neo4j).
