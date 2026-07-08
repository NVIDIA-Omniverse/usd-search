---
name: quickstart
license: Apache-2.0
version: 3.0.0
description: |
  Get a first-time user to a real 3D asset in seconds. Asks one
  question — "where do you want to search?" — with three backend
  lanes (NVIDIA-hosted default, your own URL, or a local deployment),
  then hands off to /search for the actual query. The journey is the
  SVG at docs/quickstart-user-journey.svg: Stage 1 (entry) + Stage 2
  (backend pick), then /search drives Stages 3-5.
  Use when: "quickstart", "try usd search", "show me what this does",
  "getting started", "what is usd search", "tour", "first time".
triggers:
  - quickstart
  - try usd search
  - show me what this does
  - getting started
  - what is usd search
  - tour
  - first time
allowed-tools: AskUserQuestion, Bash, Read, Skill
---

# /quickstart — discover USD Search

Your job is the **first two stages** of `docs/quickstart-user-journey.svg`:

1. Open the journey, ask "where do you want to search?"
2. Pick one of three backend lanes, set `USD_SEARCH_API_URL`.

Then hand off to `/search` — it runs Stages 3 (query) → 4 (hybrid
search) → 5 (ranked results) per the diagram.

**Be terse.** No preamble, no per-step narration. The user reads the
tool output. Two prompts max — one for the backend, one for the
search query (which `/search` will collect).

## Step 1 — Ask "where do you want to search?"

Ask the user once (a single structured question). Three options —
these match the three lanes in `docs/quickstart-user-journey.svg`:

- **"NVIDIA-hosted"** — zero setup, the default
  lane in the diagram. Set
  `USD_SEARCH_API_URL=https://search.simready.omniverse.nvidia.com`.
  Public NVIDIA dev deployment; answers unauthenticated requests. Proceed to Step 2.
- **"Your own deployment"** — the user already has a USD Search
  instance. Ask for the **name** of a shell env var holding the URL
  (and optionally a token / Basic auth pair). Never accept a pasted
  secret. Probe `curl ${URL}/info/backend/storage`; on non-200, ask
  for a different var or fall back to the NVIDIA-hosted default.
- **"Local deployment"** — one-command setup. Hand off to the
  `deploy-usdsearch` skill with **"Locally with docker compose"**
  already selected. The deploy skill must run its Local branch,
  including L1 pre-flight and `references/local-runbook.md` L2-L6,
  before returning. When it returns it will have set
  `USD_SEARCH_API_URL` for you. Then proceed to Step 2.

## Step 2 — Hand off to /search with a seed query

Hand off to the `search` skill with a suggested seed query. Offer
four one-click nouns plus an "Other" escape so the "I don't know what
to try" path is one click and a specific request is exact:

- **"a chair"**
- **"a robot"**
- **"a warehouse"**
- **"a vehicle"**
- *Other* — free-text (e.g. "yellow leather armchair")

The `/search` skill takes it from there: builds the hybrid query,
saves five thumbnails to `./search-results/<slug>/`, writes a
`manifest.json`, and inspects the JPEGs visually.

Do **not** auto-pick the query — the single most personal thing this
journey does is reflect the user's own words back as a 3D asset.

## Step 3 — Print the "now you can…" list

After `/search` returns, end with a short pointer list (not a question):

- `/search` — refine with a different query, image, or filter
- `/inspect-asset` — deep-dive a single result
- `/search-in-scene` — spatial / scene-graph queries
- `/deploy-usdsearch` — run USD Search yourself

The manifest at `./search-results/<slug>/manifest.json` lets these
skills pick up where you left off.

## Important rules

- **Two prompts max.** Q1 (backend) + Q2 (query, asked by `/search`).
- **Never auto-pick the search query.**
- **Check the env before asking for keys.** Before prompting for any
  `*_API_KEY` or URL token, grep `~/.zshrc ~/.zshenv ~/.zprofile
  ~/.profile ~/.bashrc ~/.bash_profile ~/.env*` for `export <NAME>=`.
  If absent, ask the user to `export` it themselves — never accept a
  pasted secret.
- **Indirect credentials.** When asking for a URL or token, accept
  only the **name** of a shell env var that already holds the value.
- **Three lanes, not four.** Match the SVG: NVIDIA-hosted (default),
  your own URL, local deployment. No fourth "I have an OpenSearch
  index" branch — that's an advanced flow that lives in
  `/deploy-usdsearch` if it's ever needed.
- **Hand off, don't reimplement.** `/search` owns the query, the
  scoring config, the thumbnail fetch, the visual verification. This
  skill only chooses the backend.
