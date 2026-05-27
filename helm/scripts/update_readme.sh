#!/bin/sh
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

# Generate README.md from README.md.gotmpl using helm-docs.
# Falls back to Docker if helm-docs is not installed locally.
#
set -eux
DIR="$(cd "$(dirname "$0")" && pwd -P)"
CHART_DIR="$DIR/../usdsearch"

if command -v helm-docs > /dev/null 2>&1; then
    helm-docs --chart-search-root "$(dirname "$CHART_DIR")" --chart-to-generate "$CHART_DIR"
else
    docker run --rm --volume "$(dirname "$CHART_DIR"):/helm-docs" -u "$(id -u)" jnorwood/helm-docs:latest --chart-to-generate usdsearch
fi
