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

# Build the Docker images produced by the CI `build` stage and optionally
# push them to a registry. Mirrors the three image build jobs defined in
# .gitlab-ci.yml: build-usdsearch, build-rendering-job, build-siglip2-triton.

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"

DEFAULT_REGISTRY="nvcr.io/omniverse/deeptag-internal"
ALL_IMAGES=("usdsearch" "usdsearch-kit-workflows" "siglip2-triton")

usage() {
  cat <<'EOF'
Build the Docker images produced by the CI `build` stage and optionally
push them to a registry. Mirrors the three image build jobs defined in
.gitlab-ci.yml: build-usdsearch, build-rendering-job, build-siglip2-triton.

Usage:
  scripts/build-ci-images.sh <tag> [--push] [--registry <host/namespace>]
                                   [--image <name> ...] [--no-cache]

Arguments:
  <tag>                Required. Image tag applied to every built image.

Flags:
  --push               Tag images as <registry>/<name>:<tag> and push them.
                       Without --push, images are only tagged locally as
                       <name>:<tag>.
  --registry <r>       Target registry, defaults to
                       nvcr.io/omniverse/deeptag-internal. Only used with
                       --push.
  --image <name>       Restrict to one image; repeat to build several.
                       Valid names: usdsearch, usdsearch-kit-workflows,
                       siglip2-triton. Default: all three.
  --no-cache           Pass --no-cache to docker build.
  -h, --help           Show this help text.

Examples:
  scripts/build-ci-images.sh dev-local
  scripts/build-ci-images.sh 1.4.0 --push
  scripts/build-ci-images.sh 1.4.0 --push --registry myreg.example.com/team
  scripts/build-ci-images.sh quick --image usdsearch --image siglip2-triton
EOF
}

TAG=""
PUSH=false
REGISTRY="$DEFAULT_REGISTRY"
NO_CACHE=""
SELECTED_IMAGES=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --push)
      PUSH=true
      shift
      ;;
    --registry)
      [[ $# -ge 2 ]] || { echo "ERROR: --registry requires an argument" >&2; exit 2; }
      REGISTRY="$2"
      shift 2
      ;;
    --image)
      [[ $# -ge 2 ]] || { echo "ERROR: --image requires an argument" >&2; exit 2; }
      SELECTED_IMAGES+=("$2")
      shift 2
      ;;
    --no-cache)
      NO_CACHE="--no-cache"
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "ERROR: unknown flag '$1'" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "$TAG" ]]; then
        TAG="$1"
      else
        echo "ERROR: unexpected positional argument '$1'" >&2
        usage >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$TAG" ]]; then
  echo "ERROR: <tag> is required" >&2
  usage >&2
  exit 2
fi

# Default to all images if none were explicitly selected.
if [[ ${#SELECTED_IMAGES[@]} -eq 0 ]]; then
  SELECTED_IMAGES=("${ALL_IMAGES[@]}")
fi

# Validate selections against the known set.
for img in "${SELECTED_IMAGES[@]}"; do
  found=false
  for known in "${ALL_IMAGES[@]}"; do
    if [[ "$img" == "$known" ]]; then
      found=true
      break
    fi
  done
  if ! $found; then
    echo "ERROR: unknown image '$img'. Valid: ${ALL_IMAGES[*]}" >&2
    exit 2
  fi
done

# Build one image. Tags the result locally as <name>:<tag> and, when pushing,
# also as <registry>/<name>:<tag>. Returns the registry-qualified tag(s) to
# push via $PENDING_PUSHES (a global array — bash arrays don't return well).
PENDING_PUSHES=()

build_image() {
  local name="$1"
  local dockerfile="$2"
  local context="$3"
  shift 3
  local extra_args=("$@")

  local local_tag="${name}:${TAG}"
  local tag_args=("--tag" "$local_tag")
  if $PUSH; then
    local remote_tag="${REGISTRY}/${name}:${TAG}"
    tag_args+=("--tag" "$remote_tag")
    PENDING_PUSHES+=("$remote_tag")
  fi

  echo
  echo "=============================================================="
  echo "Building $name"
  echo "  dockerfile: $dockerfile"
  echo "  context:    $context"
  echo "  tags:       ${tag_args[*]:1}"
  echo "=============================================================="

  # shellcheck disable=SC2086
  docker build $NO_CACHE \
    "${tag_args[@]}" \
    "${extra_args[@]}" \
    --file "$dockerfile" \
    "$context"
}

build_usdsearch() {
  build_image \
    "usdsearch" \
    "$REPO_ROOT/docker/Dockerfile.usdsearch" \
    "$REPO_ROOT"
}

build_usdsearch_kit_workflows() {
  build_image \
    "usdsearch-kit-workflows" \
    "$REPO_ROOT/docker/Dockerfile.kit" \
    "$REPO_ROOT/services/rendering-job" \
    --build-context "graph-builder=$REPO_ROOT/services/asset-graph-builder"
}

build_siglip2_triton() {
  build_image \
    "siglip2-triton" \
    "$REPO_ROOT/docker/Dockerfile.siglip2-triton" \
    "$REPO_ROOT/services/siglip2-triton"
}

cd "$REPO_ROOT"

for img in "${SELECTED_IMAGES[@]}"; do
  case "$img" in
    usdsearch)               build_usdsearch ;;
    usdsearch-kit-workflows) build_usdsearch_kit_workflows ;;
    siglip2-triton)          build_siglip2_triton ;;
  esac
done

if $PUSH; then
  echo
  echo "=============================================================="
  echo "Pushing ${#PENDING_PUSHES[@]} image(s) to $REGISTRY"
  echo "=============================================================="
  for ref in "${PENDING_PUSHES[@]}"; do
    echo "+ docker push $ref"
    docker push "$ref"
  done
fi

echo
echo "Done."
