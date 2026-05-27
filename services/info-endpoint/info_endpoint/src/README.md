# Info / Process endpoint

FastAPI service that exposes storage-backend introspection and on-demand
asset indexing. Mounted behind the nginx gateway in the quickstart stack
at `/info` and `/process` (see
[`infra/quickstart/gateway.conf`](../../../../infra/quickstart/gateway.conf)).

Entrypoint: `info_endpoint.src.main:app` (run via `uvicorn`).

## Routes

* **Storage backend operations**
    * `GET /info` — list and describe the storage backend(s) USD Search
      is connected to.

* **Asset operations** — for a given asset URL, one of:
    * Status check — report the per-plugin processing status (embedding,
      thumbnail, asset-graph generation, etc.).
    * `POST /process/asset` — trigger on-demand indexing so the asset is
      processed ahead of items already queued in the background.
      `services/fs-watcher` calls this for each new or changed file when
      the local-filesystem compose overlay is active.

* **Plugins** — retrieve the list of indexing plugins supported by
  USD Search.

The on-demand `/process` jobs are enqueued with `job_type="priority"`.
Every monitor worker that should drain them must include `priority` in
its `DEEPSEARCH_MONITOR_WORKER_CONFIG_JOB_ITEM_TYPE` — the default
(`["normal","none"]`) silently filters priority jobs out. See the
[Known Pitfalls](../../../../CLAUDE.md#known-pitfalls) entry.
