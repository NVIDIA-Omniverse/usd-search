# DeepSearch Rendering Job

USD asset rendering service powered by ovrtx.

## Run

```bash
pip install poetry==1.6.1
poetry install
./build.sh
docker build -t deepsearch-rendering-job:local .
```

**CLI mode:**
```bash
docker run -it --rm --gpus=all \
  deepsearch-rendering-job:local \
  https://omniverse-content-production.s3.us-west-2.amazonaws.com/Samples/OldAttic/Props/BookA.usd
```

**API mode:**
```bash
docker run -it --rm --gpus=all \
  -e MODE=api \
  -p 8000:8000 \
  deepsearch-rendering-job:local
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MODE` | `cli` | `api` for FastAPI server, `cli` for batch rendering |
| `LOAD_ASSET_AS_REFERENCE` | `True` | Load assets as USD references (strips embedded environments) |
| `RENDER_GROUND_PLANE` | `True` | Render Kit's grey floor under the asset (backdrop + contact shadow). Only the colour output shows it; depth, normals and the segmentation mask are captured without it |
| `RENDER_ADJUST_FRAMING` | `True` | Auto-frame each asset like Kit: centre the camera pivot on the asset's mask in a top and a side view, then zoom in until its largest side across the rendered views fills 75% of the view (moving out only if it is clipped). Measured from extra depth-only renders. A request can also opt out with `render_settings.adjust_camera_multiplier=false` |
| `OVRTX_SHADER_CACHE_DIR` | system temp | Parent dir for each render process's private ovrtx material cache, created per process and deleted afterwards. Never shared: ovrtx caches remote MDL materials by content and would reuse another asset's texture URLs |
| `RENDERING_SERVICE_SETTINGS_ASSET_RENDERING_TIMEOUT` | `1800` | Maximum rendering time per asset in seconds |

## Rendered views

Each asset is rendered from 8 orbit views (elevations 60° and 45°, four azimuths each). Like Kit, the
asset's own cameras are rendered too and come first. Their `camera_metadata` entries carry `prim_path`
and `deeptag_view_type: "stage"`, and Kit's `OmniverseKit_*` viewport cameras are skipped. A request
can opt out with `render_settings.render_existing_views=false`.

## Test locally

```bash
docker run -it --rm --gpus=all \
  -v "${PWD}":/deepsearch-rendering-job \
  -v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin \
  -u root --entrypoint=bash \
  deepsearch-rendering-job:local
```

Inside the container:
```bash
cd /deepsearch-rendering-job
python -m pip install "poetry<2"
python -m poetry config virtualenvs.create false
python -m poetry install --with main,test
python -m pytest ./tests/ -s -v -n 0
```
