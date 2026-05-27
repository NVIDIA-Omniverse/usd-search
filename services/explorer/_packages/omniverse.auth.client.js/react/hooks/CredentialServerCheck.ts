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

import { Credentials } from "@omniverse/auth";
import { useCallback } from "react";
import connect from "../Connection";

export interface CredentialServerCheck {
  ok: boolean;
  server: string;
  errors?: string[];
}

export default function useCredentialServerCheck() {
  return useCallback(async (server: string): Promise<CredentialServerCheck> => {
    server = server.trim();
    if (!server) {
      return {
        ok: false,
        server,
        errors: ["You have to specify the server."],
      };
    }

    const omniverseProtocol = "omniverse://";
    const omniverse = server.indexOf(omniverseProtocol);
    if (omniverse !== -1) {
      server = server.substring(omniverse + omniverseProtocol.length);
      server = server.substring(0, server.indexOf("/"));
    } else {
      const match = server.match("https?://");
      if (match) {
        const [protocol] = match;
        server = server.substring(protocol.length);
        server = server.substring(0, server.indexOf("/"));
      }
    }

    let resolvedServer = await getCanonicalName(server);
    if (!resolvedServer) {
      console.log(`Cannot resolve the hostname, proceed with ${server}...`);
      resolvedServer = server;
    }

    try {
      const response = await fetch(`https://${resolvedServer}/omni/auth/api`);
      if (response.ok) {
        return {
          ok: true,
          server: resolvedServer,
        };
      }
    } catch (error) {}

    try {
      const connection = await connect(resolvedServer, Credentials, { auth: 0 });
      await connection.transport.close();
      return {
        ok: true,
        server: resolvedServer,
      };
    } catch (error) {
      console.log(error);
      return {
        ok: false,
        server,
        errors: [`Failed to connect to the server. (${error})`],
      };
    }
  }, []);
}

export async function getCanonicalName(server: string): Promise<string> {
  if (["127.0.0.1", "localhost"].includes(server)) {
    return server;
  }

  try {
    const response = await fetch(`http://${server}/_sys/canonical-name-json`);
    const data = await response.json();
    return data.fqdn ? data.fqdn : "";
  } catch (error) {
    return "";
  }
}
