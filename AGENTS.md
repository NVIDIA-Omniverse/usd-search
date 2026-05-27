# USD Search workspace

This is the consolidated USD Search / Omniverse asset-search repo
(see `CLAUDE.md` for the full project map, architecture, and
per-package guidance). Codex skills live under `.codex/skills/`;
each `SKILL.md` is a self-contained workflow.

## Skills

| Skill | Path | What it does |
|---|---|---|
| `/search` | `.codex/skills/search/SKILL.md` | Text / image / hybrid search against `/search_hybrid` + `/images`, with `is_match` validation, the per-hit VLM validator, and thumbnail inspection via `codex exec --image`. Persists results to `./search-results/<slug>/`. |
| `/quickstart` | `.codex/skills/quickstart/SKILL.md` | First-time entry point. Picks one of three backend lanes (NVIDIA-hosted, your own URL, local deployment), sets `USD_SEARCH_API_URL`, then hands off to `/search` with a seed query. |
| `/inspect-asset` | `.codex/skills/inspect-asset/SKILL.md` | Deep-dive a single asset: thumbnails from multiple angles, indexing status, USD scene-graph (prims, polygons, MPU), dependencies, and a full report. |
| `/search-in-scene` | `.codex/skills/search-in-scene/SKILL.md` | Spatial / scene-graph queries against the Asset Graph Service: proximity, bounding-box, prim enumeration and filtering, dependency graphs. |
| `/deploy-usdsearch` | `.codex/skills/deploy-usdsearch/SKILL.md` | Stand up USD Search yourself. Branches on local docker-compose vs. Helm on Kubernetes; covers storage backend, GPU plugins, VLM plugins, smoke tests. |

When the user asks to find a 3D model, search assets, or get more
like an existing asset, start with `/search`. When they want a
guided first-time tour, start with `/quickstart`. When they want to
host their own stack, start with `/deploy-usdsearch`.

## Conventions

- **Python tooling:** `uv` (never pip/poetry).
- **Be terse.** No preamble, no per-command narration — the user
  reads tool output directly.
- **Indirect credentials only.** Before asking for any `*_API_KEY`,
  AWS key, NGC token, or password, grep `~/.zshrc ~/.zshenv
  ~/.zprofile ~/.profile ~/.bashrc ~/.bash_profile ~/.env*` for
  `export <NAME>=`. If absent, ask the user to `export` it
  themselves and pass back only the **name** of the env var. Never
  accept a pasted secret value.
- **Assume the unified API gateway is in front of every request.**
  Use the unversioned routes (`/search_hybrid`, `/images`, `/info/...`,
  `/asset_graph/...`, `/dependency_graph/...`) for everything. The
  Info Endpoint and Asset Graph Service are internal interfaces;
  never address them directly.

## Codex runtime notes

- **Visual inspection.** Thumbnails and renders are inspected via
  `codex exec --image <path>` — the same recursive-model pattern
  shown in `.codex/skills/search/SKILL.md`. Don't try to inline image
  bytes into a prompt.
- **Working directory is sticky-per-call.** Each `bash` invocation
  starts fresh — `cd` does not persist. Use absolute paths or chain
  with `&&` inside a single call. Files persist between calls; only
  the shell state resets.
- **Scratch artifacts.** Stable, agent-shared output goes under
  `./search-results/<slug>/` (skill manifests + thumbnails). Truly
  ephemeral debug artifacts go under `/tmp/`. Never write secrets to
  either.
- **Cross-skill state.** Skills chain through the filesystem — a
  `manifest.json` written by `/search` is read by `/inspect-asset`
  and `/search-in-scene` without re-querying.
