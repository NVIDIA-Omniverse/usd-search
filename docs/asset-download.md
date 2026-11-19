# Asset Download

> [!NOTE]
> **Beta.** Asset download is an early-access preview: the API, UI, and limits described here may change in upcoming releases. See [`docs/beta.md`](beta.md).

Download any indexed asset as a self-contained ZIP — the root USD plus all transitive dependencies (sublayers, references, textures, and the MDL modules a packed module imports) — with folder structure preserved so it opens without path fixups.

## Explorer UI

A download button appears on every result card and in the asset details modal.

- **Pre-click size** — file count and estimated total size shown before you commit.
- **Live progress** — elapsed time and bytes on the thumbnail, modal, and Downloads panel.
- **Queue** — multiple downloads run one at a time and auto-advance.
- **Cancel** — from the card, modal, or Downloads panel at any time.
- **Downloads panel** — *Display → Downloads* tracks active, queued, and completed. Completed items stay until dismissed.

If any files were skipped (not found, no access, deleted) or a download failed, a warning appears in the panel and as a toast. Full details, including why each file was left out, are in the archive's `manifest.json`.

## API

```
GET /download/asset?asset_url=<uri>
```

Add `?manifest_only=true` to get a JSON size preview (file count + total bytes) without building the ZIP.

**Responses:** `200` zip · `403` access denied · `404` root not found · `413` size cap exceeded · `503` too many downloads in progress (with `Retry-After`).

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
    "dependencies_truncated": false,
    "dependencies_unavailable": false,
    "downloaded": 42,
    "skipped_not_found": 1,
    "skipped_access_denied": 0,
    "skipped_no_access_or_missing": 0,
    "skipped_deleted": 1,
    "skipped_resolved_elsewhere": 1,
    "respelled": 0,
    "download_failed": 0
  },
  "skipped": [{ "url": "...", "reason": "not_found" }],
  "errors": {}
}
```

Every `skipped` entry carries one of these reasons, and `summary` counts them:

| Reason | Meaning |
|---|---|
| `not_found` | No such object in storage — a dangling reference, or deleted since the graph was built. |
| `access_denied` | The object exists but this caller may not read it. |
| `no_access_or_missing` | Backend cannot tell those two apart (Nucleus only; S3 never uses it). |
| `deleted` | The asset graph marks the dependency deleted. |
| `resolved_elsewhere` | Not a storage object — the runtime finds it on its own search path (e.g. `OmniPBR.mdl` via `MDL_SYSTEM_PATH`). Reported, not bundled. |

`errors` maps the URL of each file that passed the access check but could not be
retrieved to a description of the failure, named after the underlying error when
it carries no message of its own, and suffixed with the storage backend's status
where it reports one (for example `S3ObjectNotFound (NoSuchKey)`). A size preview
reports the same map, using `not_found` where the file is missing and
`no_size_reported` where a `HEAD` succeeded without one. `summary.download_failed`
counts them.

`dependencies_truncated` is `true` when the graph returned as many entries as
`DOWNLOAD_MAX_DEPENDENCIES` allowed, so the bundle may be missing files. Raise or
unset the cap and download again.

`dependencies_unavailable` is `true` when the asset graph could not be read at
all — the service was down, or the asset was never graphed — so the archive holds
the root asset alone. This is distinct from a graphed asset that genuinely has no
dependencies, which reports `false` with `dependencies_reported: 0`.

`respelled` counts dependencies bundled under a percent-decoded spelling of the
URL the graph recorded; the decoded form is adopted only when that object
actually exists. A non-zero count means that part of the asset graph is due a
rebuild.

## UDIM textures and assetInfo labels

The bundle holds what the asset graph recorded, and the graph builder records two
kinds of authored path differently from how they are written:

- **`<UDIM>` textures** (`T_Albedo.<UDIM>.png`) are recorded as the tiles that
  exist (`T_Albedo.1001.png`, `T_Albedo.1002.png`, …), so every tile is bundled.
  The builder lists the texture directory once; on a backend that cannot list it,
  it checks tiles one by one (1001–1099 by default, as USD does). A pattern with
  no tile at all stays in the graph, so the missing texture still shows up in
  `skipped`.
- **`assetInfo` paths** (`identifier` and other asset values inside a prim's
  `assetInfo`) are labels: USD never opens them, and they are often stale. They
  are not dependencies and are not bundled. A path the same layer also uses as a
  sublayer, reference, payload or attribute value is kept.

Graphs built before this behavior still record the literal pattern and the
labels:

- **`<UDIM>`**: the bundler expands a recorded placeholder itself. Like the
  builder, it lists the texture folder once (on S3, only the keys under the
  texture's name) and bundles every tile found, so the placeholder is not
  reported. Only when the folder cannot be listed or lists no tile does it
  check tiles `DOWNLOAD_UDIM_PROBE_FIRST_TILE`..`DOWNLOAD_UDIM_PROBE_LAST_TILE`
  (one existence check each, all patterns in one batch). A tile the caller may not read is reported
  as `access_denied`; a placeholder with no tile stays in `skipped`.
- **`assetInfo` labels**: the bundler cannot tell a label from a real dependency,
  so these stay in `skipped` (as `not_found` / `no_access_or_missing`) until the
  asset graph is [rebuilt](#rebuilding-the-asset-graph).

The builder reads these settings from its environment (Helm: the asset-graph
plugin's `kit_worker.env`):

| Env var | Default | Description |
|---|---|---|
| `UDIM_TOKEN` | `<UDIM>` | Placeholder that stands for the tile number in a texture path. |
| `UDIM_PROBE_FIRST_TILE` | `1001` | First tile checked when the texture directory cannot be listed. |
| `UDIM_PROBE_LAST_TILE` | `1099` | Last tile checked (inclusive). Each tile is one storage lookup per pattern, so a wider range is slower on remote backends. |

Tiles must be four-digit UDIM numbers (1001–9999). An invalid value (empty
token, non-integer, out of range, first tile above the last) logs a warning and
the defaults apply.

## Rebuilding the asset graph

The bundle follows the asset graph, so a fix to how the graph builder records
dependencies applies only to graphs built after it: MDL modules a packed module
imports (e.g. `import OmniPBR_ClearCoat::*;` next to `OmniPBR.mdl`), textures a
`.mdl` references by an explicitly relative path, and the `<UDIM>`/`assetInfo`
handling above. Until an asset is reprocessed, its bundle can lack those MDL
modules and textures without listing them in `skipped` (the `<UDIM>` and
`assetInfo` cases are handled or reported as described above).

To rebuild existing graphs, re-run only the `asset_graph_generation` plugin over
the indexed paths (other plugins and metadata are left alone):

```bash
kubectl exec -it $(kubectl get pods -l deepsearch.service.name=info-endpoint -o jsonpath='{.items[0].metadata.name}') -- \
    python -m usdsearch.admin.tools reindex <path> \
    --include_plugins='["asset_graph_generation"]' \
    --asset_formats='["usd","usda","usdc","usdz"]' \
    --ignore_existing_statuses=True \
    --refresh_metadata=False
