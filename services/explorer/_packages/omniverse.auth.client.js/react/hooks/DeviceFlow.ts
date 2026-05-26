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

import { DeviceFlow } from "@omniverse/auth";
import { DeviceSubmit } from "@omniverse/auth/data";
import { useCallback } from "react";
import connect from "../Connection";
import useNucleusSession from "./NucleusSession";

export interface DeviceFlowSubmit {
  code: string;
}

export function useDeviceFlowSubmit() {
  const { getSession } = useNucleusSession();

  return useCallback(
    async ({ code }: DeviceFlowSubmit): Promise<DeviceSubmit> => {
      const session = await getSession();
      if (!session) {
        throw new Error("You must be authenticated to send the user code.");
      }

      let deviceFlow: DeviceFlow | null = null;
      try {
        deviceFlow = await connect(session.server, DeviceFlow);
      } catch (error) {
        throw new Error(`Failed to connect to the service. (${error})`);
      }

      try {
        return await deviceFlow.submit({ access_token: session.accessToken, user_code: code });
      } finally {
        if (deviceFlow) {
          await deviceFlow.transport.close();
        }
      }
    },
    [getSession]
  );
}
