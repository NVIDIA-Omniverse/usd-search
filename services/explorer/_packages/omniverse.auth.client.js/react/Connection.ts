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

import DiscoverySearch, { ClientType, DiscoveryError } from "@omniverse/discovery";

export default async function connect<T>(
  server: string,
  clientType: ClientType<T>,
  capabilities: Record<string, number> = {}
): Promise<T> {
  const discovery = new DiscoverySearch(server);
  try {
    const supportedTransport = undefined;
    const client = await discovery.find(clientType, { deployment: "external" }, supportedTransport, capabilities);
    if (!client) {
      throw new DiscoveryError();
    }
    return client;
  } finally {
    discovery.close();
  }
}

export function handleConnectionErrors(server: string, error: Error) {
  console.error(error);
  if (error instanceof Event && error.type === "error") {
    return {
      server,
      errors: [`Cannot connect to the authentication service. (${error.message})`],
    };
  }
  if (error instanceof DiscoveryError) {
    return {
      server,
      errors: [`Cannot connect to the authentication service. (${error.message})`],
    };
  }
  return {
    server,
    errors: [`Unexpected error. Try again later.`],
  };
}
