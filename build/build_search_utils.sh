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

# fail on first error
set -eux
export DIR="$( cd "$(dirname "$0")" ; pwd -P )"

BUILD_DIR="$DIR/../packages/search-utils/_build"
CLOUDFRONT="https://d4i3qtqj3r0z5.cloudfront.net"

if ! command -v 7z &>/dev/null; then
    echo "ERROR: 7z not found. Install p7zip-full (apt) or p7zip (brew)." >&2
    exit 1
fi

section_start() { echo -e "\e[0Ksection_start:$(date +%s):${1}[collapsed=true]\r\e[0K${2}"; return; }
section_end()   { echo -e "\e[0Ksection_end:$(date +%s):${1}\r\e[0K"; return; }

fetch_pkg() {
    local name="$1" version="$2" dest="$3"
    local ver_enc="${version//+/%2B}"
    local tmp
    tmp=$(mktemp /tmp/pkg-XXXXXX.7z)
    section_start "fetch_${name//[^a-zA-Z0-9]/_}" "Fetching ${name}@${version}"
    curl -fL "${CLOUDFRONT}/${name}%40${ver_enc}.7z" -o "$tmp"
    mkdir -p "$dest"
    7z x "$tmp" -o"$dest" -y -bd
    rm "$tmp"
    section_end "fetch_${name//[^a-zA-Z0-9]/_}"
    return
}

echo "---- Pull dependencies ----"
fetch_pkg "omniverse.discovery.client.py"  "1.4.2+main.teamcity.593.4977d25e"              "$BUILD_DIR/discovery.client.py"
fetch_pkg "omniverse.auth.client.py"       "1.3.2+main.teamcity.885.3ae5e70b"              "$BUILD_DIR/omniverse.auth.client.py"
fetch_pkg "omniverse_connection_py"        "11.19+master.gitlab.26141.7c3f1f78"            "$BUILD_DIR/omniverse_connection"
fetch_pkg "idl.py"                         "0.17+merge-requests-362.teamcity.1706.a336a92b" "$BUILD_DIR/idl.py"
fetch_pkg "omniverse.tagging.client.py"    "3.0.0-main+teamcity.970.6675778b"              "$BUILD_DIR/tag_idl_client"

echo "----- Wheel build ---------"
uv build --package search-utils --wheel
