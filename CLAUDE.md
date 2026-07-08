# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository. This file points
to the right skill for using the repo (searching, inspecting, deploying assets);
development work on the repo itself is covered by
[`docs/development.md`](docs/development.md).

## Searching for assets

When the user asks to find a 3D model, search assets, or get more like an
existing asset, use the `/search` skill at `skills/search/SKILL.md` (source of
truth; `.claude/skills` is a compat symlink -> `../skills`). It covers
text / image / hybrid search against `/search_hybrid` + `/images`, LLM query
parsing via `/llm_parse/query`, per-hit VLM validation, and thumbnail
inspection. Mirrors the codex-side pointer in `AGENTS.md`.

Other user-facing skills cover deploying the stack (`/deploy-usdsearch`, `/quickstart`), inspecting a single asset (`/inspect-asset`), and spatial / scene-graph queries (`/search-in-scene`). The harness lists every available skill at session start — invoke the relevant one rather than reimplementing its behavior.

To find out which USD properties a corpus actually carries (and turn that into
parser config), use the `/usd-property-catalog` skill at
`skills/usd-property-catalog/SKILL.md`: it reads `GET /search/stats/usd_properties`
and builds a local `usd_property_catalog.yaml` (the grounding source for the LLM
parser, via `USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH`) plus generated
`search_fields.yaml` stanzas, with a present/absent gap audit for target
properties.

## Developing this repository

**When you are working _on_ the repo itself** — building, testing, linting, debugging, editing source, touching Docker / Helm / CI / the compose stack, regenerating clients or third-party notices, or otherwise modifying the codebase — read **[`docs/development.md`](docs/development.md)** first.

It is the source of truth for development work and covers:

- **Key architecture** — package dependency order, workspace layout, generated clients, test-path conventions
- **Docker** — the combined `usdsearch` image, the other Dockerfiles, build/run, and implementation gotchas
- **Helm chart** — versioning (dual git-tag scheme), tests, CI, releasing a chart version
- **Quickstart compose stack** — base stack + overlays (web-ui, GPU, VLM, s3proxy-auth), gateway routes, smoke + e2e tests, storage-backend selection
- **Local filesystem backend** (s3proxy) and the MinIO alternative
- **Build / install / test / lint / pre-commit** workflows (uv workspace)
- **Third-party notices** — regenerating `THIRD_PARTY_NOTICE.md` and the bundled-OS-packages step
- **CI pipeline** — stages, per-package scripts, build/publish jobs, required secrets
- **Known pitfalls**, removed/deprecated backends, and known workspace limitations

Skip it when you are only *using* the repo's skills to search, inspect, or deploy assets on the user's behalf — that work needs only the skill pointers above.
