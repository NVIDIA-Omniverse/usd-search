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

set -eu

OPENSEARCH_HOST="${OPENSEARCH_HOST:-opensearch:9200}"

echo "Waiting for OpenSearch to be ready..."
until curl -sf "http://${OPENSEARCH_HOST}/_cluster/health" | grep -qE '"status":"(green|yellow)"'; do
    echo "  OpenSearch not ready yet, retrying in 2s..."
    sleep 2
done
echo "OpenSearch is ready."

# --- Create main search index ---
INDEX_NAME="usdsearch-quickstart-ver5.0"
echo "Creating index: ${INDEX_NAME}"

curl -sf -X DELETE "http://${OPENSEARCH_HOST}/${INDEX_NAME}" || true

curl -sf -X PUT "http://${OPENSEARCH_HOST}/${INDEX_NAME}" \
  -H 'Content-Type: application/json' \
  -d '{
  "settings": {
    "index": {
      "number_of_shards": "1",
      "number_of_replicas": "0",
      "knn": "true",
      "analysis": {
        "analyzer": {
          "custom_path_tree_reversed": { "tokenizer": "custom_hierarchy_reversed" },
          "custom_path_tree": { "tokenizer": "custom_hierarchy" }
        },
        "tokenizer": {
          "custom_hierarchy": { "type": "path_hierarchy", "delimiter": "/" },
          "custom_hierarchy_reversed": { "reverse": "true", "type": "path_hierarchy", "delimiter": "/" }
        }
      }
    }
  },
  "mappings": {
    "dynamic_templates": [
      { "search_as_you_type_mappings": { "match": "*_sayt", "match_mapping_type": "string", "mapping": { "type": "search_as_you_type" } } },
      { "usd_properties": { "match": "usd_properties", "mapping": { "type": "nested" } } },
      { "usd_properties_sayt": { "path_match": "usd_properties.*_sayt", "match_mapping_type": "string", "mapping": { "type": "search_as_you_type" } } },
      { "usd_properties_keyword": { "path_match": "usd_properties.*", "match_mapping_type": "string", "mapping": { "type": "keyword" } } },
      { "usd_dimensions": { "match": "usd_dimensions", "mapping": { "type": "object" } } },
      { "usd_dimensions_float": { "path_match": "usd_dimensions.*", "match_mapping_type": "double", "mapping": { "type": "float" } } },
      { "usd_dimensions_string": { "path_match": "usd_dimensions.*", "match_mapping_type": "string", "mapping": { "type": "keyword" } } }
    ],
    "properties": {
      "base_key": { "type": "keyword" },
      "siglip2-embedding": {
        "type": "nested",
        "properties": {
          "embedding": {
            "type": "knn_vector",
            "dimension": 1536,
            "method": { "engine": "faiss", "space_type": "innerproduct", "name": "hnsw", "parameters": { "ef_search": 512, "ef_construction": 512, "m": 32 } }
          },
          "image": { "type": "keyword" },
          "keyword": { "type": "keyword" },
          "label": { "type": "text" }
        }
      },
      "embedding-1": {
        "type": "nested",
        "properties": {
          "embedding": {
            "type": "knn_vector",
            "dimension": 1536,
            "method": { "engine": "faiss", "space_type": "innerproduct", "name": "hnsw", "parameters": { "ef_search": 512, "ef_construction": 512, "m": 32 } }
          },
          "image": { "type": "keyword" },
          "keyword": { "type": "keyword" },
          "label": { "type": "text" }
        }
      },
      "created_by": { "type": "keyword" },
      "created_timestamp": { "type": "date" },
      "deleted_by": { "type": "keyword" },
      "deleted_timestamp": { "type": "date" },
      "empty": { "type": "boolean" },
      "etag": { "type": "keyword" },
      "ext": { "type": "keyword" },
      "hash_block_size": { "type": "long" },
      "hash_type": { "type": "keyword" },
      "hash_value": { "type": "keyword" },
      "is_deleted": { "type": "boolean" },
      "modified_by": { "type": "keyword" },
      "modified_timestamp": { "type": "date" },
      "name": {
        "type": "keyword",
        "fields": {
          "simple": { "type": "text", "analyzer": "simple" },
          "standard": { "type": "text", "analyzer": "standard" }
        }
      },
      "on_mount": { "type": "boolean" },
      "path": {
        "type": "keyword",
        "fields": {
          "tree": { "type": "text", "analyzer": "custom_path_tree" },
          "tree_reversed": { "type": "text", "analyzer": "custom_path_tree_reversed" }
        }
      },
      "pathType": { "type": "keyword" },
      "size": { "type": "long" },
      "status": { "type": "keyword" },
      "statusDescription": { "type": "text" },
      "tag": { "type": "keyword" },
      "tags": {
        "type": "nested",
        "include_in_root": true,
        "properties": {
          "namespace": { "type": "keyword" },
          "tag": { "type": "keyword" },
          "value": { "type": "keyword" }
        }
      },
      "text": { "type": "text" },
      "usd_properties": {
        "type": "nested",
        "properties": {
          "name": { "type": "keyword" },
          "name_sayt": { "type": "search_as_you_type", "doc_values": false, "max_shingle_size": 3 },
          "value": { "type": "keyword" },
          "value_sayt": { "type": "search_as_you_type", "doc_values": false, "max_shingle_size": 3 }
        }
      }
    }
  }
}' && echo " OK" || echo " FAILED"

# --- Create image cache index ---
CACHE_INDEX="usdsearch-quickstart-ver4.0-image-cache"
echo "Creating index: ${CACHE_INDEX}"

curl -sf -X DELETE "http://${OPENSEARCH_HOST}/${CACHE_INDEX}" || true

curl -sf -X PUT "http://${OPENSEARCH_HOST}/${CACHE_INDEX}" \
  -H 'Content-Type: application/json' \
  -d '{
  "settings": {
    "index": {
      "number_of_shards": "1",
      "number_of_replicas": "0"
    }
  },
  "mappings": {
    "properties": {
      "base_key": { "type": "keyword" },
      "image_url": { "type": "keyword" },
      "cached_at": { "type": "date" }
    }
  }
}' && echo " OK" || echo " FAILED"

echo ""
echo "OpenSearch indices initialized successfully."
