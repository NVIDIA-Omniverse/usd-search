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

# Codex-driven release smoke for USDSearch.
#
# This does not duplicate the API smoke with raw curl calls. It builds a
# Codex prompt that walks the deploy, search, and inspect skills
# end-to-end against a local compose deployment, then either prints the
# prompt or shells out to `codex exec`. Codex-only by design — for a
# raw-curl smoke see scripts/quickstart-smoke.sh.

set -eu

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

usage() {
    cat <<'EOF'
Usage:
  scripts/codex-smoke.sh [--print] [--run] [--allow-docker-socket] [--query "warehouse forklift"]

Default:
  --print    Print the codex exec command and agent prompt.

Options:
  --run      Execute codex exec with the generated prompt.
  --allow-docker-socket
             Run the nested Codex agent without sandboxing so it can
             access Docker. Required for a real local compose deploy in
             sandboxed Codex environments.
  --query    Search query for the agentic /search step.

Safe defaults:
  - local docker compose lane only
  - Public S3 sample content
  - no VLM metadata
  - no secrets
EOF
}

MODE=print
ALLOW_DOCKER_SOCKET=${AGENTIC_SMOKE_ALLOW_DOCKER_SOCKET:-0}
QUERY=${AGENTIC_SMOKE_QUERY:-"warehouse forklift"}

while [ $# -gt 0 ]; do
    case "$1" in
        --print)
            MODE=print
            shift
            ;;
        --run)
            MODE=run
            shift
            ;;
        --allow-docker-socket)
            ALLOW_DOCKER_SOCKET=1
            shift
            ;;
        --query)
            [ $# -ge 2 ] || { echo "missing value for --query" >&2; exit 2; }
            QUERY=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

PROMPT=$(cat <<EOF
You are the tester agent for the USDSearch release-readiness smoke.

Run a fully agentic end-to-end smoke against the local compose stack. Do
not ask for, accept, paste, print, or store any secrets. Do not use Helm.
Do not reduce this to raw API curl checks; the point is to verify that
the agent skills drive the workflow.

Required flow:
1. Use the /deploy-usdsearch skill for the local docker compose lane.
   Choose the no-secret defaults: Public S3 sample content, the smaller
   Isaac branch, GPU plugins only if automatically detected by the
   skill, and no VLM metadata.
2. Wait for the local gateway to be healthy. Use the deploy skill's
   smoke guidance, but keep going only when the stack is ready enough
   for agent search.
   If usdsearch containers are already running, do not ask what to do:
   leave them in place and run the compose up -d --build command to
   reconcile the local no-secret lane. If existing containers block the
   gateway from becoming healthy, mark the smoke failed and include the
   blocker in the report.
3. Set USD_SEARCH_API_URL=http://localhost:8080 for downstream skills.
4. Use the /search skill for this query: "${QUERY}". Save results under
   ./search-results/ as the skill normally does, including thumbnails
   and manifest.json.
5. Pick the best visually valid hit from the search manifest and use
   the /inspect-asset skill on its asset URL. The inspect step must
   fetch thumbnails, check indexing status, attempt scene/dependency
   data, and produce a concise report.
6. Write the final smoke report to
   ./search-results/codex-smoke/latest-report.md with:
   - deployment lane and URL
   - search query
   - chosen asset URL
   - paths to manifest and thumbnails
   - inspect summary
   - commands or skill invocations used
   - pass/fail and unresolved risks

If docker compose is unavailable, the stack fails to start, or the index
does not return a usable asset after reasonable warmup, mark the smoke
failed and include the blocker in the report. Do not tear down the stack
unless it is clearly necessary to recover from a failed partial start.
EOF
)

case "$MODE" in
    print)
        cat <<EOF
Run the agentic smoke with:

$REPO_ROOT/scripts/codex-smoke.sh --run --allow-docker-socket --query "$QUERY"

Prompt:

$PROMPT
EOF
        ;;
    run)
        if ! command -v codex >/dev/null 2>&1; then
            echo "codex CLI not found" >&2
            exit 1
        fi
        cd "$REPO_ROOT"
        CODEX_ARGS=(exec --skip-git-repo-check --cd "$REPO_ROOT")
        if [ "$ALLOW_DOCKER_SOCKET" = "1" ]; then
            CODEX_ARGS+=(--dangerously-bypass-approvals-and-sandbox)
        fi
        codex "${CODEX_ARGS[@]}" -- "$PROMPT"
        ;;
esac
