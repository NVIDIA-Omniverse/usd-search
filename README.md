# USDSearch

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

USDSearch is a semantic search stack for OpenUSD and 3D asset libraries.
It crawls asset storage, generates visual embeddings + VLM-based metadata,
indexes the results, and serves them through a search API and web UI.

<p align="center">
  <img src="docs/quickstart-user-journey.svg" alt="USDSearch /quickstart — first-time user journey" width="100%">
</p>

- 🔎 **Semantic Search** — natural-language or image-based queries over USD assets, renders, and reference images.
- 🧠 **Multimodal Embeddings** — uses SigLIP2 to project images and text into a shared embedding space for efficient search.
- 🏷️ **Automatic Tagging** — VLMs caption every asset and generate searchable metadata during ingestion. The metadata schema (caption, tags, materials, style, …) is fully configurable.
- ✅ **Result Validation** — VLM-as-a-judge filters noisy matches so results stay visually relevant.
- ☁️ **Automatic Discovery** — crawls the storage backend of your choice (S3, Storage API, Nucleus) to index assets at scale.

## Agent-driven quickstart (recommended)

| Claude Code | Codex | What it does |
|---|---|---|
| [`/quickstart`](.claude/skills/quickstart/SKILL.md) | [`$quickstart`](.codex/skills/quickstart/SKILL.md) | Pick a backend (NVIDIA-hosted / your URL / local) and get to a first asset in ~2 seconds. |
| [`/search`](.claude/skills/search/SKILL.md) | [`$search`](.codex/skills/search/SKILL.md) | Hybrid text + image search over the index; saves top-5 VLM-validated thumbnails to `./search-results/`. |
| [`/inspect-asset`](.claude/skills/inspect-asset/SKILL.md) | [`$inspect-asset`](.codex/skills/inspect-asset/SKILL.md) | Deep-dive one asset URL: thumbnails, indexing status, scene structure, dependencies, VLM relevance. |
| [`/search-in-scene`](.claude/skills/search-in-scene/SKILL.md) | [`$search-in-scene`](.codex/skills/search-in-scene/SKILL.md) | Spatial / scene-graph queries inside a USD: radius, bounding box, prim-type filters, where-used. |
| [`/deploy-usdsearch`](.claude/skills/deploy-usdsearch/SKILL.md) | [`$deploy-usdsearch`](.codex/skills/deploy-usdsearch/SKILL.md) | Stand up a local docker compose stack or Helm deployment, then hand back to `/quickstart`. |

Open this repo in your agent of choice and type:

```bash
/quickstart
```

You will be asked `Where do you want to search?` — your request is then handed off to `/search`.

## Shell quickstart (secondary, no agent required)

If Claude Code isn't an option, `scripts/quickstart.sh` mirrors the same three lanes in bash and ends with a sample query:

```bash
./scripts/quickstart.sh                         # interactive, three lanes
./scripts/quickstart.sh --hosted                # public NVIDIA dev endpoint
USD_SEARCH_API_URL=... ./scripts/quickstart.sh --own
./scripts/quickstart.sh --local                 # docker compose up + sample query
./scripts/quickstart.sh --query "yellow forklift"
```

This path is a convenience — it can't do VLM validation, image input, or the follow-on `/inspect-asset` / `/search-in-scene` flows. For anything beyond a sanity check, use the agent path above. Requires `bash`, `curl`, and `python3`; the local lane also needs `docker compose` v2.

## Standing up your own deployment

If you want to run USDSearch yourself — either on this laptop or on a Kubernetes cluster — use:

```
/deploy-usdsearch
```

`/deploy-usdsearch` ([`.claude/skills/deploy-usdsearch/SKILL.md`](.claude/skills/deploy-usdsearch/SKILL.md)) branches once between **local docker compose** (full stack at the repo root: opensearch, redis, deepsearch-api, info-endpoint, asset-graph, embedding workers behind an nginx gateway at `http://localhost:8080`, with the Explorer WebUI as an optional overlay) and **Helm on Kubernetes** (the chart at `helm/usdsearch/`). Both branches walk through storage backend (Public S3 / Custom S3 / Nucleus), GPU plugins, VLM plugins, WebUI, and credentials — accepting **env-var names only**, never raw secrets. After the stack is healthy and `./scripts/quickstart-smoke.sh` passes, control returns to `/quickstart` so you can immediately fetch an asset against your own deployment.

---

## Plain docker compose (no agent)

The agent path above wraps the same docker compose stack that's defined at the repo root. The default deployment runs **SigLIP2 on GPU** (via Triton) and the **GPU-accelerated renderer enabled** — bring it up directly with:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu-plugins.yml up -d --build
```

Requires an NVIDIA GPU on the host and `nvidia-container-toolkit` configured. To run without a GPU (SigLIP2 on CPU, no renderer), drop the `-f docker-compose.gpu-plugins.yml` flag.

Open **http://localhost:8080** — the nginx gateway routes `/` to the Explorer UI, `/docs/` to the bundled Swagger docs, and the search / info / asset-graph APIs to their backing services. After it reports healthy (~60s), `./scripts/quickstart-smoke.sh` exercises every gateway-proxied endpoint.

For configuration recipes — custom S3 bucket, local-filesystem assets, or VLM auto-tagging — see [`docs/local-deployment.md`](docs/local-deployment.md).

---

## Build from source

For developers working on USD Search itself. To deploy or run the service, use one of the paths above.

See [`docs/development.md`](docs/development.md) for prerequisites, the editable-install steps (`build_search_utils.sh`, `build_pytinyexr.sh`, `uv sync`) and repository layout details.

---

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Third-party
component licenses are listed in [THIRD_PARTY_NOTICE.md](THIRD_PARTY_NOTICE.md).

## Contributing

This project is currently not accepting contributions. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Please report security vulnerabilities per the policy in
[SECURITY.md](SECURITY.md).

## Code of Conduct

This project adheres to the Contributor Covenant Code of Conduct. See
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
