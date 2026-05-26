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

/**
 * Per-server auth-credential storage with explicit auth-method selection.
 *
 * Each backend can be authenticated via one of three methods:
 *   - "nucleus_token": Nucleus long-lived API token obtained via device flow.
 *                      Sent as Basic auth with username `$omni-api-token`.
 *   - "basic":         Arbitrary username + password sent as standard Basic auth.
 *   - "api_key":       USD-Search-issued API key sent as the `x-api-key` header.
 *
 * Credentials for each method live in their own localStorage slot so switching
 * methods never clobbers another method's saved value.
 */

import { AUTH_CONFIG } from "../config";

export const AUTH_METHODS = Object.freeze({
  NUCLEUS_TOKEN: "nucleus_token",
  BASIC: "basic",
  API_KEY: "api_key",
});

const FIELDS = ["auth_method", "api_key", "nucleus_api_token", "username", "password"];

const NUCLEUS_TOKEN_USERNAME = "$omni-api-token";

function key(serverKey, field) {
  return serverKey ? `${serverKey}_${field}` : field;
}

function isNucleusBackend(backendString) {
  return !!(backendString && backendString.toLowerCase().includes("omniverse://"));
}

/**
 * Detect and migrate the legacy storage shape in which a device-flow Nucleus
 * token was kept as `password` with `username = "$omni-api-token"`. Move the
 * token into its own `nucleus_api_token` slot, clear username/password, and
 * pin the auth method to `nucleus_token`. Idempotent; safe to call on every read.
 */
export function migrateLegacyNucleusToken(serverKey) {
  const username = localStorage.getItem(key(serverKey, "username"));
  const password = localStorage.getItem(key(serverKey, "password"));
  if (username !== NUCLEUS_TOKEN_USERNAME || !password) return;

  const existingToken = localStorage.getItem(key(serverKey, "nucleus_api_token"));
  if (!existingToken) {
    localStorage.setItem(key(serverKey, "nucleus_api_token"), password);
  }
  localStorage.removeItem(key(serverKey, "username"));
  localStorage.removeItem(key(serverKey, "password"));
  if (!localStorage.getItem(key(serverKey, "auth_method"))) {
    localStorage.setItem(key(serverKey, "auth_method"), AUTH_METHODS.NUCLEUS_TOKEN);
  }
}

/**
 * Read all stored auth state for a server. Runs the legacy-shape migration
 * first so callers never see the deprecated representation.
 */
export function readAuth(serverKey) {
  migrateLegacyNucleusToken(serverKey);
  return {
    method: localStorage.getItem(key(serverKey, "auth_method")) || "",
    api_key: localStorage.getItem(key(serverKey, "api_key")) || "",
    nucleus_api_token: localStorage.getItem(key(serverKey, "nucleus_api_token")) || "",
    username: localStorage.getItem(key(serverKey, "username")) || "",
    password: localStorage.getItem(key(serverKey, "password")) || "",
  };
}

export function writeAuthMethod(serverKey, method) {
  localStorage.setItem(key(serverKey, "auth_method"), method);
}

export function writeCredential(serverKey, field, value) {
  if (!FIELDS.includes(field) || field === "auth_method") {
    throw new Error(`Unknown credential field: ${field}`);
  }
  localStorage.setItem(key(serverKey, field), value || "");
}

export function clearCredential(serverKey, field) {
  localStorage.removeItem(key(serverKey, field));
}

/**
 * Pick a sensible default auth method when none is stored. Used both on first
 * load and as the fallback for `buildAuthHeaders`.
 *
 * Selection order:
 *   1. Nucleus backends → `nucleus_token` (the canonical Nucleus path).
 *      Wins even if another method has stale stored credentials, since the
 *      basic-auth slot may contain leftover values from a pre-backend-resolution
 *      placeholder.
 *   2. Otherwise, prefer a method whose credential is already populated, so
 *      returning users on non-Nucleus backends keep their session.
 *   3. Otherwise, fall back to `basic`.
 *
 * Methods disabled via AUTH_CONFIG.ENABLE_* are skipped.
 */
export function selectDefaultMethod(serverKey, backendString) {
  const stored = readAuth(serverKey);
  const enabled = enabledMethods();

  if (isNucleusBackend(backendString) && enabled.includes(AUTH_METHODS.NUCLEUS_TOKEN)) {
    return AUTH_METHODS.NUCLEUS_TOKEN;
  }

  const ordered = [
    [AUTH_METHODS.API_KEY, stored.api_key],
    [AUTH_METHODS.BASIC, stored.username || stored.password],
    [AUTH_METHODS.NUCLEUS_TOKEN, stored.nucleus_api_token],
  ];
  for (const [method, populated] of ordered) {
    if (populated && enabled.includes(method)) return method;
  }

  if (enabled.includes(AUTH_METHODS.BASIC)) return AUTH_METHODS.BASIC;
  return enabled[0] || AUTH_METHODS.BASIC;
}

export function enabledMethods() {
  const list = [];
  if (AUTH_CONFIG.ENABLE_NUCLEUS_AUTH) list.push(AUTH_METHODS.NUCLEUS_TOKEN);
  if (AUTH_CONFIG.ENABLE_BASIC_AUTH) list.push(AUTH_METHODS.BASIC);
  if (AUTH_CONFIG.ENABLE_API_KEY_AUTH) list.push(AUTH_METHODS.API_KEY);
  return list;
}

/**
 * Return the auth headers that should accompany an API request. Honors the
 * explicit `auth_method` selection; falls back to `selectDefaultMethod` when
 * none is stored so the very first request after a fresh install still works.
 */
export function buildAuthHeaders(serverKey, backendString) {
  const stored = readAuth(serverKey);
  const method = stored.method || selectDefaultMethod(serverKey, backendString);

  switch (method) {
    case AUTH_METHODS.API_KEY:
      if (stored.api_key) return { "x-api-key": stored.api_key };
      break;
    case AUTH_METHODS.BASIC:
      if (stored.username) {
        return {
          Authorization: "Basic " + btoa(`${stored.username}:${stored.password || ""}`),
        };
      }
      break;
    case AUTH_METHODS.NUCLEUS_TOKEN:
      if (stored.nucleus_api_token) {
        return {
          Authorization:
            "Basic " + btoa(`${NUCLEUS_TOKEN_USERNAME}:${stored.nucleus_api_token}`),
        };
      }
      break;
    default:
      break;
  }
  return {};
}

/**
 * True iff the credential for the currently selected method is populated.
 * Used to drive the "Authenticated" indicator in the UI.
 */
export function isAuthSatisfied(serverKey, backendString) {
  const stored = readAuth(serverKey);
  const method = stored.method || selectDefaultMethod(serverKey, backendString);
  switch (method) {
    case AUTH_METHODS.API_KEY:
      return !!stored.api_key;
    case AUTH_METHODS.BASIC:
      return !!stored.username;
    case AUTH_METHODS.NUCLEUS_TOKEN:
      return !!stored.nucleus_api_token;
    default:
      return false;
  }
}

export { NUCLEUS_TOKEN_USERNAME };
