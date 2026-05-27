#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

#
#
#
# USDSearch quickstart — agent-free entry point.
#
# Mirrors the `/quickstart` Claude Code skill but runs as plain bash, so
# users who don't have Claude Code installed can still get to a working
# 3D-asset search in seconds.
#
# Asks one question — "where do you want to search?" — with three lanes:
#   1) NVIDIA-hosted    (zero setup, public dev endpoint)
#   2) Your own URL     (you already have USDSearch running)
#   3) Local            (brings up the docker compose stack on this box)
#
# Then prompts the user for a query (with example suggestions), runs that
# query against the chosen endpoint, and prints what to do next.

set -eu

# ───────────────────────── helpers ─────────────────────────

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }
warn()  { printf '\033[33m%s\033[0m\n' "$*"; }
err()   { printf '\033[31m%s\033[0m\n' "$*" >&2; }
ok()    { printf '\033[32m%s\033[0m\n' "$*"; }

need() {
    command -v "$1" >/dev/null 2>&1 || { err "missing required tool: $1"; exit 1; }
}

ask_choice() {
    # ask_choice "Prompt" default a b c …  →  echoes the chosen letter
    local prompt=$1; shift
    local default=$1; shift
    local i=1 choice
    printf '%s\n' "$prompt" >&2
    for opt in "$@"; do
        printf '  %d) %s\n' "$i" "$opt" >&2
        i=$((i+1))
    done
    printf 'Choice [%s]: ' "$default" >&2
    read -r choice </dev/tty || choice=
    [ -z "$choice" ] && choice=$default
    printf '%s' "$choice"
}

probe_url() {
    # returns 0 if URL responds with any HTTP status, 1 if unreachable
    curl -fsSL --max-time 5 -o /dev/null -w '%{http_code}' "$1" >/dev/null 2>&1 \
        || curl -sSL --max-time 5 -o /dev/null -w '%{http_code}' "$1" >/dev/null 2>&1
}

sample_search() {
    # Runs a tiny text search and prints the first few hits as proof.
    # Assumes the unified API gateway is in front of $USD_SEARCH_API_URL.
    local query=$1
    local path=/search_hybrid
    bold "Running sample query: \"$query\""
    local body
    body=$(cat <<EOF
{
  "hybrid_text_query": "$query",
  "vector_queries": [{
    "field_name": "siglip2-embedding.embedding",
    "query_type": "text",
    "query": "$query"
  }],
  "file_extension_include": "usd*",
  "limit": 5,
  "scoring_config": {
    "rrf_config": {"rank_constant": 60},
    "hybrid_text": {
      "enabled": true, "weight": 1.0, "cross_field_operator": "or",
      "fields": [
        {"field":"name","weight":2,"match_type":"fuzzy","wildcard":true},
        {"field":"path","weight":1,"match_type":"fuzzy","wildcard":true}
      ]
    },
    "vector_fields": {
      "siglip2-embedding.embedding": {
        "enabled": true, "weight": 1,
        "field_name": "siglip2-embedding.embedding", "dimension": 1536
      }
    }
  }
}
EOF
)
    local resp
    resp=$(curl -sS --max-time 30 -X POST \
        -H 'content-type: application/json' \
        ${AUTH_HEADER:+-H "$AUTH_HEADER"} \
        -d "$body" \
        "${USD_SEARCH_API_URL}${path}" || true)

    if ! printf '%s' "$resp" | grep -q '"hits"'; then
        warn "Sample query returned no usable response. The endpoint is up but the index may still be warming."
        dim "Raw response (first 200 chars): $(printf '%s' "$resp" | head -c 200)"
        return 1
    fi

    local resp_file
    resp_file=$(mktemp)
    printf '%s' "$resp" > "$resp_file"
    python3 - "$resp_file" <<'PY' || true
import json, sys
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    print(f"  (could not parse response: {e})")
    sys.exit(0)
hits = data.get("hits", []) if isinstance(data, dict) else []
if not hits:
    print("  (0 hits — index may still be warming)")
    sys.exit(0)
print(f"  Got {len(hits)} hits:")
for i, h in enumerate(hits[:5], 1):
    src = h.get("source", {})
    name = src.get("base_key") or src.get("name") or src.get("url") or "?"
    score = h.get("score") or h.get("rrf_score") or 0.0
    print(f"  {i:>2}. score={score:.3f}  {name}")
PY
    rm -f "$resp_file"
}

