# DeepSearch Crawler

The DeepSearch Crawler connects to a supported storage backend, scans it
for assets, and pushes discovered items onto a
[Redis Stream](https://redis.io/docs/data-types/streams/) for downstream
indexing workers (`services/deepsearch-monitor`) to consume via the
shared `DeepSearchConsumer` from `packages/search-utils`.

- **Nucleus**: the crawler subscribes to live update notifications, so
  changes are picked up as they happen.
- **S3** (public or private): subscription updates are not supported, so
  the crawler periodically re-scans the bucket at a configurable
  interval.

## Install

This service is a `uv` workspace member. From the repo root:

```bash
uv sync --package deepsearch-crawler
```

(See the [main CLAUDE.md](../../CLAUDE.md#build-and-install) for the
mandatory `./build/build_search_utils.sh` pre-step.)
