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

# Upload the chart README to the NGC registry.
#
# Environment variables:
#   REGISTRY - NGC registry path (default: omniverse/deeptag-internal)
#   ORG      - NGC org (default: omniverse)
#   TEAM     - NGC team (default: deeptag-internal)
#
set -eux
DIR="$(cd "$(dirname "$0")" && pwd -P)"
CHART_DIR="$DIR/../usdsearch"

registry=${REGISTRY:-"omniverse/deeptag-internal"}
org=${ORG:-"omniverse"}
team=${TEAM:-"deeptag-internal"}

ngc registry chart update "${registry}/usdsearch" \
    --overview-filename "$CHART_DIR/README.md" \
    --org "$org" \
    --team "$team" \
    --publisher NVIDIA \
    --short-desc "USD Search API Helm chart"
