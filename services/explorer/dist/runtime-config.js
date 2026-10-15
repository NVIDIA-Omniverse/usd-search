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

/*
 * Runtime deployment config — loaded by index.html BEFORE the app bundle.
 *
 * This shipped copy is a deliberate no-op. A deployment configures the
 * Explorer WITHOUT rebuilding the image, either by setting the
 * EXPLORER_SERVER_MAPPING / EXPLORER_DEFAULT_SERVER container env vars
 * (docker/explorer-entrypoint.sh renders this file at start-up) or by
 * overwriting the file directly
 * (e.g. `- ./config.gen.js:/app/runtime-config.js:ro` in docker-compose):
 *
 *   window.__SERVER_MAPPING__ = {
 *     "<server-key>": {              // the x-usdsearch-storage-backend value
 *       name: "Display name",        //   shown in the account-popover picker
 *       apiUrl: "",                  //   "" = same-origin (gateway routes by header)
 *       embedding_config: { field_name: "siglip2-embedding.embedding", dimension: 1536 },
 *     },
 *     ...
 *   };
 *   window.__DEFAULT_SERVER__ = "<server-key>";  // selected when no ?server=
 *
 * Falls back to the build-time REACT_APP_SERVER_MAPPING when unset.
 */
