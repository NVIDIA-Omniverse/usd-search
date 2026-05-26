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

import { Credentials } from "@omniverse/auth/client";
import { CredentialSettings } from "@omniverse/auth/data";
import { useCallback, useEffect, useState } from "react";
import connect from "../Connection";
import { callAPI } from "../util/API";

export default function useCredentialSettings(server: string): {
  settings: CredentialSettings | null;
  errors: string[];
  retry: () => unknown;
} {
  const [settings, setSettings] = useState<CredentialSettings | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [queryDate, setQueryDate] = useState(() => new Date());

  const retry = useCallback(() => {
    setQueryDate(new Date());
  }, []);

  useEffect(() => {
    let subscribed = true;
    setSettings(null);
    setErrors([]);

    let debounced: number;
    if (server) {
      debounced = window.setTimeout(async () => {
        try {
          const settings = await callAPI({
            http: () => httpCredentialSettings(server),
            ws: () => wsCredentialSettings(server),
          });

          if (subscribed) {
            setSettings(settings);
          }
        } catch (error) {
          setErrors([`Failed to connect to the server (${error}).`]);
          console.warn(error);
        }
      }, 300);
    }

    return () => {
      subscribed = false;
      if (debounced) {
        clearTimeout(debounced);
      }
    };
  }, [server, queryDate]);

  return { settings, errors, retry };
}

async function httpCredentialSettings(server: string): Promise<CredentialSettings> {
  const response = await fetch(`https://${server}/omni/auth/api/sso/settings`, { cache: "force-cache" });
  const json = await response.json();
  return {
    can_register: json.can_register,
    is_ui_visible: json.can_use_credentials,
    login_url: json.login_url,
  };
}

async function wsCredentialSettings(server: string): Promise<CredentialSettings> {
  let credentials: Credentials | null = null;
  try {
    credentials = await connect(server, Credentials, { get_settings: 0 });
    return await credentials.getSettings();
  } finally {
    if (credentials) {
      await credentials.transport.close();
    }
  }
}
