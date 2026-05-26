/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

// If not set it uses the local 'api/' endpoint
export const apiUrl = process.env.REACT_APP_API_URL || "";

export const defaultEmbeddingFieldName = process.env.REACT_APP_DEFAULT_EMBEDDING_FIELD_NAME || "siglip2-embedding.embedding";
export const defaultEmbeddingDimension = process.env.REACT_APP_DEFAULT_EMBEDDING_DIMENSION || 1536;

// Default embedding configuration
export const defaultEmbeddingConfig = {
  field_name: defaultEmbeddingFieldName,
  dimension: 1536
};

// Server name to URL mapping configuration
// Expects a JSON string in format: {"server1": "http://url1", "server2": "http://url2"}
let serverMapping = {};
try {
  const mappingStr = process.env.REACT_APP_SERVER_MAPPING || "{}";
  serverMapping = JSON.parse(mappingStr);
} catch (error) {
  console.error("Failed to parse SERVER_MAPPING configuration:", error);
  serverMapping = {};
}
export const SERVER_MAPPING = serverMapping;

// Image processing configuration
export const IMAGE_SIZE = 224;

// Duplicate removal configuration
export const DUPLICATE_REMOVAL_THRESHOLD = process.env.REACT_APP_DUPLICATE_REMOVAL_THRESHOLD || 0.0001;

// Check if running on HTTPS (required for clipboard API)
export const IS_HTTPS = typeof window !== 'undefined' && window.location.protocol === 'https:';

// Feature flags configuration
export const FEATURE_FLAGS = {
  // Enable/disable feedback modal - enabled by default, can be disabled via env var
  ENABLE_FEEDBACK_MODAL: process.env.REACT_APP_ENABLE_FEEDBACK_MODAL === "true",
};

// Validation configuration
export const VALIDATION_CONFIG = {
  MAX_CONCURRENT: parseInt(process.env.REACT_APP_VALIDATION_MAX_CONCURRENT || "8", 10),
  MAX_RETRIES: parseInt(process.env.REACT_APP_VALIDATION_MAX_RETRIES || "3", 10),
  RETRY_DELAY_MS: parseInt(process.env.REACT_APP_VALIDATION_RETRY_DELAY_MS || "5000", 10),
  TIMEOUT_MS: parseInt(process.env.REACT_APP_VALIDATION_TIMEOUT_MS || "30000", 10),
};

// Authentication configuration
export const AUTH_CONFIG = {
  // All three authentication methods are available by default; each can be
  // explicitly disabled with REACT_APP_ENABLE_*_AUTH="false".
  ENABLE_NUCLEUS_AUTH: process.env.REACT_APP_ENABLE_NUCLEUS_AUTH !== "false",
  ENABLE_API_KEY_AUTH: process.env.REACT_APP_ENABLE_API_KEY_AUTH !== "false",
  ENABLE_BASIC_AUTH: process.env.REACT_APP_ENABLE_BASIC_AUTH !== "false",

  // Default values if provided
  DEFAULT_NUCLEUS_TOKEN: process.env.REACT_APP_DEFAULT_NUCLEUS_TOKEN || "",
  DEFAULT_API_KEY: process.env.REACT_APP_DEFAULT_API_KEY || "",
  DEFAULT_USERNAME: process.env.REACT_APP_DEFAULT_USERNAME || "",
  DEFAULT_PASSWORD: process.env.REACT_APP_DEFAULT_PASSWORD || "",
};
