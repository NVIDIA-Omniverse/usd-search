# USD Search documentation

This folder holds the reference documentation for USD Search. Start here to find
the right guide, whether you are *using* USD Search through an agent, *deploying*
the stack, or *developing* on the repo itself.

The top-level [`README.md`](../README.md) is the product overview; this index
points at the deeper docs.

## Using USD Search with an agent

USD Search ships agent skills that wrap search, inspection, and deployment as
interactive workflows. The skills live under [`skills/`](../skills/) — a single
source of truth shared by **Claude** and **Codex Desktop** (`.claude/skills` and
`.codex/skills` are compat symlinks to it). Invoke them with `/` in Claude or
`$` in Codex.

- [Agent Desktop search guide](agent-desktop/search/README.md) — install the
  skills and run text / image / hybrid searches against the public hosted
  instance. The simplest end-to-end path.
- [Agent skills overview](agent-skills.md) — the full Claude + Codex skill set
  and the first-time user journey.

| Skill | Use it for |
|---|---|
| `search` | Find USD assets by text, image, or both. |
| `quickstart` | Pick a backend and run a first search. |
| `inspect-asset` | Deep-dive one asset URL: thumbnails, metadata, scene structure, indexing status, and dependencies. |
| `search-in-scene` | Query inside a USD scene: prims, proximity, bounding boxes, hierarchy, and dependencies. |
| `deploy-usdsearch` | Run USD Search locally with Docker Compose or on Kubernetes with Helm. |
| `usd-property-catalog` | Discover which USD properties a deployment can filter on. |

## Search quality & filters

- [Search filters](search-filters.md) — discover and enable the metadata filters
  your deployment can apply to plain-language queries.
- [USD-property catalog](usd-property-catalog.md) — build the catalog that
  grounds the LLM query parser on the USD properties your corpus actually
  carries.
- [VLM result validation](vlm-validation.md) — how a Vision Language Model
  double-checks each search result against the query.
- [Search research playbook](search_research_playbook.md) — run retrieval
  experiments and evaluate ranking changes rigorously.
- [Search inside scenes](../services/asset-graph/README.md) — the Asset Graph
  Service: spatial, property, and forward/reverse dependency queries within a
  single scene.

## Deploying & operating

- [Local deployment recipes](local-deployment.md) — configuration recipes for
  running the stack against public S3, custom S3, or Nucleus, with or without
  GPU/VLM plugins.
- [Helm chart](../helm/usdsearch/README.md) — Kubernetes installation of the
  full stack.
- [Container images & the Explorer](containers.md) — what each published image
  is, how it is built, and where it is pushed.
- [Models & configuration](models-and-config.md) — the shared OpenAI-compatible
  LLM/VLM connection and per-role model selection.
- [Configuration map](configuration-map.md) — one table from each feature to the
  file that defines it and the env var that overrides it.
- [`openapi.html`](openapi.html) — rendered REST API reference.

## Beta features

- [Beta features](beta.md) — early-access previews whose interfaces may still
  change.
- [Asset download](asset-download.md) — download an asset with all its
  dependencies as a self-contained bundle (beta).

## Developing on this repo

- [Development guide](development.md) — the source of truth for building,
  running, testing, and modifying USD Search from source: architecture, Docker,
  Helm, the quickstart compose stack, CI, and known pitfalls. It also covers
  **maintaining the agent skills and these docs** (update checklist, public-safety
  rules, skill-discovery paths).
- [Search-quality benchmark](../benchmark/README.md) — the agent-driven benchmark
  for evaluating retrieval quality.
