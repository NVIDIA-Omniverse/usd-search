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

# Smoke tests for the USD Search quickstart stack.
# Exercises every gateway-proxied API and reports PASS/FAIL.
# Exit code: 0 if all critical tests pass, 1 otherwise.
#
# Usage:   ./scripts/quickstart-smoke.sh
# Env:
#   BASE=http://localhost:8080    override gateway URL
#   ASSET_GRAPH_TIMEOUT=15        max seconds to wait for the AGS worker to
#                                 graph a scene (section 7). Polled every 5s.
#   VLM_VALIDATION_TIMEOUT=60     max seconds to wait for a single VLM
#                                 validation call (section 8). Reasoning
#                                 models can take 30s+ per request.
#   BASIC_AUTH=user:password      optional HTTP Basic Auth for every curl
#                                 call. Set when the gateway proxies a
#                                 backend that gates the APIs (e.g. when
#                                 STORAGE_BACKEND_TYPE=nucleus). Empty by
#                                 default — anonymous access.
#   WEB_UI=on|off                 whether the docker-compose.web-ui.yml
#                                 overlay was included when starting the
#                                 stack. Controls section-1 assertions:
#                                   off (default): GET / → 302 /docs/;
#                                                  /ui/ check skipped.
#                                   on:            GET / → 302 /ui/;
#                                                  /ui/ must return 200.
#   LOCAL_FS_MODE=on|off          whether the docker-compose.local-fs.yml
#                                 overlay was included. When on, section 9
#                                 asserts that the LocalFSPathMiddleware
#                                 rewrote every s3:// URI out of /search
#                                 and /search_hybrid responses. Skipped
#                                 when off (default).

set +e
BASE=${BASE:-http://localhost:8080}
ASSET_GRAPH_TIMEOUT=${ASSET_GRAPH_TIMEOUT:-15}
VLM_VALIDATION_TIMEOUT=${VLM_VALIDATION_TIMEOUT:-60}
WEB_UI=${WEB_UI:-off}
LOCAL_FS_MODE=${LOCAL_FS_MODE:-off}
# Build a curl auth-flag array that's empty when BASIC_AUTH isn't set.
# `"${CURL_AUTH[@]}"` then expands to nothing for anonymous access and to
# `-u user:password` otherwise — same call sites work for both modes.
CURL_AUTH=()
if [ -n "${BASIC_AUTH:-}" ]; then
    CURL_AUTH=(-u "$BASIC_AUTH")
fi
PASS=0; FAIL=0; SKIP=0
check() {
    case "$1" in
        OK)
            echo "  PASS  $2"
            PASS=$((PASS + 1))
            ;;
        SKIP)
            echo "  SKIP  $2 — $3"
            SKIP=$((SKIP + 1))
            ;;
        *)
            echo "  FAIL  $2 — $3"
            FAIL=$((FAIL + 1))
            ;;
    esac
}

echo "── 1. Gateway / static surfaces ──"
if [ "$WEB_UI" = "on" ]; then
    [ "$(curl "${CURL_AUTH[@]}" -so/dev/null -w'%{http_code}' "$BASE"/)" = 302 ]                   && check OK "GET /     → 302 /ui/"             || check FAIL "GET /"           "expected 302"
    [ "$(curl "${CURL_AUTH[@]}" -sLo/dev/null -w'%{http_code}' "$BASE"/ui/)" = 200 ]               && check OK "GET /ui/  → 200"                 || check FAIL "GET /ui/"        "expected 200"
else
    [ "$(curl "${CURL_AUTH[@]}" -so/dev/null -w'%{http_code}' "$BASE"/)" = 302 ]                   && check OK "GET /     → 302 /docs/"           || check FAIL "GET /"           "expected 302"
    check SKIP "GET /ui/" "WebUI overlay not enabled (WEB_UI=off)"
fi
[ "$(curl "${CURL_AUTH[@]}" -so/dev/null -w'%{http_code}' "$BASE"/docs/)" = 200 ]              && check OK "GET /docs/ → 200"                || check FAIL "GET /docs/"      "expected 200"
[ "$(curl "${CURL_AUTH[@]}" -so/dev/null -w'%{http_code}' "$BASE"/docs/openapi.json)" = 200 ]  && check OK "GET /docs/openapi.json → 200"    || check FAIL "openapi.json"    "expected 200"

echo "── 2. info-endpoint ──"
curl "${CURL_AUTH[@]}" -sf "$BASE"/info/backend/storage | grep -q '"storage_backend_type"' \
    && check OK "GET /info/backend/storage" \
    || check FAIL "/info/backend/storage" "missing storage_backend_type"

