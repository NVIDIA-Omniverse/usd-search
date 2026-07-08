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

# Build the unified OpenAPI spec: bring up deepsearch-api, info-endpoint,
# and asset-graph-service from source, then run the openapi-merger sidecar
# to produce helm/usdsearch/docs/openapi.json (configurable via
# $OPENAPI_OUTPUT_DIR). The spec lives under the helm chart so it ships
# as-is in the packaged chart's static-content configmap
# (.Files.Get "docs/openapi.json").
#
# All images are built from source via the base compose files — no
# dependency on a pre-built usdsearch image.
#
# Usage:
#   scripts/build-openapi-docs.sh                # writes helm/usdsearch/docs/openapi.json
#   OPENAPI_OUTPUT_DIR=/tmp/spec scripts/build-openapi-docs.sh
#   API_VERSION=1.4.0 scripts/build-openapi-docs.sh
#
# The merged-spec version comes from the repo-root VERSION.md unless
# $API_VERSION is already set in the environment.
set -euo pipefail

DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P )"
REPO_ROOT="$( cd "$DIR/.." && pwd -P )"
COMPOSE_DIR="$REPO_ROOT/infra/compose"

VERSION_FILE="$REPO_ROOT/VERSION.md"
if [[ -z "${API_VERSION:-}" && -f "$VERSION_FILE" ]]; then
    API_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi
export API_VERSION="${API_VERSION:-}"
[[ -n "$API_VERSION" ]] && echo "API version: $API_VERSION (from ${VERSION_FILE#$REPO_ROOT/})"

# Run the openapi-merger as the invoking user so the generated openapi.json
# is owned by the host user, not root. The compose file references these via
# user: "${HOST_UID:-0}:${HOST_GID:-0}".
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo "Error: docker compose not found" >&2
    exit 1
fi

# Output directory is mounted into the merger container at /output. Default
# is helm/usdsearch/docs/ so the generated spec ships with the helm chart's
# static-content configmap; override with $OPENAPI_OUTPUT_DIR.
export OPENAPI_OUTPUT_DIR="${OPENAPI_OUTPUT_DIR:-$REPO_ROOT/helm/usdsearch/docs}"
mkdir -p "$OPENAPI_OUTPUT_DIR"

COMPOSE_FILES=(
    -f "$COMPOSE_DIR/redis.yml"
    -f "$COMPOSE_DIR/neo4j.yml"
    -f "$COMPOSE_DIR/opensearch.yml"
    -f "$COMPOSE_DIR/deepsearch-api.yml"
    -f "$COMPOSE_DIR/info-endpoint.yml"
    -f "$COMPOSE_DIR/asset-graph-service.yml"
    -f "$COMPOSE_DIR/openapi-merge.yml"
)

# In CI, layer the per-service *.ci.yml overlays so service builds
# pull from / push to the shared $CI_REGISTRY_IMAGE/usdsearch:cache
# registry tag. All three services build from docker/Dockerfile.usdsearch,
# so they share the same cache ref. Local runs rely on Docker's
# default local layer cache and skip this.
if [[ "${GITLAB_CI:-}" == "true" && -n "${CI_REGISTRY_IMAGE:-}" ]]; then
    echo "CI detected — enabling registry-backed BuildKit cache (usdsearch:cache)"
    COMPOSE_FILES+=(
        -f "$COMPOSE_DIR/deepsearch-api.ci.yml"
        -f "$COMPOSE_DIR/info-endpoint.ci.yml"
        -f "$COMPOSE_DIR/asset-graph-service.ci.yml"
    )
fi

cleanup() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "--- Container logs (failure dump) -----------------------------"
        $DOCKER_COMPOSE_CMD "${COMPOSE_FILES[@]}" logs --no-color || true
    fi
    $DOCKER_COMPOSE_CMD "${COMPOSE_FILES[@]}" down --volumes --remove-orphans || true
    exit $rc
}
trap cleanup EXIT

echo "--- Starting infrastructure -----------------------------------"
$DOCKER_COMPOSE_CMD "${COMPOSE_FILES[@]}" up -d --wait --build --quiet-pull --remove-orphans \
    redis neo4j opensearch deepsearch-api info-endpoint asset-graph-service

echo "--- Running openapi-merger -----------------------------------"
$DOCKER_COMPOSE_CMD "${COMPOSE_FILES[@]}" run --rm --no-deps --quiet-pull openapi-merger

echo "--- Done -----------------------------------------------------"
echo "Merged spec: $OPENAPI_OUTPUT_DIR/openapi.json"
