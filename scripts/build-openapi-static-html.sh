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

# Generate a static single-file Redoc HTML page from the merged openapi.json.
# Equivalent to the legacy _old/api-gateway/generate_static_docs.sh, but reads
# from helm/usdsearch/docs/openapi.json by default. Output stays under docs/
# because it's a GitLab Pages artifact, not a chart asset.
#
# Usage:
#   scripts/build-openapi-static-html.sh                    # helm/usdsearch/docs/openapi.json -> docs/openapi.html
#   scripts/build-openapi-static-html.sh path/to/spec.json  # custom input
set -euo pipefail

DIR="$( cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P )"
REPO_ROOT="$( cd "$DIR/.." && pwd -P )"

INPUT_SPEC="${1:-$REPO_ROOT/helm/usdsearch/docs/openapi.json}"
OUTPUT_HTML="${OPENAPI_HTML_OUTPUT:-$REPO_ROOT/docs/openapi.html}"

if [[ ! -f "$INPUT_SPEC" ]]; then
    echo "Error: input spec not found at $INPUT_SPEC" >&2
    echo "Run scripts/build-openapi-docs.sh first to generate it." >&2
    exit 1
fi

if ! command -v npx &> /dev/null; then
    echo "Error: npx not found. Install Node.js to use the redocly CLI." >&2
    exit 1
fi

echo "--- Generating static Redoc HTML -----------------------------"
npx --yes @redocly/cli build-docs "$INPUT_SPEC" -o "$OUTPUT_HTML"
echo "Static docs: $OUTPUT_HTML"
