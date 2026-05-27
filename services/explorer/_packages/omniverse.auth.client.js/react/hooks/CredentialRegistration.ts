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
import { AuthStatus, Profile } from "@omniverse/auth/data";
import { useCallback } from "react";
import { AuthenticationResult } from "../AuthForm";
import AuthMessages from "../AuthMessages";
import connect, { handleConnectionErrors } from "../Connection";
import { RegistrationFormFields } from "../RegistrationForm";

export default function useCredentialRegistration() {
  return useCallback(
    async ({
      username,
      password,
      server,
      firstName,
      lastName,
      email,
      nonce,
    }: RegistrationFormFields): Promise<AuthenticationResult> => {
      let credentials: Credentials | null = null;

      if (!server) {
        return {
          errors: ["You have to specify the server."],
          server: "",
        };
      }

      const profile: Profile = {
        first_name: firstName,
        last_name: lastName,
        email,
      };

      return connect(server, Credentials, { "register": 0 })
        .then((conn) => (credentials = conn))
        .then((credentials) =>
          credentials.register({ username, password, profile, nonce })
        )
        .then((result): AuthenticationResult =>
          result.status === AuthStatus.OK
            ? {
                server,
                status: result.status,
                accessToken: result.access_token,
                refreshToken: result.refresh_token,
                username: result.username,
                profile: result.profile,
                nonce: result.nonce,
              }
            : {
                server,
                status: result.status,
                errors: [AuthMessages[result.status]],
                nonce: result.nonce,
              }
        )
        .catch((error) => {
          return handleConnectionErrors(server, error);
        })
        .finally(() => {
          if (credentials) {
            credentials.transport.close();
          }
        });
    },
    []
  );
}