N=$(curl "${CURL_AUTH[@]}" -sf "$BASE"/info/plugins | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)
[ "${N:-0}" -ge 1 ] && check OK "GET /info/plugins ($N plugins)" || check FAIL "/info/plugins" "no plugins reported"

echo "── 3. deepsearch-api: V2 text search ──"
RES=$(curl "${CURL_AUTH[@]}" -sf "$BASE/search?description=robot&limit=3")
N=$(echo "$RES" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)
if [ "${N:-0}" -ge 1 ]; then
    check OK "GET /search description=robot ($N hits)"
    echo "$RES" | python3 -c "
import json, sys
for h in json.load(sys.stdin):
    print(f\"    score={h['score']:.3f}  {h['url'][:90]}\")
"
else
    check FAIL "/search" "no hits returned (index may still be warming)"
    IDX_TOTAL=$(curl "${CURL_AUTH[@]}" -sf -X POST "$BASE/search_hybrid" \
        -H 'content-type: application/json' \
        -d '{"limit":1}' 2>/dev/null \
        | python3 -c 'import json,sys;print(json.load(sys.stdin).get("total",0))' 2>/dev/null)
    echo "    index status: ${IDX_TOTAL:-0} documents in OpenSearch"
fi
# Always surface pipeline metrics so operators can observe state regardless of outcome.
# NOTE: The runtime image is distroless (no curl). Use python3 urllib to fetch metrics.
PIPELINE_METRICS=$(docker exec usdsearch-crawler python3 -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://localhost:8000/metrics', timeout=5)
    sys.stdout.write(r.read().decode())
except Exception:
    pass
" 2>/dev/null \
    | grep -E "^omnideepsearch_deepsearch_crawler_(stream_length|group_read|group_processed)" \
    | grep -v "^#")
if [ -n "$PIPELINE_METRICS" ]; then
    echo "    ┌─ pipeline metrics (crawler prometheus):"
    echo "$PIPELINE_METRICS" | sed 's/^/    │ /'
    echo "    └─"
fi
MONITOR_METRICS=$(docker exec usdsearch-monitor-crawler python3 -c "
import urllib.request, sys
try:
    r = urllib.request.urlopen('http://localhost:8000/metrics', timeout=5)
    sys.stdout.write(r.read().decode())
except Exception:
    pass
" 2>/dev/null \
    | grep -E "^omnideepsearch_(deepsearch_monitor_(queued|processed|queue_progress)|plugin_items_processed|plugin_tasks_queue_size|results_queue_size)" \
    | grep -v "^#")
if [ -n "$MONITOR_METRICS" ]; then
    echo "    ┌─ pipeline metrics (monitor prometheus):"
    echo "$MONITOR_METRICS" | sed 's/^/    │ /'
    echo "    └─"
fi
CRAWLER_ERRORS=$(docker logs usdsearch-crawler --tail 30 2>&1 | grep -i -E 'Error|Timeout|Traceback|NoCredentials|InvalidAccess|ConnectionRefused' | tail -5 2>/dev/null)
if [ -n "$CRAWLER_ERRORS" ]; then
    echo "    ┌─ crawler errors (docker logs usdsearch-crawler):"
    echo "$CRAWLER_ERRORS" | sed 's/^/    │ /'
    echo "    └─"
fi

echo "── 4. deepsearch-api: V3 hybrid (text + SigLIP2 vector) ──"
RES=$(curl "${CURL_AUTH[@]}" -sf -X POST "$BASE/search_hybrid" \
    -H 'content-type: application/json' \
    -d '{
      "hybrid_text_query":"warehouse",
      "vector_queries":[{"field_name":"siglip2-embedding.embedding","query_type":"text","query":"warehouse"}],
      "limit":3,
      "return_metadata":true
    }')
TOTAL=$(echo "$RES" | python3 -c 'import json,sys;print(json.load(sys.stdin)["total"])' 2>/dev/null)
if [ "${TOTAL:-0}" -ge 1 ]; then
    check OK "POST /search_hybrid (total=$TOTAL)"
    echo "$RES" | python3 -c "
import json, sys
for h in json.load(sys.stdin)['hits'][:3]:
    print(f\"    score={h['score']:.3f}  {h['source']['base_key'][:90]}\")
"
else
    check FAIL "/search_hybrid" "no hits — Triton or vector index may not be ready (total in index: ${TOTAL:-0})"
fi

echo "── 5. deepsearch-api: stats endpoint ──"
[ "$(curl "${CURL_AUTH[@]}" -so/dev/null -w'%{http_code}' "$BASE"/search/stats/usd_properties)" = 200 ] \
    && check OK "GET /search/stats/usd_properties" \
    || check FAIL "/search/stats/usd_properties" "non-200 response"

echo "── 6. info-endpoint: pipeline status for a real asset ──"
URL=$(curl "${CURL_AUTH[@]}" -sf "$BASE/search?description=robot&limit=1" \
    | python3 -c 'import json,sys;r=json.load(sys.stdin);print(r[0]["url"] if r else "")' 2>/dev/null)
if [ -n "$URL" ]; then
    RES=$(curl "${CURL_AUTH[@]}" -sfG --data-urlencode "url=$URL" "$BASE/info/indexing/asset/status")
    if echo "$RES" | grep -q '"plugins_statuses"'; then
        check OK "GET /info/indexing/asset/status (asset has plugin history)"
        echo "    asset: $URL"
        echo "$RES" | python3 -c "
import json, sys
ps = json.load(sys.stdin).get('plugins_statuses', {})
for name, info in ps.items():
    print(f\"    {name} → {info.get('indexing_status')}\")
"
    else
        check FAIL "/info/indexing/asset/status" "missing plugins_statuses key"
    fi
else
    check FAIL "/info/indexing/asset/status" "could not fetch a sample asset URL from /search"
fi

echo "── 7. asset-graph-service: scene graph for a real asset ──"
# /search supports return_root_prims=true, which annotates each hit with its
# root prims pulled from the graph store. A non-empty root_prims field is
# proof the asset_graph_generation worker has already finished it — so we
# pick a graphed scene deterministically in a single request, no probing.
# Poll up to ASSET_GRAPH_TIMEOUT seconds (5s cadence) to absorb cold-start
# backlog on slower runners.
find_graphed_scene() {
    curl "${CURL_AUTH[@]}" -sf "$BASE/search?description=building&limit=50&return_root_prims=true" 2>/dev/null \
        | python3 -c '
import json, sys
hits = json.load(sys.stdin)
for h in hits:
    rp = h.get("root_prims") or []
    if rp:
        print(h["url"])
        break
' 2>/dev/null
}

GRAPHED_URL=$(find_graphed_scene)
WAITED=0
while [ -z "$GRAPHED_URL" ] && [ "$WAITED" -lt "$ASSET_GRAPH_TIMEOUT" ]; do
    sleep 5
    WAITED=$((WAITED + 5))
    echo "    waiting for ags worker... ${WAITED}/${ASSET_GRAPH_TIMEOUT}s"
    GRAPHED_URL=$(find_graphed_scene)
done

if [ -n "$GRAPHED_URL" ]; then
    PRIMS_JSON=$(curl "${CURL_AUTH[@]}" -sfG --data-urlencode "scene_url=$GRAPHED_URL" --data-urlencode "limit=5" \
        "$BASE/asset_graph/usd/prims")
    PRIM_COUNT=$(echo "$PRIMS_JSON" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))' 2>/dev/null)
    check OK "GET /asset_graph/usd/prims ($PRIM_COUNT prims via return_root_prims pre-filter)"
    echo "    scene: $GRAPHED_URL"
    echo "$PRIMS_JSON" | python3 -c "
import json, sys
for p in json.load(sys.stdin):
    print(f\"    {p.get('prim_type','?'):20} {p.get('usd_path','?')}\")
"

    # Cross-check: scene_summary should report the same scene with sane aggregates.
    SUMMARY=$(curl "${CURL_AUTH[@]}" -sfG --data-urlencode "scene_url=$GRAPHED_URL" "$BASE/asset_graph/usd/scene_summary/")
    N_PRIMS=$(echo "$SUMMARY" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("n_prims",0))' 2>/dev/null)
    if [ "${N_PRIMS:-0}" -ge 1 ]; then
        check OK "GET /asset_graph/usd/scene_summary/ (n_prims=$N_PRIMS)"
        echo "$SUMMARY" | python3 -c "
import json, sys
s = json.load(sys.stdin)
print(f\"    prim_types: {s.get('prim_types')}\")
print(f\"    polygons={s.get('total_polygon_count')}, points={s.get('total_point_count')}, mpu={s.get('scene_mpu')}\")
"
    else
        check FAIL "/asset_graph/usd/scene_summary/" "n_prims missing or 0"
    fi
else
    check FAIL "/asset_graph/usd/prims" "no graphed hits in /search?return_root_prims=true after ${ASSET_GRAPH_TIMEOUT}s — ags worker may not be running (check 'docker logs usdsearch-worker-ags')"
fi

echo "── 8. deepsearch-api: VLM validation ──"
# POSTs to /vlm_validate/search_result with a real asset URL + the same
# query we searched for. The endpoint returns:
#   200 — body has is_match / confidence / similarity_score / reasoning
#   503 — VLM validation is not enabled on this server (compose stack came
#         up without docker-compose.vlm-plugins.yml, or
#         USDSEARCH_VISION_VALIDATION_ENABLED=false). Reported as SKIP, not FAIL — the
#         endpoint itself is the gate, no extra env-flag plumbing needed.
# Uses --max-time because real VLM calls (especially reasoning models like
# gemini-3-flash-preview) can run 30s+ per image batch.
VLM_URL=$(curl "${CURL_AUTH[@]}" -sf "$BASE/search?description=warehouse&limit=1" \
    | python3 -c 'import json,sys;r=json.load(sys.stdin);print(r[0]["url"] if r else "")' 2>/dev/null)
if [ -n "$VLM_URL" ]; then
    VLM_TMP=$(mktemp)
    HTTP=$(curl "${CURL_AUTH[@]}" -s -o "$VLM_TMP" -w '%{http_code}' \
        --max-time "$VLM_VALIDATION_TIMEOUT" \
        -X POST "$BASE/vlm_validate/search_result" \
        -H 'content-type: application/json' \
        --data-binary "$(python3 -c 'import json,sys;print(json.dumps({"asset_url":sys.argv[1],"query_text":"warehouse"}))' "$VLM_URL")")
    case "$HTTP" in
        200)
            VLM_SUMMARY=$(VLM_TMP="$VLM_TMP" python3 -c "
import json, os, sys
r = json.load(open(os.environ['VLM_TMP']))
required = {'is_match', 'confidence', 'similarity_score', 'reasoning'}
missing = required - set(r)
if missing:
    sys.exit(f'missing keys: {sorted(missing)}')
print(f\"    is_match={r['is_match']} confidence={r['confidence']:.2f} similarity_score={r['similarity_score']}\")
print(f\"    reasoning={r['reasoning'][:200]!r}\")
" 2>&1)
            if [ $? -eq 0 ]; then
                check OK "POST /vlm_validate/search_result"
                echo "    asset: $VLM_URL"
                echo "$VLM_SUMMARY"
            else
                check FAIL "/vlm_validate/search_result" "response shape invalid: $VLM_SUMMARY"
            fi
            ;;
        503)
            check SKIP "/vlm_validate/search_result" "VLM validation disabled on the server (HTTP 503)"
            ;;
        000)
            check FAIL "/vlm_validate/search_result" "curl timed out (>${VLM_VALIDATION_TIMEOUT}s) — VLM provider may be slow or misconfigured"
            ;;
        *)
            check FAIL "/vlm_validate/search_result" "HTTP $HTTP — $(head -c 200 "$VLM_TMP")"
            ;;
    esac
    rm -f "$VLM_TMP"
else
    check FAIL "/vlm_validate/search_result" "could not fetch a sample asset URL from /search"
fi

echo "── 9. LocalFS path-rewrite (s3:// leak) ──"
# When the docker-compose.local-fs.yml overlay is in play, LocalFSPathMiddleware
# is expected to rewrite every s3://<bucket>/... URI in API responses to its
# host-filesystem equivalent. A leaked s3:// substring indicates the
# middleware missed a code path — useful regression catch for that ASGI shim.
# Skipped for every other config; the s3:// scheme is expected there.
if [ "$LOCAL_FS_MODE" = "on" ]; then
    LEAK_TMP=$(mktemp)
    trap 'rm -f "$LEAK_TMP"' EXIT
    {
        curl "${CURL_AUTH[@]}" -sf "$BASE/search?description=*&limit=20" || true
        curl "${CURL_AUTH[@]}" -sf -X POST "$BASE/search_hybrid" \
            -H 'content-type: application/json' \
            -d '{"hybrid_text_query":"*","limit":20,"return_metadata":true}' || true
    } > "$LEAK_TMP"
    if grep -q 's3://' "$LEAK_TMP"; then
        OFFENDER=$(grep -o 's3://[^"]*' "$LEAK_TMP" | head -1)
        check FAIL "LocalFSPathMiddleware s3:// rewrite" "leaked URI: ${OFFENDER:0:120}"
    else
        check OK "LocalFSPathMiddleware rewrote all s3:// URIs in /search + /search_hybrid"
    fi
    rm -f "$LEAK_TMP"
    trap - EXIT
else
    check SKIP "LocalFSPathMiddleware s3:// rewrite" "local-fs overlay not enabled (LOCAL_FS_MODE=off)"
fi

echo
if [ "$SKIP" -gt 0 ]; then
    echo "═══ $PASS passed, $FAIL failed, $SKIP skipped ═══"
else
    echo "═══ $PASS passed, $FAIL failed ═══"
fi
[ $FAIL -eq 0 ]
