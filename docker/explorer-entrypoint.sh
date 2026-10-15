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

# Explorer container entrypoint: renders /app/runtime-config.js from
# container env, then hands off to the stock bitnami nginx entrypoint.
#
#   EXPLORER_SERVER_MAPPING  JSON object: {"<server-key>": {name, apiUrl,
#                            embedding_config}, ...} — the runtime index
#                            registry (window.__SERVER_MAPPING__). Each key is
#                            the x-usdsearch-storage-backend header value the
#                            SPA sends; see public/runtime-config.js for the
#                            full schema.
#   EXPLORER_DEFAULT_SERVER  Key selected at load when no ?server= deep link
#                            (window.__DEFAULT_SERVER__).
#
# Both unset -> the committed placeholder stands and the SPA falls back to the
# build-time REACT_APP_SERVER_MAPPING. The value is emitted verbatim into a
# standalone <script> file: malformed JSON breaks only that file, and the SPA
# falls back to the build-time mapping (config.jsx guards).
set -eu

OUT=/app/runtime-config.js
if [ -n "${EXPLORER_SERVER_MAPPING:-}" ] || [ -n "${EXPLORER_DEFAULT_SERVER:-}" ]; then
  {
    echo "// Rendered at container start by explorer-entrypoint.sh from"
    echo "// EXPLORER_SERVER_MAPPING / EXPLORER_DEFAULT_SERVER."
    if [ -n "${EXPLORER_SERVER_MAPPING:-}" ]; then
      printf 'window.__SERVER_MAPPING__ = %s;\n' "${EXPLORER_SERVER_MAPPING}"
    fi
    if [ -n "${EXPLORER_DEFAULT_SERVER:-}" ]; then
      printf 'window.__DEFAULT_SERVER__ = "%s";\n' "${EXPLORER_DEFAULT_SERVER}"
    fi
  } > "${OUT}"
fi

exec /opt/bitnami/scripts/nginx/entrypoint.sh "$@"
