# Agent skills

This repo ships agent skills for Claude Code and Codex that wrap the
search, inspection, and deployment workflows interactively. They are
entirely optional — every path in the main [README](../README.md) works
without them.

<p align="center">
  <img src="quickstart-user-journey.svg" alt="USD Search /quickstart — first-time user journey" width="80%">
</p>

| Claude Code | Codex | What it does |
|---|---|---|
| [`/quickstart`](../.claude/skills/quickstart/SKILL.md) | [`$quickstart`](../.codex/skills/quickstart/SKILL.md) | Pick a backend (NVIDIA-hosted / your URL / local) and get to a first asset. |
| [`/search`](../.claude/skills/search/SKILL.md) | [`$search`](../.codex/skills/search/SKILL.md) | Hybrid text + image search over the index; saves top-5 VLM-validated thumbnails to `./search-results/`. |
| [`/inspect-asset`](../.claude/skills/inspect-asset/SKILL.md) | [`$inspect-asset`](../.codex/skills/inspect-asset/SKILL.md) | Deep-dive one asset URL: thumbnails, indexing status, scene structure, dependencies, VLM relevance. |
| [`/search-in-scene`](../.claude/skills/search-in-scene/SKILL.md) | [`$search-in-scene`](../.codex/skills/search-in-scene/SKILL.md) | Spatial / scene-graph queries inside a USD: radius, bounding box, prim-type filters, where-used. |
| [`/deploy-usdsearch`](../.claude/skills/deploy-usdsearch/SKILL.md) | [`$deploy-usdsearch`](../.codex/skills/deploy-usdsearch/SKILL.md) | Stand up a local docker compose stack or Helm deployment, then hand back to `/quickstart`. |

Open this repo in your agent of choice and type one of the slash / dollar
commands above. With an agent active in the repo you can also skip the
explicit command and ask in plain language ("find a yellow forklift",
"more like this beverage") — the agent dispatches the right skill.

**About `/deploy-usdsearch`:** branches once between **local docker
compose** and **Helm on Kubernetes**, then walks through storage backend
(Public S3 / Custom S3 / Nucleus), GPU plugins, VLM plugins, WebUI, and
credentials — accepting **env-var names only**, never raw secrets. After
the stack is healthy and
[`./scripts/quickstart-smoke.sh`](../scripts/quickstart-smoke.sh) passes,
control returns to `/quickstart` so you can immediately fetch an asset
against your own deployment.