print_next_steps() {
    cat <<EOF

$(bold "What just happened")
You ran a hybrid SigLIP2 (vision) + OpenSearch (keyword) search against:
  $USD_SEARCH_API_URL

$(bold "Next steps")
  • Try another query:
      USD_SEARCH_API_URL=$USD_SEARCH_API_URL $0 --query "yellow forklift"
  • Open the Swagger docs in a browser:
      ${USD_SEARCH_API_URL%/}/docs/
  • Open the Explorer web UI (local deployments only):
      http://localhost:8080/ui/
  • Use it from Claude Code for an agent-driven experience:
      /search "yellow forklift"

EOF
}

# ───────────────────────── flags ─────────────────────────

QUERY_OVERRIDE=""
LANE_OVERRIDE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --query)      QUERY_OVERRIDE=$2; shift 2 ;;
        --hosted)     LANE_OVERRIDE=1; shift ;;
        --own)        LANE_OVERRIDE=2; shift ;;
        --local)      LANE_OVERRIDE=3; shift ;;
        -h|--help)
            cat <<'EOF'
USDSearch quickstart — agent-free entry point.

Usage:
  scripts/quickstart.sh                  interactive
  scripts/quickstart.sh --hosted         use the public NVIDIA dev endpoint
  scripts/quickstart.sh --own            connect to USD_SEARCH_API_URL (must be set)
  scripts/quickstart.sh --local          docker compose up + sample query
  scripts/quickstart.sh --query "..."    run a query non-interactively (skips the prompt)

Environment honoured by --own:
  USD_SEARCH_API_URL                     URL of an existing USDSearch instance
  USD_SEARCH_API_TOKEN                   optional Bearer token
  USD_SEARCH_API_USERNAME / _PASSWORD    optional HTTP Basic auth
EOF
            exit 0 ;;
        *) err "unknown flag: $1"; exit 2 ;;
    esac
done

need curl
need python3

# ───────────────────────── lane pick ─────────────────────────

cat <<'EOF'

  ╔════════════════════════════════════════════════════════════╗
  ║              USDSearch — quickstart (no agent)             ║
  ║   semantic search for OpenUSD / 3D assets · SigLIP2 + RAG  ║
  ╚════════════════════════════════════════════════════════════╝

EOF

if [ -z "$LANE_OVERRIDE" ]; then
    LANE_OVERRIDE=$(ask_choice "Where do you want to search?" 1 \
        "NVIDIA-hosted   (zero setup, public dev endpoint — recommended)" \
        "Your own URL    (you already have USDSearch running somewhere)" \
        "Local           (bring up the full stack on this machine via docker compose)")
fi

