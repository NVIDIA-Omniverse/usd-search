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

export interface CallAPIOptions<T> {
  http: () => Promise<T>;
  ws: () => Promise<T>;
}

export async function callAPI<T>({ http, ws }: CallAPIOptions<T>): Promise<T> {
  let result: T | null = null;

  if (window.location.hostname !== "localhost" && window.location.hostname !== "127.0.0.1") {
    try {
      result = await http();
    } catch (error) {}
  }

  if (!result) {
    result = await ws();
  }

  return result;
}
