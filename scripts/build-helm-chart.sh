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

# Package and optionally publish the usdsearch Helm chart. Mirrors the
# helm-package and helm-publish-ngc jobs defined in ci/helm/gitlab-ci.yml:
#   1. (optional) regenerate helm/usdsearch/README.md via helm-docs
#   2. stamp Chart.yaml `version` / `appVersion` and values.yaml
#      `global.appVersion`
#   3. add the opensearch + neo4j helm repos, fetch deps, package the chart
#   4. optionally push the resulting .tgz to NGC via helm/scripts/push_to_ngc.sh

set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")"/.. && pwd)"
CHART_DIR="$REPO_ROOT/helm/usdsearch"
CHART_FILE="$CHART_DIR/Chart.yaml"
VALUES_FILE="$CHART_DIR/values.yaml"

DEFAULT_REGISTRY="omniverse/deeptag-internal"
DEFAULT_ORG="omniverse"
DEFAULT_TEAM="deeptag-internal"
DEFAULT_DEST="$REPO_ROOT/_charts"

usage() {
  cat <<'EOF'
Package and optionally publish the usdsearch Helm chart to NGC. Mirrors
the helm-package and helm-publish-ngc jobs in ci/helm/gitlab-ci.yml.

Usage:
  scripts/build-helm-chart.sh <chart-version> [--app-version <ver>]
                                              [--push] [--overwrite]
                                              [--registry <r>] [--org <o>] [--team <t>]
                                              [--dest <dir>] [--skip-readme]

Arguments:
  <chart-version>      Required. Sets Chart.yaml `version` and the
                       packaged .tgz filename (usdsearch-<version>.tgz).

Flags:
  --app-version <ver>  Override Chart.yaml `appVersion` and values.yaml
                       `global.appVersion`. Defaults to <chart-version>.
  --push               After packaging, push the chart to NGC via
                       helm/scripts/push_to_ngc.sh.
  --overwrite          When pushing, replace an existing chart of the
                       same version (passed as OVERWRITE=true).
  --registry <r>       NGC registry path (default: omniverse/deeptag-internal).
  --org <o>            NGC org (default: omniverse).
  --team <t>           NGC team (default: deeptag-internal).
  --dest <dir>         Output directory for the .tgz (default: _charts/
                       at the repo root).
  --skip-readme        Skip regenerating helm/usdsearch/README.md (the
                       CI build-helm-readme step). Use when helm-docs
                       and docker are both unavailable.
  -h, --help           Show this help text.

Requirements:
  - helm, yq (mikefarah / go-yq -- `apk add yq` or `brew install yq`)
  - With --push: ngc CLI on PATH and authenticated (see helm/scripts/push_to_ngc.sh).
  - Without --skip-readme: helm-docs OR docker on PATH.

Examples:
  scripts/build-helm-chart.sh 1.4.0
  scripts/build-helm-chart.sh 1.4.0 --app-version 1.4.0 --push
  scripts/build-helm-chart.sh 1.4.0-rc.1 --app-version 1.4.0 --push --overwrite
EOF
}

