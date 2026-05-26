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

import { Auth, AuthStatus } from "@omniverse/auth/data";
import AuthMessages from "../AuthMessages";
import {
  encodeResetPasswordPayload,
  GenerateResetPasswordPayloadError,
  GenerateResetPasswordPayloadOptions,
  resetPassword,
  ResetPasswordError,
  ResetPasswordPayload
} from "./ResetPassword";


export type InvitationPayload = ResetPasswordPayload;

export function encodeInvitationPayload(
  server: string,
  username: string,
  adminToken: string,
  { state }: GenerateResetPasswordPayloadOptions = {}
): Promise<string> {
  try {
    return encodeResetPasswordPayload(server, username, adminToken, { state });
  } catch (error) {
    if (error instanceof GenerateResetPasswordPayloadError) {
      throw new GenerateInvitationPayloadError(error.result);
    }
    throw error;
  }
}

export class GenerateInvitationPayloadError extends Error {
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

export function decodeInvitationPayload(encoded: string): InvitationPayload {
  const json: InvitationPayload = JSON.parse(atob(encoded));
  if (!json.username || !json.token || !json.server) {
    throw new Error("Invalid invitation payload.");
  }
  return json;
}

export async function inviteUser(password: string, payload: InvitationPayload): Promise<Auth> {
  try {
    return resetPassword(password, payload);
  } catch (error) {
    if (error instanceof ResetPasswordError) {
      throw new InvitationError(error.result);
    }
    throw error;
  }
}

export class InvitationError extends Error {
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