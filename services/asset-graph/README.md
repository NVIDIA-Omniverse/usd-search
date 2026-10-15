# Asset Graph Service

The **Asset Graph Service (AGS) API** provides advanced querying capabilities for assets and USD trees indexed in a graph database. It supports proximity queries based on coordinates or prims to find objects within specified areas or radii, sorted by distance, and includes transformation options for vector alignment. The API also offers dependency and reverse dependency searches, helping to identify all assets referenced in a scene or scenes containing a particular asset, which can optimize scene loading and track dependency changes. By combining different query types, the AGS API enables complex scenarios for scene understanding, manipulation, and generation. It can also be integrated with DeepSearch to provide in-scene search functionality.

## Features

- **Proximity Queries:**
  - Find objects within a specified bounding box or radius.
  - Results sorted by distance with options for vector alignment using a transformation matrix.

- **USD Property Queries:**
  - Enables querying objects in a 3D scene using USD properties, such as finding all assets with a specific semantic label.

- **Asset Dependency Searches:**
  - Identify all assets referenced in a scene - including USD references, material references, or textures.
  - Reverse search to find all scenes containing a particular asset.

- **Combined Query Capabilities:**
  - Enable complex scenarios for enhanced scene understanding, manipulation, and generation.

- **Integration with DeepSearch:**
  - Provides in-scene search functionality.

## User Guide

To use the Asset Graph Service, deploy it as part of USD Search using the
[`usdsearch` Helm chart](../../helm/usdsearch/README.md) or the quickstart
compose stack at the repo root (the service comes up automatically as part
of the base stack). The graph itself is populated by
`services/deepsearch-monitor`'s `asset_graph_generation` worker; AGS only
serves queries against an already-populated graph.

### Python API client

The generated Python client lives in the workspace at
[`packages/asset-graph-client`](../../packages/asset-graph-client/). It is
auto-generated from this service's OpenAPI spec via
`openapi-python-client`; **do not hand-edit**. See that package's README
for regeneration instructions and SPDX-header re-application.

Consumers depend on it as a workspace package, e.g.:

```toml
asset-graph-client = { workspace = true }
```

## Admin tools

Maintenance tools live in the shared admin CLI
([`packages/usdsearch`](../../packages/usdsearch/usdsearch/admin/tools/)), which
ships in the same image. The ones below read the graph, so they run from the
asset-graph-service pod — that is where `db_uri`, `db_username` and `db_password`
are set — and refuse to start anywhere else. `python -m usdsearch.admin.tools --help`
lists the rest.

### Repair percent-encoded asset URLs

Graphs built before `graph_url` (`services/asset-graph-builder`) can hold an
`:Asset` keyed by a percent-encoded URL while storage holds the raw object key,
so downloads silently drop the layer and reverse-dependency lookups come back
empty. This renames those nodes, merging into the existing node where one
already holds the decoded URL:

```bash
kubectl exec -it deploy/<release>-asset-graph-service -- \
    python -m usdsearch.admin.tools migrate_url_spellings           # report only
kubectl exec -it deploy/<release>-asset-graph-service -- \
    python -m usdsearch.admin.tools migrate_url_spellings --apply --reindex
```

Reporting is the default and `--apply` is required to write. Back it up first —
it rewrites primary keys. Run it before or with the inbound percent-decoding in
`search_utils.url_mapping`: once the API decodes incoming URLs, an encoded node
is unreachable by any spelling except through `/download/asset`'s own fallback.

`--reindex` resubmits every migrated asset for the `asset_graph_generation`
plugin, so the node is rebuilt rather than just re-keyed. It goes through the
same `/process/asset` client as the `reindex` command. The endpoint comes from
`--endpoint_url`, else `INFO_ENDPOINT_URL` (which the chart sets from
`asset-graph-service.infoEndpointURL`), else `http://localhost:8000`. A failed
submission is named in the log and does not stop the rest — re-running the
migration will not retry it, because that node no longer looks encoded, so
resubmit those with `reindex`.

Flags: `--limit N` stops after N nodes, `--verbose` lists every node instead of
a sample of ten.

## Developer guide

### Workspace install

This service is a `uv` workspace member. From the repo root:

```bash
uv sync --package asset-graph-service
```

(See the [main CLAUDE.md](../../CLAUDE.md#build-and-install) for the
mandatory `./build/build_search_utils.sh` pre-step.)
