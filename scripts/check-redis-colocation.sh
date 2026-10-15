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

# Show which nodes the search REST API and Redis pods landed on, and whether
# they share one.
#
# WHY THIS MATTERS: Redis holds the RRF ranking cache, which every paged search
# reads and every first page writes. Cross-node, those are network round trips
# on the request path. The chart asks for co-location with a *preferred* pod
# affinity (ngsearch/templates/deployment_search_rest_api.yaml) — preferred, not
# required, so the scheduler is free to ignore it when a node is full. This
# script is how you find out whether it actually got what it asked for.
#
# Co-location is an optimisation, never a correctness property: a split
# deployment is slower, not broken. So the exit code is 0 either way unless
# --strict is passed.
#
# Usage:
#   ./scripts/check-redis-colocation.sh [-n NAMESPACE] [--strict]
#
# Flags:
#   -n, --namespace NS  Namespace to inspect (default: the kubectl context's).
#       --strict        Exit non-zero when any API pod is NOT on a Redis node,
#                       for use in a deployment check.
#   -h, --help          Show this help text.

set -euo pipefail

NAMESPACE=""
STRICT=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="${2:-}"; shift 2 ;;
    --namespace=*) NAMESPACE="${1#*=}"; shift ;;
    --strict) STRICT=true; shift ;;
    -h|--help)
      sed -n '17,39p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "ERROR: unknown argument '$1' (try --help)" >&2; exit 2 ;;
  esac
done

KUBECTL_ARGS=()
[[ -n "$NAMESPACE" ]] && KUBECTL_ARGS+=(--namespace "$NAMESPACE")

CONTEXT="$(kubectl config current-context 2>/dev/null || echo '<none>')"
NS_LABEL="${NAMESPACE:-$(kubectl config view --minify -o jsonpath='{..namespace}' 2>/dev/null || true)}"
echo "context: ${CONTEXT}    namespace: ${NS_LABEL:-default}"
echo

# Pending pods have no .spec.nodeName; print a placeholder rather than a blank
# column, so "not scheduled yet" is visibly different from "scheduled somewhere".
PODS="$(
  kubectl get pods "${KUBECTL_ARGS[@]}" --no-headers \
    -o custom-columns='NODE:.spec.nodeName,POD:.metadata.name,PHASE:.status.phase' 2>/dev/null \
    | grep -E 'search-rest-api|redis' \
    | awk '{ if ($1 == "<none>" || $1 == "") $1 = "(unscheduled)"; print }' \
    | sort || true
)"

if [[ -z "$PODS" ]]; then
  echo "No search-rest-api or redis pods found." >&2
  echo "Matching is by pod name, so a chart rename would also look like this." >&2
  exit 1
fi

printf '%s\n' "$PODS" | column -t
echo

# Verdict. Redis pods define the "good" nodes; every API pod is then checked
# against that set.
printf '%s\n' "$PODS" | awk -v strict="$STRICT" '
  { if ($2 ~ /redis/) redis_node[$1] = 1; else api_node[$2] = $1 }
  END {
    total = 0; together = 0
    for (pod in api_node) {
      total++
      if (api_node[pod] in redis_node) together++
    }
    if (total == 0) {
      print "No search REST API pods found — only Redis."
      exit 0
    }
    if (together == total) {
      printf "OK: all %d search REST API pod(s) share a node with Redis.\n", total
      exit 0
    }
    printf "SPLIT: %d of %d search REST API pod(s) share a node with Redis.\n", together, total
    print "  The ranking-cache read on every paged search crosses the network for the rest."
    print "  Affinity is preferred, not required, so this is legal — check node capacity,"
    print "  and note that with more API replicas than Redis nodes it is unavoidable."
    exit (strict == "true" ? 1 : 0)
  }
'
