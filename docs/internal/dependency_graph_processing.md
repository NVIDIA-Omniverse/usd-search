# Triggering dependency-graph (asset-graph) processing

This guide shows how to (re)index a folder of USD assets with the
**`asset_graph_generation`** plugin — the plugin that builds the USD dependency
graph consumed by the Asset Graph Service (AGS) and the `search-in-scene`
workflows.

There are two ways to do it:

1. **Bulk folder reindex with the `usdsearch` admin CLI** — runs *inside the
   cluster*, lists a whole folder via the storage client and fans out per-asset
   processing calls.
2. **Per-asset reindex over the HTTP API** — the client enumerates the asset
   URLs itself and calls the `/process/asset` endpoint once per asset. No cluster
   (`kubectl`) access is required, only network reachability to the deployment's
   API gateway.

Both paths ultimately hit the same info-endpoint route (`GET /process/asset`),
which enqueues a **priority** processing job for the selected plugin(s).

---

## Option 1 — Bulk folder reindex via the admin CLI

The admin CLI (`python -m usdsearch.admin.tools`) ships inside the
**info-endpoint** container. Its `reindex` command:

1. lists every asset under `--path` using the storage client that is already
   configured in the pod (Storage API / S3 / Nucleus, from the pod's env), then
2. fans out `GET /process/asset` calls to the info-endpoint (on `localhost:8000`
   in the same pod), one per asset, limited to the plugins you select.

Because both the listing and the processing calls happen inside the pod, **no
extra credentials are needed** — the pod already has storage access and the
endpoint is local.

### Requirements

- **`kubectl` access** to the cluster/namespace where USD Search is deployed
  (enough to `get pods` and `exec` into the info-endpoint pod).

### Command

Grab the info-endpoint pod name and run `reindex` inside it. Point `--path` at
the folder you want, and restrict processing to the dependency-graph plugin with
`--include_plugins`:

```bash
INFO_POD=$(kubectl get pods \
  -l deepsearch.service.name=info-endpoint \
  -o jsonpath='{.items[0].metadata.name}')

kubectl exec -i "$INFO_POD" -- python -m usdsearch.admin.tools reindex \
  --path=https://storageapistorageaccount.blob.core.windows.net/rc-bucket/Samples/PixarSamples/Kitchen_set/Kitchen_set/assets/Book/ \
  --endpoint_url=http://localhost:8000 \
  --include_plugins='["asset_graph_generation"]' \
  --ignore_existing_statuses=True
```

Adjust `--path` to your own storage URL. The scheme depends on the deployment's
storage backend (`s3://…`, `omniverse://…`, or an `https://…` Storage API URL).

### Key flags

| Flag | Purpose |
|---|---|
| `--path` | Storage folder to scan. Every supported asset under it is a candidate. |
| `--endpoint_url` | Info-endpoint base URL. Inside the pod this is `http://localhost:8000`. |
| `--include_plugins` | JSON list of plugin names to run. Use `'["asset_graph_generation"]'` for dependency-graph only. Omit to run every plugin that supports the asset. |
| `--ignore_existing_statuses` | `True` forces a refresh of **all** listed assets regardless of their current status. When omitted, the CLI first queries each asset's status and skips those already indexed. |
| `--exclude_statuses` | Statuses to skip when *not* ignoring existing statuses. Defaults to `[ok]` (skip already-OK assets). |
| `--asset_formats` | Restrict to extensions, e.g. `'["usd","usda","usdc"]'`. Defaults to all. |
| `--exclude_file_patterns` | `fnmatch` patterns to drop from the listing. |
| `--num_parallel_api_calls` | Max concurrent `/process/asset` calls (default `10`). |
| `--dry_run` | `True` prints the assets that *would* be reindexed (grouped by status) and exits without triggering anything. Handy to preview scope. |
| `--refresh_metadata` / `--refresh_tags` / `--refresh_plugins` | Whether to refresh asset metadata / tags / re-enqueue plugin jobs. Defaults: metadata `True`, tags `False`, plugins `True`. |

> **Tip:** run with `--dry_run=True` first to confirm the folder resolves to the
> assets you expect before enqueuing work.

### Verifying progress

Asset-graph builds are asynchronous. Poll the per-asset status endpoint until the
plugin reports `in_sync`:

```bash
kubectl exec -i "$INFO_POD" -- python - <<'PY'
import requests

url = "https://storageapistorageaccount.blob.core.windows.net/rc-bucket/Samples/PixarSamples/Kitchen_set/Kitchen_set/assets/Book/Book.usd"
resp = requests.get(
    "http://localhost:8000/info/indexing/asset/status",
    params={"url": url},
    headers={"accept": "application/json"},
    timeout=60,
)
resp.raise_for_status()
status = resp.json()["plugins_statuses"].get("asset_graph_generation", {})
print(url, "->", status.get("indexing_status"))
PY
```

`indexing_status` is one of `not_found`, `out_of_sync`, or `in_sync`; `in_sync`
means the dependency graph for that asset is fully built and up to date.

---

## Option 2 — Per-asset reindex via the HTTP API

If you cannot (or do not want to) `exec` into the cluster, you can drive the same
processing from any HTTP client. In this mode **you enumerate the asset URLs on
the client side** (from your own inventory, a storage listing you already have,
or the Storage API) and call `/process/asset` **once per asset**.

Both `/process` and `/info` are exposed through the deployment's **API gateway**,
so you only need the gateway's base URL (and any auth your deployment requires).

### Requirements

- **Network access** to the deployment's API gateway base URL (call it
  `$USDSEARCH_URL`), and any credentials/headers the gateway enforces.
