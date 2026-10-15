<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Asset-graph build failures

When the asset-graph plugin cannot build a graph for an asset, it records *why*
as the asset's per-plugin status. A crawl can therefore report a breakdown —
"3% ran out of memory, 0.2% are missing" — instead of one opaque failure rate.

## Reason codes

| Status | Meaning | Usual fix |
|---|---|---|
| `graph_construction_oom` | Kit exceeded the memory watchdog, or was OOM-killed by the kernel | Raise `kit_worker.resources.limits.memory` (and `memory_limit_mb` with it) |
| `graph_construction_timeout` | The build exceeded its wall-clock limit | Raise `kit_worker.timeout_seconds` |
| `graph_construction_open_layer_failed` | The asset is readable but the stage would not open (malformed layer, unresolvable sublayer) | Fix the asset |
| `graph_construction_asset_not_found` | The storage backend reports the asset does not exist | Stale index entry, or a bad crawl path |
| `graph_construction_access_denied` | The storage backend rejected the credentials, or could not be reached | Check the backend credentials |
| `graph_construction_kit_crashed` | Kit exited non-zero without classifying the failure itself | Inspect the kit-worker logs |
| `graph_construction_service_unavailable` | The kit-worker sidecar was unreachable or restarted mid-request | Often a symptom of an OOM elsewhere in the batch — check sidecar restarts |
| `graph_construction_failed` | Unclassified — the catch-all | Inspect the kit-worker logs |
| `graph_storage_failed` | The graph was built but rejected by the Asset Graph Service | Inspect the AGS response in the worker logs |

`graph_construction_failed` predates the other values and is kept as the
catch-all, so anything matching on it still sees the unclassified tail.

## Where to see them

**Per asset** — `GET /indexing/status` returns `plugin_status_history` for each
plugin, with the status and the underlying error message:

```bash
curl "$USDSEARCH_URL/indexing/status?url=s3://bucket/asset.usd"
```

**In aggregate** — the plugin workers export a Prometheus counter, labelled by
the status they assigned:

```
omnideepsearch_worker_item_status_total{plugin_name="asset_graph_generation", status="graph_construction_oom"}
```

The metric is generic, so the same query shape gives a per-status breakdown for
any plugin, not just asset-graph.

## Build timings

Every build reports where its time went, on the `X-Graph-Build-Timings` response
header of `POST /construct_graph/`:

```json
{
  "kit_startup_ms": 8421.5,
  "phases": {"storage_registration": 12.0, "stage_open": 900.0, "traverse": 12000.0, "traverse_recursive": 8800.0},
  "died_in": null,
  "total_ms": 30120.0
}
```

- `kit_startup_ms` is the gap between the service spawning Kit and the exec
  script's first instruction — the per-build cold start, and the number that
  decides whether keeping Kit warm is worth doing. It cannot be measured from
  inside Kit or from the service alone, only across the two.
- `died_in` names the phase a killed build was in when it died. A build that is
  OOM- or timeout-killed writes no graph document, so this is the only account of
  where it got to.

The kit-worker logs the same breakdown as one line per build (`Graph build
timings for <url>: ...`), and the AGS plugin attaches it to its per-asset
`asset_graph_generation.get_graph` span as `graph_build.*` attributes. Note that
trace collection is off unless `global.tracing.OTEL_TRACES_EXPORTER` is enabled,
so the log line is what most deployments will read. That line is `INFO`, and the
sidecar takes its level from the chart's `loggingConfig` like every other
component — raise `loggers.root.level` above `INFO` and it goes away.

**In aggregate** — the plugin workers export the same numbers as Prometheus
histograms, one series per phase, plus a counter for the phase a killed build
died in:

```
omnideepsearch_worker_phase_duration_seconds{plugin_name="asset_graph_generation", phase="kit_startup"}
omnideepsearch_worker_item_failure_phase_total{plugin_name="asset_graph_generation", phase="traverse_recursive"}
```

`phase` takes the keys of `phases` above plus `kit_startup` and `total`, so the
cold-start share of a crawl is one query — `kit_startup` over `total`. Both
metrics are generic: a plugin that measures its own phases reports them the same
way. Two caveats when reading them: builds whose sidecar died mid-request never
send the header, so they are counted by
`omnideepsearch_worker_item_status_total{status="graph_construction_service_unavailable"}`
and not here; and durations are in seconds, while the header is in milliseconds.

Timings are recorded to their own file inside the Kit container, appended and
flushed per phase, precisely so that a `SIGKILL` — which cannot be trapped —
still leaves everything up to the kill.

## Why OOM is worth configuring for

A container OOM-kill is invisible to the service being killed: the kernel takes
the process and the in-flight request's connection with it, leaving nothing to
report. That is why the graph builder has a **soft** memory watchdog
(`kit_worker.memory_limit_mb`) set *below* the container's hard limit — it kills
Kit first, so the asset that could not fit gets a
`graph_construction_oom` status naming it, and the sidecar keeps serving.

Leave `memory_limit_mb` unset and the kernel stays solely in charge: builds that
exceed the limit still fail, but as `graph_construction_service_unavailable` on
whichever asset happened to be in flight.

See the "Asset Graph Service additional settings" section of the chart README
for how to size the sidecar and set the build timeout.
