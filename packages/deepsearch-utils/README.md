# deepsearch-utils

Plugin-support utilities shared by the DeepSearch monitor workers and other
USD Search services. Sits one layer above `search-utils` and depends on
`ngsearch-storage` and `vision-endpoint`.

## What's inside

| Module | Purpose |
|---|---|
| `farm/`, `farm_utils.py` | Async websocket client + helpers for submitting rendering / asset-graph jobs to the DeepSearch farm. |
| `rendering_service/`, `rendering_utils.py` | HTTP client for `services/rendering-job` (the renderer is **not** a workspace member and is called over HTTP — see [CLAUDE.md](../../CLAUDE.md#known-workspace-limitations) for why). |
| `k8s_renderer/` | Kubernetes-side helpers for routing render requests inside the Helm-deployed stack. |
| `image_processing_utils.py` | Thumbnail + EXR utilities (uses `pytinyexr` on Linux). |
| `ds_plugin_utils.py`, `models.py` | Plugin job models and shared helpers consumed by `services/deepsearch-monitor` plugin workers. |
| `secure_pickle.py`, `misc_utils.py` | Misc shared helpers. |

## Install

This package is a `uv` workspace member. Install via:

```bash
uv sync --package deepsearch-utils
```

## Notable constraints

- Pins `websockets~=10.4`. `services/rendering-job` needs `websockets>=12.0`,
  which is why the renderer cannot be a workspace member and is reached over
  HTTP — see [Known Workspace Limitations](../../CLAUDE.md#known-workspace-limitations).
- `pytinyexr` is Linux-only and only required when working with HDR EXR
  thumbnails.