- The list of **asset URLs** to process — produced client-side. There is no
  bulk "reindex this folder" HTTP endpoint; the folder-listing step is the CLI's
  job (Option 1), so here you supply the URLs yourself.

### Trigger processing for one asset

`GET /process/asset` enqueues a priority job. Restrict it to the dependency-graph
plugin with the repeatable `plugins` query parameter:

```bash
curl -G "$USDSEARCH_URL/process/asset" \
  --data-urlencode "url=s3://my-bucket/assets/Book/Book.usd" \
  --data-urlencode "plugins=asset_graph_generation" \
  --data-urlencode "refresh_plugins=true" \
  --data-urlencode "refresh_metadata=true" \
  --data-urlencode "priority=priority" \
  -H "accept: application/json"
```

Query parameters:

| Param | Default | Meaning |
|---|---|---|
| `url` | — (required) | Asset URL to submit for processing. Must exist on the backend. |
| `plugins` | all applicable | Repeat once per plugin to restrict which plugins run. Use `plugins=asset_graph_generation` for dependency-graph only. |
| `refresh_plugins` | `true` | Re-enqueue plugin processing jobs. |
| `refresh_metadata` | `false` | Refresh asset metadata from the backend. |
| `refresh_tags` | `false` | Refresh asset tags. |
| `priority` | `priority` | Job queue to use. |

The response reports the plugins that were `submitted` (and which were ignored
because they don't apply or aren't enabled).

### Loop over a client-side URL list

```python
import requests

BASE = "https://<your-usdsearch-gateway>"  # $USDSEARCH_URL

# URLs enumerated on the client side (your inventory, a storage listing, etc.)
urls = [
    "s3://my-bucket/assets/Book/Book.usd",
    "s3://my-bucket/assets/Book/Book.geom.usd",
    "s3://my-bucket/assets/Book/Book_payload.usd",
]

for url in urls:
    resp = requests.get(
        f"{BASE}/process/asset",
        params={
            "url": url,
            "plugins": "asset_graph_generation",
            "refresh_plugins": "true",
            "refresh_metadata": "true",
            "priority": "priority",
        },
        headers={"accept": "application/json"},
        timeout=300,
    )
    resp.raise_for_status()
    print("submitted:", url)
```

### Check status per asset

Same endpoint as Option 1, just through the gateway:

```bash
curl -G "$USDSEARCH_URL/info/indexing/asset/status" \
  --data-urlencode "url=s3://my-bucket/assets/Book/Book.usd" \
  -H "accept: application/json"
```

Poll until `plugins_statuses.asset_graph_generation.indexing_status == "in_sync"`.

---

## Which one should I use?

- **Reindex a whole folder / large batch** and you have cluster access →
  **Option 1** (the CLI does the listing and fan-out for you).
- **Reindex a known set of assets from outside the cluster**, or integrate
  reindexing into a client app → **Option 2** (enumerate URLs yourself, one
  `/process/asset` call per asset).

Both enqueue the same priority jobs; the only difference is *who lists the
assets* and *where the calls originate*.

---

## Reading back the dependency list

Once `asset_graph_generation` has processed an asset (`indexing_status ==
"in_sync"`), the resulting dependency graph is served by the **Asset Graph
Service (AGS)**. To get a **flat list of every file an asset depends on**
(references, payloads, textures, materials, …) use
`GET /dependency_graph/flat`. It is exposed through the API gateway under
`/dependency_graph`.

```bash
curl -G "$USDSEARCH_URL/dependency_graph/flat" \
  --data-urlencode "root_node_url=s3://my-bucket/assets/Book/Book.usd" \
  -H "accept: application/json"
```

Query parameters:

| Param | Default | Meaning |
|---|---|---|
| `root_node_url` | — (required) | The asset whose dependencies you want. |
| `max_level` | unlimited | Cap the depth of the dependency-tree traversal. `1` = only direct references. |
| `limit` | `1000` | Page size (max number of returned assets). |

The response is a JSON array of `Asset` objects, each with a `url` — i.e. the
flat set of files the root asset pulls in:

```json
[
  { "url": "s3://my-bucket/assets/Book/Book.geom.usd" },
  { "url": "s3://my-bucket/assets/Book/Book_payload.usd" },
  { "url": "s3://my-bucket/textures/paper_albedo.png" }
]
```

Extract just the URLs client-side:

```python
import requests

BASE = "https://<your-usdsearch-gateway>"  # $USDSEARCH_URL

resp = requests.get(
    f"{BASE}/dependency_graph/flat",
    params={"root_node_url": "s3://my-bucket/assets/Book/Book.usd"},
    headers={"accept": "application/json"},
    timeout=60,
)
resp.raise_for_status()
dependencies = [asset["url"] for asset in resp.json()]
print("\n".join(dependencies))
```

> **Requirements:** the deployment must have the Asset Graph Service enabled
> (`asset_graph_service_deployment.enabled=true`) and the root asset must already
> be indexed by `asset_graph_generation` (Option 1 or 2 above). A `404` means the
> asset is not yet in the graph.

**Related endpoints** (same `/dependency_graph` prefix and query params):

- `GET /dependency_graph/inverse/flat` — the reverse: a flat list of every scene
  or asset that **references** `root_node_url` ("where is this asset used?").
- `GET /dependency_graph/graph` and `.../inverse/graph` — the same relationships
  **with graph structure** (nodes + directed edges) instead of a flat list.