case "$LANE_OVERRIDE" in
    1)
        USD_SEARCH_API_URL=${USD_SEARCH_API_URL:-https://search.simready.omniverse.nvidia.com}
        bold "→ Using NVIDIA-hosted endpoint: $USD_SEARCH_API_URL"
        if ! probe_url "$USD_SEARCH_API_URL"; then
            warn "Could not reach $USD_SEARCH_API_URL — it may be down or require VPN."
            warn "Falling through anyway; the sample query will surface the real error."
        fi
        AUTH_HEADER=""
        ;;
    2)
        if [ -z "${USD_SEARCH_API_URL:-}" ]; then
            printf 'USD_SEARCH_API_URL (e.g. http://my-host:8080): ' >&2
            read -r USD_SEARCH_API_URL </dev/tty
        fi
        [ -n "${USD_SEARCH_API_URL:-}" ] || { err "no URL given"; exit 1; }
        export USD_SEARCH_API_URL
        bold "→ Using your endpoint: $USD_SEARCH_API_URL"
        AUTH_HEADER=""
        if [ -n "${USD_SEARCH_API_TOKEN:-}" ] && [ "$USD_SEARCH_API_TOKEN" != "x" ]; then
            AUTH_HEADER="Authorization: Bearer $USD_SEARCH_API_TOKEN"
        elif [ -n "${USD_SEARCH_API_USERNAME:-}" ] && [ -n "${USD_SEARCH_API_PASSWORD:-}" ]; then
            b64=$(printf '%s' "$USD_SEARCH_API_USERNAME:$USD_SEARCH_API_PASSWORD" | base64)
            AUTH_HEADER="Authorization: Basic $b64"
        fi
        if ! probe_url "$USD_SEARCH_API_URL"; then
            err "Could not reach $USD_SEARCH_API_URL — check the URL and your network."
            exit 1
        fi
        ;;
    3)
        bold "→ Local deployment via docker compose"
        need docker
        if ! docker compose version >/dev/null 2>&1; then
            err "docker compose v2 not found. Install Docker Desktop or the docker-compose-plugin package."
            exit 1
        fi
        REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
        cd "$REPO_ROOT"
        dim "Working dir: $REPO_ROOT"

        # GPU detection — default is GPU plugins (GPU-accelerated SigLIP2
        # + the renderer). Fall back to the base stack (SigLIP2 on CPU, no
        # renderer) when no NVIDIA GPU is visible on the host.
        COMPOSE_FILES=(-f docker-compose.yml -f docker-compose.gpu-plugins.yml)
        if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
            dim "NVIDIA GPU detected — bringing up GPU-accelerated SigLIP2 + renderer (GPU plugins overlay)."
        else
            warn "No NVIDIA GPU detected (nvidia-smi missing or failed)."
            warn "Falling back to the base stack: SigLIP2 runs on CPU (slower indexing) and the renderer is not included."
            warn "Install nvidia-container-toolkit + a GPU and re-run to enable the GPU plugins overlay."
            COMPOSE_FILES=(-f docker-compose.yml)
        fi

        dim "This first build can take 10–25 minutes depending on bandwidth."
        dim "Subsequent starts take ~60s."
        printf 'Bring up the stack now with `docker compose %s up -d --build`? [Y/n]: ' "${COMPOSE_FILES[*]}" >&2
        read -r yn </dev/tty || yn=
        case "${yn:-Y}" in
            n|N|no|No) err "Aborting — re-run when ready."; exit 1 ;;
        esac
        docker compose "${COMPOSE_FILES[@]}" up -d --build
        USD_SEARCH_API_URL=http://localhost:8080
        export USD_SEARCH_API_URL
        AUTH_HEADER=""
        bold "Waiting for the gateway to become healthy…"
        for i in $(seq 1 60); do
            if probe_url "$USD_SEARCH_API_URL/docs/"; then
                ok "Gateway is up after ${i}0s."
                break
            fi
            sleep 10
            printf '.' >&2
        done
        printf '\n' >&2
        if [ -x ./scripts/quickstart-smoke.sh ]; then
            dim "Running scripts/quickstart-smoke.sh to verify endpoints…"
            ./scripts/quickstart-smoke.sh || warn "Smoke had failures — services may still be warming. Re-run in ~60s."
        fi
        bold "Want custom S3, local-FS assets, VLM tagging, or GPU plugins on top? See docs/local-deployment.md"
        ;;
    *)
        err "unknown lane: $LANE_OVERRIDE"; exit 2 ;;
esac

export USD_SEARCH_API_URL

# ───────────────────────── sample query ─────────────────────────

if [ -z "$QUERY_OVERRIDE" ]; then
    cat >&2 <<'EOF'

What do you want to search for?

  Examples:  blue forklift
             industrial robot arm
             robot
             apple
             spoon
             humanoid

EOF
    printf 'Query (blank to skip): ' >&2
    read -r QUERY_OVERRIDE </dev/tty || QUERY_OVERRIDE=
fi

if [ -n "$QUERY_OVERRIDE" ]; then
    sample_search "$QUERY_OVERRIDE" || true
else
    dim "No query entered. Re-run any time with: $0 --query \"<your query>\""
fi

print_next_steps