```

`--ignore_existing_statuses=True` resubmits every asset under `<path>`, including
those already processed successfully (by default `reindex` only retries assets
that are not `ok`). `reindex` lists `<path>` in storage rather than the index,
so it also picks up paths the crawler's `exclude_patterns` keep out; pass the
same exclusions with `--exclude_file_patterns='["*/NVIDIA/*"]'` (`fnmatch`
globs matched against the full URL, not the crawler's regexes). Add
`--dry_run=True` to list the assets first. See
[Re-indexing](../helm/usdsearch/README.md#re-indexing) for the tool's other
options.

## Configuration

Set via `DOWNLOAD_*` env vars or Helm (`ngsearch.microservices.search_rest_api.download`).

| Env var | Default | Description |
|---|---|---|
| `DOWNLOAD_MAX_DEPENDENCIES` | `0` = unlimited | Max transitive dependencies to include. |
| `DOWNLOAD_MAX_DEPENDENCY_DEPTH` | unlimited | Max traversal depth. |
| `DOWNLOAD_CONCURRENCY` | `8` | Concurrent file fetches during assembly. |
| `DOWNLOAD_SIZE_CHECK_CONCURRENCY` | `16` | Concurrent HEAD requests for the size preview. |
| `DOWNLOAD_MAX_BUNDLE_BYTES` | `0` = unlimited (chart: 2 GiB) | Reject bundles larger than this with `413`. |
| `DOWNLOAD_TEMP_DIR` | system default (chart: `/var/tmp/usdsearch-downloads`) | Where the ZIP is assembled **and served from**. Must be disk-backed — see the warning below. |
| `DOWNLOAD_MAX_CONCURRENT` | `4` | Bundle assemblies in flight per process (`0` = unlimited); excess waits, then `503`. Previews are exempt. |
| `DOWNLOAD_QUEUE_TIMEOUT` | `60` | Seconds to wait for a free slot before returning `503`. Keep below the gateway's 300 s read timeout. |
| `DOWNLOAD_COMPRESSION` | `auto` | `auto` stores already-compressed members (`.png`, `.mp4`, `.usdz`, …) — zlib saves ~0.1% on them for a full CPU pass; USD still deflates. `deflate` compresses everything, `stored` nothing. |
| `DOWNLOAD_STORED_EXTENSIONS` | images, video, archives | Comma-separated extensions stored uncompressed under `auto`. |
| `DOWNLOAD_TRACE_FILES` | `true` | Emit a `download.fetch` span per bundle member. |
| `DOWNLOAD_UDIM_TOKEN` | `<UDIM>` | Placeholder that marks a recorded dependency as a set of UDIM tiles ([details](#udim-textures-and-assetinfo-labels)). |
| `DOWNLOAD_UDIM_PROBE_FIRST_TILE` / `DOWNLOAD_UDIM_PROBE_LAST_TILE` | `1001` / `1099` | Tiles checked for such a placeholder when its folder cannot be listed (inclusive, 1001–9999); one existence check per tile. |

The archive is streamed from disk, so the response carries a `Content-Length`
and peak memory is `DOWNLOAD_CONCURRENCY` × largest file, not bundle size.

> **`DOWNLOAD_TEMP_DIR` must be disk-backed.** The archive lives there until the
> client finishes downloading, so a RAM-backed volume (`/tmp`, `/dev/shm`,
> `emptyDir: {medium: Memory}`) holds the whole bundle in memory and fails with
> `OSError: [Errno 28] No space left on device`.

`DOWNLOAD_MAX_CONCURRENT` × `DOWNLOAD_MAX_BUNDLE_BYTES` bounds the volume's use;
keep it under the volume size (the chart ships 4 × 2 GiB against 10 GiB).

`asset_url` accepts a public (rewritten) URL as well as the internal one when the
deployment publishes them — see
[configuration-map.md](configuration-map.md#public-asset-urls). Every URL in the
response, including the ones inside `manifest.json`, is then in the public form
too, so the archive quotes the same addresses the API gave you. The `path` values
describe the layout inside the ZIP and are never rewritten.

## Telemetry

When search telemetry is enabled (`USE_SEARCH_TELEMETRY=true` **and**
`SEARCH_TELEMETRY_STDOUT=true`, Helm
`ngsearch.microservices.search_rest_api.use_search_telemetry` /
`search_telemetry_stdout` — both are needed), every `/download/asset` request
writes one business event to the service log alongside the existing search
events. It is keyed `asset_load_total` and records:

| Field | Meaning |
|---|---|
| `asset_url` | The requested asset, always in the internal form (so it joins to search events and to the OpenSearch `base_key`, even where public URLs are published). |
| `username` | The caller, resolved from the bearer token, basic-auth username, or API key. `anonymous` when the request carries no identity. See the note on bearer tokens below. |
| `manifest_only` | `true` for a size preview, which transfers no asset data; `false` for a real download. **Always present.** |
| `status`, `http_status`, `error_type` | Outcome. Rejections (`403`, `404`, `413`, `503`) are recorded, not dropped. |
| `n_files`, `total_bytes`, `n_failed` | Bundle contents. |
| `dependencies_reported`, `dependencies_truncated`, `dependencies_unavailable`, `n_skipped_no_access`, `n_skipped_deleted` | What the dependency graph returned and what was excluded. `n_skipped_no_access` remains the total of every non-deletion skip. |
| `n_skipped_resolved_elsewhere`, `n_respelled` | See the skip reasons under [manifest.json](#manifestjson). |
| `n_udim_expanded` | `<UDIM>` placeholders bundled as their tiles ([details](#udim-textures-and-assetinfo-labels)). |
| `acl_check_ms` | Access check on the root asset — only when `STORAGE_REQUIRE_AUTH` is on. |
| `dependency_resolve_ms` | Dependency resolution end to end — the graph call **and** the access check below. |
| `ags_graph_ms` | The Asset Graph Service call alone. |
| `dependency_acl_ms` | The per-dependency access check alone, usually the larger half. Absent when there was nothing to check. |
| `udim_expand_ms` | Finding the tiles of `<UDIM>` placeholders: folder listings, plus probes where a folder cannot be listed. Absent when there are no dependencies. |
| `size_check_ms` | Time spent on the HEAD pass — only when a size preview or a size cap runs. |
| `queue_wait_ms` | Wait for a `DOWNLOAD_MAX_CONCURRENT` slot; present only when the cap is on. |
| `collect_ms` | Fetching the files and writing them into the ZIP — split by the next three fields. |
| `fetch_wait_ms` | Blocked on the storage backend. Wall clock, not a per-file sum — concurrent fetches make it ~the whole phase. |
| `fetch_total_ms`, `fetch_max_ms` | Summed and slowest per-file fetch. Summed ≫ `collect_ms` means they overlapped; ≈ means they serialized. |
| `compress_ms` | Time in the ZIP writer. |
| `n_stored`, `n_deflated` | Members stored vs. deflated. |
| `finalize_ms` | Time spent writing the manifest into the archive. |
| `processing_time_ms` | The whole request, server-side. |

Every phase is also a child span, and each member gets a `download.fetch` span.
The storage client's HTTP span ends at response headers, so body-transfer time
sits between the two.

Reading the numbers:

- **Count real downloads with `manifest_only=false`.** The Explorer issues a
  preview call whenever the asset details modal opens, so counting every event
  overstates downloads. Include the error rows: a `413` is a download that was
  attempted and refused, and `status` is what separates attempt from success.
- **Byte and file counts mean different things on the two paths.** On a preview
  they come from HEAD requests and describe what *would* be transferred; on a
  real download they describe what *was*. Do not sum them together.
- **Timings are server-side processing time**, not what the user experienced.
  They stop when the archive is handed to the web server, so the time spent
  sending it over the network is not included.
- **An interrupted request records nothing.** The event is written when the
  request finishes, so a cancelled download (the Explorer supports cancel) is
  recorded as a success, and a request that never finishes at all — a restarted
  pod mid-bundle — produces no event.

**Bearer-token identities on non-Nucleus backends.** The username is now read
from the bearer token whatever the storage backend is. Previously only Nucleus
tokens were decoded, so a deployment authenticating with tokens against S3 or the
Storage API recorded every caller as `anonymous` — including in search telemetry.
Those deployments will start seeing real identities in their logs after upgrading.

Telemetry is off by default. Because these events identify the caller, turning
telemetry on is what makes usernames appear in the logs; `USE_SEARCH_TELEMETRY=false`
is the way to record nothing about who is searching or downloading.

## Limitations

- **Single storage backend.** Files are fetched through the configured storage client (S3, Nucleus, etc.). Cross-server dependencies fail gracefully and appear in `manifest.json` under `errors`.
- **Non-USD / unindexed assets.** Assets not registered in the Asset Graph Service are bundled as a single file — the dependency lookup returns nothing and the root is packed alone.
