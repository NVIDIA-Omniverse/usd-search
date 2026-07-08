# storage-api

In-repo Python gRPC client bindings for:

- **Omniverse Storage API** — `nvidia.omniverse.storage.{capabilities,filefolder,fileobject,metadata,versioning}.{v1alpha,v1beta}`
- **Omniverse Notifications Consumer API** — `nvidia.omniverse.notifications.consumer.v1beta`

This package replaces the `omniverse-storage-grpc-python` and `omniverse-notifications-grpc-python` wheels previously pulled from the buf PyPI registry. The generated `_pb2.py`, `_pb2_grpc.py`, and `_pb2.pyi` files are committed under `nvidia/` and shipped as the wheel.

The `.proto` sources are **not** vendored here — they are fetched on demand from the public [`NVIDIA-Omniverse/ovstorage`](https://github.com/NVIDIA-Omniverse/ovstorage) repo at generation time (see [Regenerating](#regenerating)).

## Layout

```
packages/storage-api/
├── nvidia/                 # generated Python output (committed, packaged)
│   └── omniverse/
└── scripts/
    └── storage-api-grpc-client-generate.py
```

## Regenerating

The generator downloads the proto sources from `NVIDIA-Omniverse/ovstorage` at a configurable git ref (tag, branch, or commit SHA; default `v0.1.0`), then wipes and re-emits the entire `nvidia/` Python tree. Review the diff before committing.

```bash
# Default ref (v0.1.0):
uv run --package storage-api python packages/storage-api/scripts/storage-api-grpc-client-generate.py

# Pin a different ref:
uv run --package storage-api python packages/storage-api/scripts/storage-api-grpc-client-generate.py --ref v0.2.0
# or via env var:
STORAGE_API_PROTO_REF=main uv run --package storage-api python packages/storage-api/scripts/storage-api-grpc-client-generate.py

# Offline: generate from an already-extracted local proto root:
uv run --package storage-api python packages/storage-api/scripts/storage-api-grpc-client-generate.py --proto-root /path/to/proto/root
```

`--repo` (default `NVIDIA-Omniverse/ovstorage`) overrides the source repository.

## Proto sources

Fetched from two include subtrees in `NVIDIA-Omniverse/ovstorage` (default ref `v0.1.0`), merged under a shared `nvidia/omniverse/...` namespace:

| Upstream subtree | Contributes |
|---|---|
| `ovstorage-services/apis/storage-api/proto/` | `nvidia/omniverse/storage/{capabilities,filefolder,fileobject,metadata,versioning}/...` |
| `ovstorage-services/apis/notifications-api/consumer/protos/` | `nvidia/omniverse/notifications/consumer/v1beta/event_consumer.proto` |
