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

# Publish the packaged Helm chart to NGC registry.
#
# Environment variables:
#   SOURCE      - Directory containing the packaged .tgz chart (default: _charts at repo root)
#   REGISTRY    - NGC registry path (default: omniverse/deeptag-internal)
#   ORG         - NGC org (default: omniverse)
#   TEAM        - NGC team (default: deeptag-internal)
#   OVERWRITE   - Whether to overwrite existing chart (default: false)
#   CHART_VERSION - Set by version.sh or CI; used as the chart version
#
set -eux
DIR="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$DIR/../.." && pwd -P)"

# Source version info if not already set
if [ -z "${CHART_VERSION:-}" ]; then
    source "$DIR/version.sh"
fi

registry=${REGISTRY:-"omniverse/deeptag-internal"}
org=${ORG:-"omniverse"}
team=${TEAM:-"deeptag-internal"}
overwrite=${OVERWRITE:-"false"}
chart_name="usdsearch"
source_dir=${SOURCE:-"${ROOT}/_charts"}
version=${CHART_VERSION}

chart=$registry/$chart_name:$version

echo "Publishing chart $chart from $source_dir"
push_result=$(ngc registry chart push --source "$source_dir" --org "$org" $chart 2>&1)

echo "$push_result"

# NGC CLI returns exit code 0 regardless of the actual push status so we need to check its output
if [[ $push_result =~ .*"already exists in the repository".* ]]; then

    # if overwrite flag was set - do not require user input
    if [[ $overwrite == "true" ]]; then
        overwrite="y"
    else
        overwrite="n"
        echo "overwrite [y/n]:"
        read overwrite
    fi

    if [[ $overwrite == "y" ]]; then
        echo "Removing existing chart $version"
        ngc registry chart remove -y "$chart" --org "$org" --team "$team"

        echo "Publishing chart $version"
        push_result=$(ngc registry chart push "$chart" --source "$source_dir" --org "$org" --team "$team" 2>&1)
        echo "$push_result"
        echo "Push completed, chart overwritten"
    else
        echo "Push failed, chart already exists in the repository"
        exit 1
    fi
else
    echo "Push completed, chart created"
fi
