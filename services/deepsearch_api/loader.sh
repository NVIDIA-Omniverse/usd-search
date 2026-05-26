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

set -eux

# Default data directory to /data but allow override via environment variable
DATA_DIR=${DATA_DIR:-/data}

echo "Installing curl and jq if not present..."
if [ -f /etc/alpine-release ] || grep -qi 'ID=alpine' /etc/os-release 2>/dev/null; then
	echo "Detected Alpine Linux; installing with apk..."
	apk add --no-cache curl jq
else
	echo "Detected non-Alpine Linux; installing with apt..."
	apt update && apt install -y curl jq
fi

echo "Installing elasticdump..."
npm install -g elasticdump

echo "Contents of $DATA_DIR:"
ls -la "$DATA_DIR"

find "$DATA_DIR" -type f -name "*.json" || exit 1

echo "Processing files..."
# Create indices by combining settings and mappings, and PUT in one request
find "$DATA_DIR" -maxdepth 1 -type f -name "*.settings.json" | while read -r settings_file; do
	index_name=$(basename "$settings_file" .settings.json)
	mapping_file="$DATA_DIR/$index_name.mapping.json"

	echo "Preparing combined index creation for: $index_name"
	echo "Settings file: $settings_file"
	echo "Mapping file: $mapping_file"

	if [ ! -f "$mapping_file" ]; then
		echo "Mapping file not found for index $index_name, expected: $mapping_file"
		exit 1
	fi

	# Extract nested settings and mappings from files of the form:
	# {"<index_name>": {"settings": {...}}} and {"<index_name>": {"mappings": {...}}}
	settings_obj=$(jq -c 'def norm: (if type=="string" then (try fromjson catch .) else . end); norm | (if has("settings") then .settings else to_entries[0].value.settings end)' "$settings_file")
	mappings_obj=$(jq -c 'def norm: (if type=="string" then (try fromjson catch .) else . end); norm | (if has("mappings") then .mappings else to_entries[0].value.mappings end)' "$mapping_file")

	if [ -z "$settings_obj" ] || [ "$settings_obj" = "null" ]; then
		echo "Failed to extract settings for $index_name from $settings_file"
		exit 1
	fi
	if [ -z "$mappings_obj" ] || [ "$mappings_obj" = "null" ]; then
		echo "Failed to extract mappings for $index_name from $mapping_file"
		exit 1
	fi

	echo "Deleting index $index_name if it exists..."
	curl -sS -X DELETE "http://${OPENSEARCH_HOST}/$index_name" || true

	echo "Creating index $index_name with settings and mappings in a single PUT..."
	if jq -n --argjson settings "$settings_obj" --argjson mappings "$mappings_obj" \
		'{settings: $settings, mappings: $mappings}
		| (if (.settings|type) == "object" and (.settings|has("index")) then
				.settings.index |= (del(.["knn.derived_source"]))
		   else . end)' \
		| curl -sS -X PUT "http://${OPENSEARCH_HOST}/$index_name" \
			-H 'Content-Type: application/json' \
			--data-binary @-; then
		echo "Successfully created index $index_name with combined settings and mappings"
	else
		echo "Failed to create index $index_name with combined settings and mappings"
		exit 1
	fi
done

# Then load all data
find "$DATA_DIR" -maxdepth 1 -type f -name "*.data.json" | while read -r file; do
    index_name=$(basename "$file" .data.json)
    echo "Loading data from file: $file"
    echo "Full path: $file"
    if elasticdump \
        --input="$file" \
        --output="http://${OPENSEARCH_HOST}/$index_name" \
        --type=data \
        --limit=1000 \
        --debug=false; then
        echo "Successfully loaded data from $file"
    else
        echo "Failed to load data from $file"
        exit 1
    fi
done
