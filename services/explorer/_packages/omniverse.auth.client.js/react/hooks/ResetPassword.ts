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

import { Credentials, Tokens } from "@omniverse/auth";
import { Auth, AuthStatus } from "@omniverse/auth/data";
import AuthMessages from "../AuthMessages";
import connect from "../Connection";

export interface GenerateResetPasswordPayloadOptions {
  /**
   * Extra state that will be encoded into the payload.
   */
  state?: Record<string, string>;
}

export interface ResetPasswordPayload {
  username: string;
  token: string;
  server: string;
  state?: Record<string, string>;
}

export async function encodeResetPasswordPayload(
  server: string,
  username: string,
  adminToken: string,
  { state }: GenerateResetPasswordPayloadOptions = {}
): Promise<string> {
  const tokens = await connect(server, Tokens, { generate: 0 });
  try {
    const result = await tokens.generate({ username, admin_token: adminToken });
    if (result.status !== AuthStatus.OK) {
      throw new GenerateResetPasswordPayloadError(result);
    }

    const payload: ResetPasswordPayload = {
      token: result.access_token!,
      username,
      server,
      state,
    };

    return await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = reader.result!.toString();
        const [, content] = result.split(",");
        resolve(content);
      };
      reader.onerror = reject;
      reader.readAsDataURL(new Blob([JSON.stringify(payload)]));
    });

  } finally {
    await tokens.transport.close();
  }
}

export class GenerateResetPasswordPayloadError extends Error {
  public readonly messages: { [status: string]: string } = {
    ...AuthMessages,
    [AuthStatus.Denied]: "You don't have access to generate tokens for this user.",
  };
  public readonly result: { status: AuthStatus };

  constructor(result: { status: AuthStatus }) {
    super();
    this.result = result;
    this.message = this.messages[result.status] || DefaultErrorMessage(result.status);
  }
}

export function decodeResetPasswordPayload(encoded: string): ResetPasswordPayload {
  const json: ResetPasswordPayload = JSON.parse(atob(encoded));
  if (!json.username || !json.token || !json.server) {
    throw new Error("Invalid reset password payload.");
  }
  return json;
}

export async function resetPassword(
  newPassword: string,
  { server, username, token }: ResetPasswordPayload
): Promise<Auth> {
  const credentials = await connect(server, Credentials, { reset: 0 });
  try {
    const response = await credentials.reset({ username, new_password: newPassword, token });
    if (response.status !== AuthStatus.OK) {
      throw new ResetPasswordError(response);
    }
    return response;
  } finally {
    await credentials.transport.close();
  }
}

export class ResetPasswordError extends Error {
  public readonly messages: { [status: string]: string } = {
    ...AuthMessages,
    [AuthStatus.Expired]: "The link has expired.",
  };
  public readonly result: { status: AuthStatus };

  constructor(result: { status: AuthStatus }) {
    super();
    this.result = result;
    this.message = this.messages[result.status] || DefaultErrorMessage(result.status);
  }
}

export const DefaultErrorMessage = (status: string) => `Unknown error, please contact administrator (${status}).`;