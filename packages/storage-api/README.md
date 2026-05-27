# storage-api

In-repo Python gRPC client bindings for:

- **Omniverse Storage API** — `nvidia.omniverse.storage.{capabilities,filefolder,fileobject,metadata,versioning}.{v1alpha,v1beta}`
- **Omniverse Notifications Consumer API** — `nvidia.omniverse.notifications.consumer.v1beta`

This package replaces the `omniverse-storage-grpc-python` and `omniverse-notifications-grpc-python` wheels previously pulled from the buf PyPI registry. The generated `_pb2.py`, `_pb2_grpc.py`, and `_pb2.pyi` files are committed under `nvidia/` and shipped as the wheel.

## Layout

```
packages/storage-api/
├── protos/                 # source .proto files (committed)
│   └── nvidia/omniverse/
├── nvidia/                 # generated Python output (committed, packaged)
│   └── omniverse/
└── scripts/
    └── storage-api-grpc-client-generate.py
```

## Regenerating

When the protos are bumped, replace the contents of `protos/nvidia/` with the new tree, then:

```bash
uv run --package storage-api python packages/storage-api/scripts/storage-api-grpc-client-generate.py
```

The script wipes and re-emits the entire `nvidia/` Python tree under this package; review the diff before committing.

## Proto sources

Initial import: `storage-api v1.0.0-beta.4` and `notifications-consumer-api v1.0.0-beta-1`. The reference archives sit (gitignored) under `_protos/` at the repo root.
