---
name: deploy-usdsearch
license: Apache-2.0
version: 2.0.0
description: |
  Stand up a USD Search deployment the user controls. Branches on
  local docker-compose vs. helm on Kubernetes. Local branch covers
  the full quickstart compose stack with GPU/VLM/storage-backend
  questionnaires. Helm branch covers the usdsearch chart at
  helm/usdsearch.
  Use when: "deploy usdsearch", "run the stack myself", "helm install
  usdsearch", "start the stack", "run usdsearch locally", "host my own".
triggers:
  - deploy usdsearch
  - deploy usd search
  - run the stack
  - start the stack
  - install usdsearch
  - helm install usdsearch
  - run locally
  - host my own
allowed-tools: AskUserQuestion, Bash, Read
---

# /deploy-usdsearch — stand up USD Search yourself

Branch once between **local docker-compose** and **helm on Kubernetes**,
then execute the matching runbook. Both branches end at "healthy and
smoke-tested" and set `USD_SEARCH_API_URL` so the calling skill (usually
`/quickstart`) can resume.

If the user only wants to *use* USD Search and doesn't care about
hosting it, redirect them to `/quickstart`.

**Be terse.** No preamble, no per-step narration, no recap of what you
just did. The user reads the tool output. Before asking for any
`*_API_KEY`, grep `~/.zshrc ~/.zshenv ~/.zprofile ~/.profile
~/.bashrc ~/.bash_profile ~/.env*` for `export <NAME>=` — if absent,
ask the user to `export` it themselves; never accept a pasted secret.

## Step 0 — Ask local vs helm

If this skill was invoked by `/quickstart` after the user selected
**"Local deployment"**, treat **"Locally with docker compose"** as
already selected and proceed directly to the **Local** runbook. Do not
ask this question again.

Ask the user once (a single structured question):

- **"Locally with docker compose"** — fastest, runs on
  a developer laptop. Proceed to the **Local** runbook below.
- **"Helm on Kubernetes"** — production-shaped. Requires a cluster
  with GPU nodes. The published USD Search images on
  `nvcr.io/nvidia/usdsearch` are publicly pullable — no NGC API key
  needed for the default install. Proceed to the **Helm** runbook.

---

# Local runbook (docker compose)

You are bringing up the full USD Search stack on this machine via the
top-level compose files at the repo root. Run the L1 pre-flight below,
then follow `references/local-runbook.md` for configuration and launch.

## L1: Pre-flight checks

Run all checks in a single Bash call. Each line of output is `KEY=VALUE`
so you can parse it directly:

```bash
# Docker CLI
if command -v docker >/dev/null 2>&1; then
  echo "DOCKER=ok ($(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,))"
else
  echo "DOCKER=missing"
fi

# Compose variant (prefer v2)
if docker compose version >/dev/null 2>&1; then
  echo "COMPOSE=docker compose ($(docker compose version --short 2>/dev/null))"
elif command -v docker-compose >/dev/null 2>&1; then
  echo "COMPOSE=docker-compose ($(docker-compose version --short 2>/dev/null))"
else
  echo "COMPOSE=missing"
fi

# Combined image
if docker image inspect usdsearch:latest >/dev/null 2>&1; then
  echo "IMAGE=ok ($(docker image inspect usdsearch:latest --format '{{.Size}}' | awk '{printf "%.1f GB", $1/1024/1024/1024}'))"
else
  echo "IMAGE=missing"
fi

# Git LFS — siglip2-triton image build COPYs ~7.2 GB ONNX weights from
# services/siglip2-triton/model_repo/ which are LFS-tracked. Without
# `git lfs pull`, the build silently succeeds with 134-byte pointer
# files and SigLIP2 fails at runtime.
if ! command -v git >/dev/null 2>&1; then
  echo "GIT_LFS=git-missing"
elif ! git lfs version >/dev/null 2>&1; then
  echo "GIT_LFS=missing (install git-lfs, then run 'git lfs install && git lfs pull')"
else
  total=$(git lfs ls-files 2>/dev/null | wc -l)
  pointers=$(git lfs ls-files 2>/dev/null | awk '$2=="-"' | wc -l)
  if [ "$total" -eq 0 ]; then
    echo "GIT_LFS=no-tracked-files"
  elif [ "$pointers" -gt 0 ]; then
    echo "GIT_LFS=not-pulled (${pointers}/${total} files are pointers; run 'git lfs pull')"
  else
    echo "GIT_LFS=ok (${total} files fetched)"
  fi
fi

# GPU
if nvidia-smi >/dev/null 2>&1; then
  echo "GPU=yes ($(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1))"
else
  echo "GPU=no"
fi

# Already-running quickstart containers
running=$(docker ps --filter "name=usdsearch-" --format '{{.Names}}' 2>/dev/null | wc -l)
echo "STACK_RUNNING=${running}"
```

**Display a summary table** to the user from the parsed output. Use this
markdown shape — `✓` present/ready, `⚠` missing-but-recoverable,
`✗` blocker:

```markdown
| Check          | Status | Detail                                  |
|----------------|--------|-----------------------------------------|
| Docker         | ✓      | 27.3.1                                  |
| Compose        | ✓      | docker compose v2.29.7                  |
| usdsearch:latest image | ✓ | 0.4 GB                               |
| Git LFS        | ✓      | 14 files fetched                        |
| GPU            | ✓      | NVIDIA RTX A6000                        |
| Stack running  | ✓      | not running                             |
```

After printing the table, branch on the results:

- **Docker or Compose missing (`✗`):** Stop. Tell the user what to install.
- **Image missing (`⚠`):** Show the build command and ask whether to
  build now (run in background) or skip:
  ```
  docker build --platform linux/amd64 \
    -f docker/Dockerfile.usdsearch -t usdsearch:latest .
  ```
