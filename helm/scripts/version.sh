#!/bin/bash
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

# Derives chart version and appVersion from git tags.
#
# Versioning strategy:
#   - chart-X.Y.Z tags → CHART_VERSION (Chart.yaml version)
#   - images-X.Y.Z tags → APP_VERSION (Chart.yaml appVersion, Docker image tags)
#   - Bare X.Y.Z tag on the current commit (CI_COMMIT_TAG) — used as a
#     fallback for both CHART_VERSION and APP_VERSION when no prefixed
#     tag is reachable. Lets a single bare tag drive a one-shot release
#     without having to push parallel chart-* / images-* tags.
#
# On non-tagged commits, appends "-N" suffix where N = commits since last tag.
# On a tagged commit itself, the version is clean (no suffix).
#
# Usage:
#   source helm/scripts/version.sh
#   echo $CHART_VERSION $APP_VERSION
#
set -euo pipefail

# Resolve the version when no namespaced tag is reachable via git describe.
#   - CI_COMMIT_TAG matches our prefix → strip it (handles shallow CI clones
#     where describe fails even though we're on the tag).
#   - CI_COMMIT_TAG matches the *other* prefix → not relevant to us, use 0.0.1.
#   - CI_COMMIT_TAG is a bare tag (no chart-/images- prefix) → use it as
#     fallback for both CHART_VERSION and APP_VERSION.
#   - CI_COMMIT_TAG unset → use 0.0.1.
_ci_tag_or_default() {
    local prefix="$1"
    local tag="${CI_COMMIT_TAG:-}"
    if [ -z "$tag" ]; then
        echo "0.0.1"
    elif [[ "$tag" == ${prefix}* ]]; then
        echo "${tag#${prefix}}"
    elif [[ "$tag" == chart-* || "$tag" == images-* ]]; then
        echo "0.0.1"
    else
        echo "$tag"
    fi
}

# --- Chart version (from chart-X.Y.Z tags) ---
CHART_TAG=$(git describe --tags --match 'chart-*' --abbrev=0 2>/dev/null || echo "")
if [ -z "$CHART_TAG" ]; then
    CHART_VERSION="$(_ci_tag_or_default chart-)"
    CHART_DISTANCE="0"
else
    CHART_VERSION="${CHART_TAG#chart-}"  # strip prefix: "chart-1.4.0" → "1.4.0"
    CHART_DISTANCE=$(git rev-list "${CHART_TAG}..HEAD" --count)
fi

if [ "$CHART_DISTANCE" -gt 0 ]; then
    CHART_VERSION="${CHART_VERSION}-${CHART_DISTANCE}"
fi

# --- App/Image version (from images-X.Y.Z tags) ---
IMAGES_TAG=$(git describe --tags --match 'images-*' --abbrev=0 2>/dev/null || echo "")
if [ -z "$IMAGES_TAG" ]; then
    APP_VERSION="$(_ci_tag_or_default images-)"
    IMAGES_DISTANCE="0"
else
    APP_VERSION="${IMAGES_TAG#images-}"  # strip prefix: "images-1.4.0" → "1.4.0"
    IMAGES_DISTANCE=$(git rev-list "${IMAGES_TAG}..HEAD" --count)
fi

if [ "$IMAGES_DISTANCE" -gt 0 ]; then
    APP_VERSION="${APP_VERSION}-${IMAGES_DISTANCE}"
fi

export CHART_VERSION
export APP_VERSION

echo "CHART_VERSION=$CHART_VERSION"
echo "APP_VERSION=$APP_VERSION"
