# Asset Download

> [!NOTE]
> **Beta.** Asset download is an early-access preview: the API, UI, and limits described here may change in upcoming releases. See [`docs/beta.md`](beta.md).

Download any indexed asset as a self-contained ZIP — the root USD plus all transitive dependencies (sublayers, references, textures) — with folder structure preserved so it opens without path fixups.

## Explorer UI

A download button appears on every result card and in the asset details modal.

- **Pre-click size** — file count and estimated total size shown before you commit.
- **Live progress** — elapsed time and bytes on the thumbnail, modal, and Downloads panel.
- **Queue** — multiple downloads run one at a time and auto-advance.
- **Cancel** — from the card, modal, or Downloads panel at any time.
- **Downloads panel** — *Display → Downloads* tracks active, queued, and completed. Completed items stay until dismissed.

If any files were skipped (no access, deleted, fetch error), a warning appears in the panel and as a toast. Full details are in the archive's `manifest.json`.

## API

```
GET /download/asset?asset_url=<uri>
```

Add `?manifest_only=true` to get a JSON size preview (file count + total bytes) without building the ZIP.

**Responses:** `200` zip · `403` access denied · `404` root not found · `413` size cap exceeded.

The `X-Download-Summary` header contains a compact JSON count of downloaded/skipped/failed files — readable without unzipping.

### manifest.json

Included at the archive root:

```json
{
  "root_url": "s3://bucket/path/scene.usd",
  "file_count": 42,
  "files": [{ "url": "...", "path": "scene.usd", "size": 12345 }, "..."],
  "summary": {
    "dependencies_reported": 45,
    "downloaded": 42,
    "skipped_no_access_or_missing": 2,
    "skipped_deleted": 1,
    "download_failed": 0
  },
  "skipped": [{ "url": "...", "reason": "no_access_or_missing" }],
  "errors": {}
}
```

## Configuration

Set via `DOWNLOAD_*` env vars or Helm (`ngsearch.microservices.search_rest_api.download`).

| Env var | Default | Description |
|---|---|---|
| `DOWNLOAD_MAX_DEPENDENCIES` | unlimited | Max transitive dependencies to include. |
| `DOWNLOAD_MAX_DEPENDENCY_DEPTH` | unlimited | Max traversal depth. |
| `DOWNLOAD_CONCURRENCY` | `8` | Concurrent file fetches during assembly. |
| `DOWNLOAD_SIZE_CHECK_CONCURRENCY` | `16` | Concurrent HEAD requests for the size preview. |
| `DOWNLOAD_MAX_BUNDLE_BYTES` | `0` (unlimited) | Reject bundles larger than this. |
| `DOWNLOAD_TEMP_DIR` | system default | Where the ZIP is assembled. Point at a `tmpfs`/`/dev/shm` volume on Kubernetes. |

## Limitations

- **Single storage backend.** Files are fetched through the configured storage client (S3, Nucleus, etc.). Cross-server dependencies fail gracefully and appear in `manifest.json` under `errors`.
- **Non-USD / unindexed assets.** Assets not registered in the Asset Graph Service are bundled as a single file — the dependency lookup returns nothing and the root is packed alone.