- **Git LFS missing or `not-pulled` (`✗`):** Stop. The siglip2-triton
  image build needs the ONNX weights at
  `services/siglip2-triton/model_repo/`. Without them the image builds
  with 134-byte pointer files and SigLIP2 fails at runtime. Tell the
  user to run:
  ```
  git lfs install
  git lfs pull
  ```
  Re-run the L1 checks after they're done.
- **GPU missing (`⚠`):** GPU plugins are automatically skipped —
  CPU-mock mode is the only option.
- **Stack already running (`STACK_RUNNING > 0`):** List the running
  containers and ask whether to leave them, restart (`down` then `up`),
  or just `up` over the top to reconcile changes.

### L1 Troubleshooting

If Docker-related checks fail, branch on the symptom:

- **Daemon won't start (no systemd):** On GKE-kernel or container-
  optimized hosts where `systemctl` is absent, `get.docker.com` installs
  Docker but the daemon never starts. Fallback:
  ```bash
  sudo dockerd &>/tmp/dockerd.log &
  ```
  For persistence across reboots: `@reboot sudo dockerd &>/tmp/dockerd.log`.

- **`permission denied` on `/var/run/docker.sock`:** The current user is
  not in the `docker` group. Fix:
  ```bash
  sudo usermod -aG docker "$USER"
  ```
  Then start a **new shell session** (group membership doesn't take
  effect in the current shell). Alternatively, prefix all docker commands
  with `sudo`.

- **NVIDIA runtime not found after `nvidia-ctk runtime configure`:**
  The running dockerd must be **fully restarted** (not just SIGHUP'd)
  for the nvidia runtime to be picked up. `kill -HUP` is insufficient.
  ```bash
  sudo systemctl restart docker        # systemd hosts
  sudo kill $(cat /var/run/docker.pid) && sudo dockerd &>/tmp/dockerd.log &  # no-systemd hosts
  ```
  Verify: `docker info | grep -i nvidia` should show the runtime.

## L2–L6: configure and launch

Once L1 is green, **read `references/local-runbook.md` and follow it**.
It covers, in order:

- **L2 — Storage backend.** The five-option structured question (Public
  S3 / Custom S3 / Local filesystem / Storage API / Nucleus),
  crawler-scope follow-up, per-backend credential handling, the s3proxy
  auth-proxy rule for custom endpoints + GPU, and the Nucleus Basic-Auth
  gateway gotcha.
- **L3 — GPU plugins.** Enabled by default when L1 detected a GPU; do
  not ask. Only skip on no-GPU or explicit user request.
- **L4 — VLM plugins.** Optional metadata generation; provider +
  API-key-env-var-name questions.
- **L4.5 — Explorer WebUI.** Optional React front-end overlay.
- **L5 — Build the compose command.** Env-var and `-f` overlay tables,
  the final `docker compose … up -d --build` pattern, and the rule to
  reuse the exact invocation prefix for every later command.
- **L6 — Health check + smoke.** `quickstart-smoke.sh`, the
  failure-triage list, and the Prometheus deep-diagnostics probes.

---

# Helm runbook (Kubernetes)

You are installing the `usdsearch` Helm chart at `helm/usdsearch/`.
**Read `references/helm-runbook.md` and follow it.** It covers, in order:

- **H1 — Verify prerequisites** (cluster, GPU nodes, Helm 3+,
  backend connection details, PV capacity; public NGC images need no
  pull secret).
- **H2 — Storage backend + required information** (four-option backend
  pick — Public S3 / Custom S3 / Storage API / Nucleus, no Local
  filesystem — then per-backend follow-ups and namespace).
- **H3 — Optional features** (VLM labeling / validation, Asset Graph
  Service, per-job vs. persistent rendering mode).
- **H4 — Build dependencies** (`helm dependency update`).
- **H5 — Secrets + values file** (secret-by-name pattern, the
  `my-usdsearch-config.yaml` template, persistent-renderer opt-in block,
  private-registry block).
- **H6–H8 — Dry-run, install, verify, and set `USD_SEARCH_API_URL`.**
- **Helm source-of-truth + troubleshooting tables.**

---

# Important rules (both branches)

- **Indirect credentials — never ask the user to paste secret values.**
  Whenever the stack needs a credential (AWS keys, Nucleus passwords,
  VLM API keys, private-registry tokens), accept only the **name** of
  an env var that already holds the secret. Validate with a
  length/prefix check (`printf 'len=%d prefix=%s\n' "${#VAR}"
  "${VAR:0:4}"`) and never print more than the first 4 characters.
- **Never print secrets in full.**
- **Use the detected docker compose variant** (`docker compose` vs
  `docker-compose`) consistently.
- **Always show the full, copy-pasteable command.** Every follow-up
  docker compose action must include the same `-f <overlay>` chain
  and env vars used to bring the stack up.
- **Don't block on image builds.** Run them in the background.
- **The minimal local config (Public S3 + CPU + no VLM)** works with
  zero configuration: `docker compose up -d --build`.
- **On success, set `USD_SEARCH_API_URL`** (`http://localhost:8080`
  locally, the port-forward URL for helm) and return control to the
  caller. The user's next step is almost always `/quickstart` (which
  in turn hands off to `/search`) so they can actually use the
  deployment.
- **After indexing, ground query parsing on the real corpus** — run
  `/usd-property-catalog` to discover which USD properties your assets
  carry and wire the result into the parser (`.llm_parsing.property_catalog`
  / `.llm_parsing.fields`). See the LLM-query-parsing entry in
  `references/helm-runbook.md`.