CHART_VERSION=""
APP_VERSION=""
PUSH=false
OVERWRITE=false
REGISTRY="$DEFAULT_REGISTRY"
ORG="$DEFAULT_ORG"
TEAM="$DEFAULT_TEAM"
DEST="$DEFAULT_DEST"
SKIP_README=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --app-version)
      [[ $# -ge 2 ]] || { echo "ERROR: --app-version requires an argument" >&2; exit 2; }
      APP_VERSION="$2"
      shift 2
      ;;
    --push)
      PUSH=true
      shift
      ;;
    --overwrite)
      OVERWRITE=true
      shift
      ;;
    --registry)
      [[ $# -ge 2 ]] || { echo "ERROR: --registry requires an argument" >&2; exit 2; }
      REGISTRY="$2"
      shift 2
      ;;
    --org)
      [[ $# -ge 2 ]] || { echo "ERROR: --org requires an argument" >&2; exit 2; }
      ORG="$2"
      shift 2
      ;;
    --team)
      [[ $# -ge 2 ]] || { echo "ERROR: --team requires an argument" >&2; exit 2; }
      TEAM="$2"
      shift 2
      ;;
    --dest)
      [[ $# -ge 2 ]] || { echo "ERROR: --dest requires an argument" >&2; exit 2; }
      DEST="$2"
      shift 2
      ;;
    --skip-readme)
      SKIP_README=true
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
      if [[ -z "$CHART_VERSION" ]]; then
        CHART_VERSION="$1"
      else
        echo "ERROR: unexpected positional argument '$1'" >&2
        usage >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [[ -z "$CHART_VERSION" ]]; then
  echo "ERROR: <chart-version> is required" >&2
  usage >&2
  exit 2
fi

APP_VERSION="${APP_VERSION:-$CHART_VERSION}"

command -v helm >/dev/null 2>&1 || { echo "ERROR: helm not found on PATH" >&2; exit 1; }
command -v yq >/dev/null 2>&1 || { echo "ERROR: yq not found on PATH (need mikefarah/yq)" >&2; exit 1; }
if $PUSH; then
  command -v ngc >/dev/null 2>&1 || { echo "ERROR: ngc CLI not found on PATH (required with --push)" >&2; exit 1; }
fi

cd "$REPO_ROOT"

# Snapshot the version-stamped files so the working tree is left clean
# regardless of how the script exits.
CHART_BAK="$(mktemp)"
VALUES_BAK="$(mktemp)"
cp "$CHART_FILE" "$CHART_BAK"
cp "$VALUES_FILE" "$VALUES_BAK"

restore_files() {
  cp "$CHART_BAK" "$CHART_FILE"
  cp "$VALUES_BAK" "$VALUES_FILE"
  rm -f "$CHART_BAK" "$VALUES_BAK"
}
trap restore_files EXIT

echo "=============================================================="
echo "  chart version : $CHART_VERSION"
echo "  app version   : $APP_VERSION"
echo "  output dir    : $DEST"
echo "  push to NGC   : $PUSH"
if $PUSH; then
  echo "  registry      : $REGISTRY"
  echo "  org / team    : $ORG / $TEAM"
  echo "  overwrite     : $OVERWRITE"
fi
echo "=============================================================="

# 1. Regenerate README (matches CI build-helm-readme job).
if ! $SKIP_README; then
  echo
  echo "=== Regenerating $CHART_DIR/README.md ==="
  ./helm/scripts/update_readme.sh
fi

# 2. Stamp Chart.yaml and values.yaml (matches the yq edits in helm-package).
echo
echo "=== Stamping Chart.yaml and values.yaml ==="
yq -i ".version = \"$CHART_VERSION\"" "$CHART_FILE"
yq -i ".appVersion = \"$APP_VERSION\"" "$CHART_FILE"
yq -i ".global.appVersion = \"$APP_VERSION\"" "$VALUES_FILE"

# 3. Fetch deps and package (matches helm-package script block).
mkdir -p "$DEST"
echo
echo "=== Adding helm repos ==="
helm repo add opensearch https://opensearch-project.github.io/helm-charts/ >/dev/null
helm repo add neo4j https://helm.neo4j.com/neo4j >/dev/null
helm repo update >/dev/null

echo
echo "=== Packaging chart ==="
helm package "$CHART_DIR" \
  --dependency-update \
  --destination "$DEST" \
  --version "$CHART_VERSION"

PKG_PATH="$DEST/usdsearch-$CHART_VERSION.tgz"
if [[ ! -f "$PKG_PATH" ]]; then
  echo "ERROR: expected package not found at $PKG_PATH" >&2
  exit 1
fi
echo "Packaged: $PKG_PATH"

# 4. Optionally push to NGC (matches helm-publish-ngc).
if $PUSH; then
  echo
  echo "=== Pushing chart to NGC ($REGISTRY/usdsearch:$CHART_VERSION) ==="
  if $OVERWRITE; then
    OVERWRITE_VAL=true
  else
    OVERWRITE_VAL=false
  fi
  REGISTRY="$REGISTRY" \
  ORG="$ORG" \
  TEAM="$TEAM" \
  SOURCE="$DEST" \
  OVERWRITE="$OVERWRITE_VAL" \
  CHART_VERSION="$CHART_VERSION" \
    ./helm/scripts/push_to_ngc.sh
fi

echo
echo "Done."
