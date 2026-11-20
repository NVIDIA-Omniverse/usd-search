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
#
# The CLI is pinned: unpinned, the page changed looks when @redocly/cli 2.70.0
# moved build-docs from Redoc 2 to Redoc 3. Bump it deliberately and check the
# rendered page. The page embeds Redoc (--inlineBundle) rather than loading it
# from Redocly's CDN, and Redoc's in-page telemetry is off.
set -euo pipefail

REDOCLY_CLI_VERSION="${REDOCLY_CLI_VERSION:-2.82.0}"

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

# The spec's server is "/" (right for the gateway's own /docs). Redoc 3 resolves
# it against the page's location, so a standalone page would show file:// or the
# Pages host as the API base; give the page a placeholder gateway URL instead.
STATIC_DIR="$(mktemp -d)"
trap 'rm -rf "$STATIC_DIR"' EXIT
STATIC_SPEC="$STATIC_DIR/openapi.json"
node -e '
const fs = require("fs");
const [src, dst, gateway] = process.argv.slice(1);
const spec = JSON.parse(fs.readFileSync(src, "utf8"));
spec.servers = [{
    url: "{gateway}",
    description: "Your USD Search API gateway",
    variables: { gateway: { default: gateway, description: "Base URL of the USD Search API gateway" } },
}];
fs.writeFileSync(dst, JSON.stringify(spec));
' "$INPUT_SPEC" "$STATIC_SPEC" "${OPENAPI_HTML_GATEWAY_URL:-http://localhost:8080}"

echo "--- Generating static Redoc HTML -----------------------------"
REDOCLY_TELEMETRY=off npx --yes "@redocly/cli@${REDOCLY_CLI_VERSION}" \
    build-docs "$STATIC_SPEC" -o "$OUTPUT_HTML" --inlineBundle
echo "Static docs: $OUTPUT_HTML"
