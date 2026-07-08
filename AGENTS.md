# USD Search workspace

This is the consolidated USD Search / Omniverse asset-search repo
(see `docs/development.md` for the full project map, architecture, and
per-package guidance, and `CLAUDE.md` for skill-usage pointers).
Skills live under `skills/` — the single source
of truth, shared with Claude; `.codex/skills` is a compat symlink →
`../skills`. Each `SKILL.md` is a self-contained workflow. The bodies
are written agent-neutrally; the **Codex runtime notes** below say how
to map the generic verbs onto Codex's runtime.

## Skills

| Skill | Path | What it does |
|---|---|---|
| `/search` | `skills/search/SKILL.md` | Text / image / hybrid search against `/search_hybrid` + `/images`, with `is_match` validation, the per-hit VLM validator, and thumbnail inspection via `codex exec --image`. Persists results to `./search-results/<slug>/`. |
| `/quickstart` | `skills/quickstart/SKILL.md` | First-time entry point. Picks one of three backend lanes (NVIDIA-hosted, your own URL, local deployment), sets `USD_SEARCH_API_URL`, then hands off to `/search` with a seed query. |
| `/inspect-asset` | `skills/inspect-asset/SKILL.md` | Deep-dive a single asset: thumbnails from multiple angles, indexing status, USD scene-graph (prims, polygons, MPU), dependencies, and a full report. |
| `/search-in-scene` | `skills/search-in-scene/SKILL.md` | Spatial / scene-graph queries against the Asset Graph Service: proximity, bounding-box, prim enumeration and filtering, dependency graphs. |
| `/deploy-usdsearch` | `skills/deploy-usdsearch/SKILL.md` | Stand up USD Search yourself. Branches on local docker-compose vs. Helm on Kubernetes; covers storage backend, GPU plugins, VLM plugins, smoke tests. |
| `/usd-property-catalog` | `skills/usd-property-catalog/SKILL.md` | Discover which USD properties a corpus carries via `GET /search/stats/usd_properties`; build a local `usd_property_catalog.yaml` (grounds the LLM parser) + `search_fields.generated.yaml`, with a present/absent gap audit for target properties. |

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

The skill bodies are agent-neutral. Map their generic verbs onto Codex
like this:

- **"`/deploy-usdsearch` Bash commands"** → run on the host system,
  not inside the Codex sandbox. Request host execution/escalation before
  running its Docker, Compose, GPU, NVIDIA runtime, or Kubernetes
  checks; the sandbox can hide the Docker daemon, GPU devices, and
  host kube context, producing false negatives.
- **"Inspect / view the thumbnails visually"** → run
  `codex exec --image <path>` — the recursive-model pattern shown in
  `skills/search/SKILL.md`. Don't try to inline image bytes into a
  prompt.
- **"Ask the user (a structured question)"** → ask a normal clarifying
  prompt. Codex has no picker widget or arrow-key selection. Treat
  `Header`, `Options`, `picker`, and `one-click` language in skills as
  UI metadata: preserve the choice semantics, but render them as a
  lettered or numbered list and tell the user to type the letter, short
  name, or their own free-form answer. Use the skill's option labels
  and descriptions exactly as written; do not shorten, reword, or
  summarize them. If a skill groups options with labels like
  `[Group] Name`, prefer plain group headings in Codex instead of
  showing the bracketed prefixes, but keep the remaining label and the
  full description verbatim. Never add an explicit "Other" option just
  to support free-form input.
- **"Hand off to the `<name>` skill"** → follow
  `skills/<name>/SKILL.md` in this same session. Preserve any branch
  choice already made by the caller (for example `/quickstart` →
  `deploy-usdsearch` with Local deployment selected), and load any
  runbook/reference file the target skill tells you to read before
  returning to the caller.
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
