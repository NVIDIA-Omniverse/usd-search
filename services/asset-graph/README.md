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

## Developer guide

### Workspace install

This service is a `uv` workspace member. From the repo root:

```bash
uv sync --package asset-graph-service
```

(See the [main CLAUDE.md](../../CLAUDE.md#build-and-install) for the
mandatory `./build/build_search_utils.sh` pre-step.)
