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

export type Capabilities = {
  [function_name: string]: number,
};

export type DeviceFlowServerRemoteCapabilities = Capabilities;

export class DeviceFlowServerLocalCapabilities {
  public static value: {'authorize': 0, 'submit': 0, 'token': 0};
}

export type DeviceFlowServerCapabilities = DeviceFlowServerRemoteCapabilities;

export type DeviceFlowClientRemoteCapabilities = Capabilities;

export class DeviceFlowClientLocalCapabilities {
  public static value: {'authorize': 0, 'submit': 0, 'token': 0};
}

export type DeviceFlowClientCapabilities = DeviceFlowClientLocalCapabilities;

export type DeviceFlowTokenServerRemoteVersion = number;

export class DeviceFlowTokenServerLocalVersion {
  public static value: 0;
}

export type DeviceFlowTokenServerVersion = DeviceFlowTokenServerRemoteVersion;

export type DeviceFlowTokenClientRemoteVersion = number;

export class DeviceFlowTokenClientLocalVersion {
  public static value: 0;
}

export type DeviceFlowSubmitServerRemoteVersion = number;

export class DeviceFlowSubmitServerLocalVersion {
  public static value: 0;
}

export type DeviceFlowSubmitServerVersion = DeviceFlowSubmitServerRemoteVersion;

export type DeviceFlowSubmitClientRemoteVersion = number;

export class DeviceFlowSubmitClientLocalVersion {
  public static value: 0;
}

export type DeviceFlowAuthorizeServerRemoteVersion = number;

export class DeviceFlowAuthorizeServerLocalVersion {
  public static value: 0;
}

export type DeviceFlowAuthorizeServerVersion = DeviceFlowAuthorizeServerRemoteVersion;

export type DeviceFlowAuthorizeClientRemoteVersion = number;

export class DeviceFlowAuthorizeClientLocalVersion {
  public static value: 0;
}

export type UserStoreServerRemoteCapabilities = Capabilities;

export class UserStoreServerLocalCapabilities {
  public static value: {'get': 0, 'set': 0, 'remove': 0};
}

export type UserStoreServerCapabilities = UserStoreServerRemoteCapabilities;

export type UserStoreClientRemoteCapabilities = Capabilities;

export class UserStoreClientLocalCapabilities {
  public static value: {'get': 0, 'set': 0, 'remove': 0};
}

export type UserStoreClientCapabilities = UserStoreClientLocalCapabilities;

export type UserStoreRemoveServerRemoteVersion = number;

export class UserStoreRemoveServerLocalVersion {
  public static value: 0;
}

export type UserStoreRemoveServerVersion = UserStoreRemoveServerRemoteVersion;

export type UserStoreRemoveClientRemoteVersion = number;

export class UserStoreRemoveClientLocalVersion {
  public static value: 0;
}

export type UserStoreSetServerRemoteVersion = number;

export class UserStoreSetServerLocalVersion {
  public static value: 0;
}

export type UserStoreSetServerVersion = UserStoreSetServerRemoteVersion;

export type UserStoreSetClientRemoteVersion = number;

export class UserStoreSetClientLocalVersion {
  public static value: 0;
}

export type UserStoreGetServerRemoteVersion = number;

export class UserStoreGetServerLocalVersion {
  public static value: 0;
}

export type UserStoreGetServerVersion = UserStoreGetServerRemoteVersion;

export type UserStoreGetClientRemoteVersion = number;

export class UserStoreGetClientLocalVersion {
  public static value: 0;
}

export type TokensServerRemoteCapabilities = Capabilities;

export class TokensServerLocalCapabilities {
  public static value: {'generate': 2, 'refresh': 1, 'invalidate': 0, 'subscribe': 0, 'create_api_token': 2, 'delete_api_token': 0, 'get_api_tokens': 0, 'auth_with_api_token': 1};
}

export type TokensServerCapabilities = TokensServerRemoteCapabilities;

export type TokensClientRemoteCapabilities = Capabilities;

export class TokensClientLocalCapabilities {
  public static value: {'generate': 2, 'refresh': 1, 'invalidate': 0, 'subscribe': 0, 'create_api_token': 2, 'delete_api_token': 0, 'get_api_tokens': 0, 'auth_with_api_token': 1};
}

export type TokensClientCapabilities = TokensClientLocalCapabilities;

export type TokensAuthWithApiTokenServerRemoteVersion = number;

export class TokensAuthWithApiTokenServerLocalVersion {
  public static value: 1;
}

export type TokensAuthWithApiTokenServerVersion = TokensAuthWithApiTokenServerRemoteVersion;

export type TokensAuthWithApiTokenClientRemoteVersion = number;

export class TokensAuthWithApiTokenClientLocalVersion {
  public static value: 1;
}

export type TokensGetApiTokensServerRemoteVersion = number;

export class TokensGetApiTokensServerLocalVersion {
  public static value: 0;
}

export type TokensGetApiTokensServerVersion = TokensGetApiTokensServerRemoteVersion;

export type TokensGetApiTokensClientRemoteVersion = number;

export class TokensGetApiTokensClientLocalVersion {
  public static value: 0;
}

export type TokensDeleteApiTokenServerRemoteVersion = number;

export class TokensDeleteApiTokenServerLocalVersion {
  public static value: 0;
}

export type TokensDeleteApiTokenServerVersion = TokensDeleteApiTokenServerRemoteVersion;

export type TokensDeleteApiTokenClientRemoteVersion = number;

export class TokensDeleteApiTokenClientLocalVersion {
  public static value: 0;
}

export type TokensCreateApiTokenServerRemoteVersion = number;

export class TokensCreateApiTokenServerLocalVersion {
  public static value: 2;
}

export type TokensCreateApiTokenServerVersion = TokensCreateApiTokenServerRemoteVersion;

export type TokensCreateApiTokenClientRemoteVersion = number;

export class TokensCreateApiTokenClientLocalVersion {
  public static value: 2;
}

export type TokensSubscribeServerRemoteVersion = number;

export class TokensSubscribeServerLocalVersion {
  public static value: 0;
}

export type TokensSubscribeServerVersion = TokensSubscribeServerRemoteVersion;

export type TokensSubscribeClientRemoteVersion = number;

export class TokensSubscribeClientLocalVersion {
  public static value: 0;
}

export type TokensInvalidateServerRemoteVersion = number;

export class TokensInvalidateServerLocalVersion {
  public static value: 0;
}

export type TokensInvalidateServerVersion = TokensInvalidateServerRemoteVersion;

export type TokensInvalidateClientRemoteVersion = number;

export class TokensInvalidateClientLocalVersion {
  public static value: 0;
}

export type TokensRefreshServerRemoteVersion = number;

export class TokensRefreshServerLocalVersion {
  public static value: 1;
}

export type TokensRefreshServerVersion = TokensRefreshServerRemoteVersion;

export type TokensRefreshClientRemoteVersion = number;

export class TokensRefreshClientLocalVersion {
  public static value: 1;
}

export type TokensGenerateServerRemoteVersion = number;

export class TokensGenerateServerLocalVersion {
  public static value: 2;
}

export type TokensGenerateServerVersion = TokensGenerateServerRemoteVersion;

export type TokensGenerateClientRemoteVersion = number;

export class TokensGenerateClientLocalVersion {
  public static value: 2;
}

export type SSOServerRemoteCapabilities = Capabilities;

export class SSOServerLocalCapabilities {
  public static value: {'get_settings': 0, 'auth': 2, 'redirect': 1};
}

export type SSOServerCapabilities = SSOServerRemoteCapabilities;

export type SSOClientRemoteCapabilities = Capabilities;

export class SSOClientLocalCapabilities {
  public static value: {'get_settings': 0, 'auth': 2, 'redirect': 1};
}

export type SSOClientCapabilities = SSOClientLocalCapabilities;

export type SSORedirectServerRemoteVersion = number;

export class SSORedirectServerLocalVersion {
  public static value: 1;
}

export type SSORedirectServerVersion = SSORedirectServerRemoteVersion;

export type SSORedirectClientRemoteVersion = number;

export class SSORedirectClientLocalVersion {
  public static value: 1;
}

export type SSOAuthServerRemoteVersion = number;

export class SSOAuthServerLocalVersion {
  public static value: 2;
}

export type SSOAuthServerVersion = SSOAuthServerRemoteVersion;

export type SSOAuthClientRemoteVersion = number;

export class SSOAuthClientLocalVersion {
  public static value: 2;
}

export type SSOGetSettingsServerRemoteVersion = number;

export class SSOGetSettingsServerLocalVersion {
  public static value: 0;
}

export type SSOGetSettingsClientRemoteVersion = number;

export class SSOGetSettingsClientLocalVersion {
  public static value: 0;
}

export type ProfilesServerRemoteCapabilities = Capabilities;

export class ProfilesServerLocalCapabilities {
  public static value: {'get_settings': 0, 'get_all': 0, 'get': 0, 'set_info': 2, 'set_enabled': 0, 'set_admin': 0, 'set_nucleus_ro': 0, 'add': 0};
}

export type ProfilesServerCapabilities = ProfilesServerRemoteCapabilities;

export type ProfilesClientRemoteCapabilities = Capabilities;

export class ProfilesClientLocalCapabilities {
  public static value: {'get_settings': 0, 'get_all': 0, 'get': 0, 'set_info': 2, 'set_enabled': 0, 'set_admin': 0, 'set_nucleus_ro': 0, 'add': 0};
}

export type ProfilesClientCapabilities = ProfilesClientLocalCapabilities;

export type ProfilesAddServerRemoteVersion = number;

export class ProfilesAddServerLocalVersion {
  public static value: 0;
}

export type ProfilesAddServerVersion = ProfilesAddServerRemoteVersion;

export type ProfilesAddClientRemoteVersion = number;

export class ProfilesAddClientLocalVersion {
  public static value: 0;
}

export type ProfilesSetNucleusRoServerRemoteVersion = number;

export class ProfilesSetNucleusRoServerLocalVersion {
  public static value: 0;
}

export type ProfilesSetNucleusRoServerVersion = ProfilesSetNucleusRoServerRemoteVersion;

export type ProfilesSetNucleusRoClientRemoteVersion = number;

export class ProfilesSetNucleusRoClientLocalVersion {
  public static value: 0;
}

export type ProfilesSetAdminServerRemoteVersion = number;

export class ProfilesSetAdminServerLocalVersion {
  public static value: 0;
}

export type ProfilesSetAdminServerVersion = ProfilesSetAdminServerRemoteVersion;

export type ProfilesSetAdminClientRemoteVersion = number;

export class ProfilesSetAdminClientLocalVersion {
  public static value: 0;
}

export type ProfilesSetEnabledServerRemoteVersion = number;

export class ProfilesSetEnabledServerLocalVersion {
  public static value: 0;
}

export type ProfilesSetEnabledServerVersion = ProfilesSetEnabledServerRemoteVersion;

export type ProfilesSetEnabledClientRemoteVersion = number;

export class ProfilesSetEnabledClientLocalVersion {
  public static value: 0;
}

export type ProfilesSetInfoServerRemoteVersion = number;

export class ProfilesSetInfoServerLocalVersion {
  public static value: 2;
}

export type ProfilesSetInfoServerVersion = ProfilesSetInfoServerRemoteVersion;

export type ProfilesSetInfoClientRemoteVersion = number;

export class ProfilesSetInfoClientLocalVersion {
  public static value: 2;
}

export type ProfilesGetServerRemoteVersion = number;

export class ProfilesGetServerLocalVersion {
  public static value: 0;
}

export type ProfilesGetServerVersion = ProfilesGetServerRemoteVersion;

export type ProfilesGetClientRemoteVersion = number;

export class ProfilesGetClientLocalVersion {
  public static value: 0;
}

export type ProfilesGetAllServerRemoteVersion = number;

export class ProfilesGetAllServerLocalVersion {
  public static value: 0;
}

export type ProfilesGetAllServerVersion = ProfilesGetAllServerRemoteVersion;

export type ProfilesGetAllClientRemoteVersion = number;

export class ProfilesGetAllClientLocalVersion {
  public static value: 0;
}

export type ProfilesGetSettingsServerRemoteVersion = number;

export class ProfilesGetSettingsServerLocalVersion {
  public static value: 0;
}

export type ProfilesGetSettingsClientRemoteVersion = number;

export class ProfilesGetSettingsClientLocalVersion {
  public static value: 0;
}

export type CredentialsServerRemoteCapabilities = Capabilities;

export class CredentialsServerLocalCapabilities {
  public static value: {'get_settings': 0, 'auth': 2, 'register': 3, 'reset': 2};
}

export type CredentialsServerCapabilities = CredentialsServerRemoteCapabilities;

export type CredentialsClientRemoteCapabilities = Capabilities;

export class CredentialsClientLocalCapabilities {
  public static value: {'get_settings': 0, 'auth': 2, 'register': 3, 'reset': 2};
}

export type CredentialsClientCapabilities = CredentialsClientLocalCapabilities;

export type CredentialsResetServerRemoteVersion = number;

export class CredentialsResetServerLocalVersion {
  public static value: 2;
}

export type CredentialsResetServerVersion = CredentialsResetServerRemoteVersion;

export type CredentialsResetClientRemoteVersion = number;

export class CredentialsResetClientLocalVersion {
  public static value: 2;
}

export type CredentialsRegisterServerRemoteVersion = number;

export class CredentialsRegisterServerLocalVersion {
  public static value: 3;
}

export type CredentialsRegisterServerVersion = CredentialsRegisterServerRemoteVersion;

export type CredentialsRegisterClientRemoteVersion = number;

export class CredentialsRegisterClientLocalVersion {
  public static value: 3;
}

export type CredentialsAuthServerRemoteVersion = number;

export class CredentialsAuthServerLocalVersion {
  public static value: 2;
}

export type CredentialsAuthServerVersion = CredentialsAuthServerRemoteVersion;

export type CredentialsAuthClientRemoteVersion = number;

export class CredentialsAuthClientLocalVersion {
  public static value: 2;
}

export type CredentialsGetSettingsServerRemoteVersion = number;

export class CredentialsGetSettingsServerLocalVersion {
  public static value: 0;
}

export type CredentialsGetSettingsClientRemoteVersion = number;

export class CredentialsGetSettingsClientLocalVersion {
  public static value: 0;
}

export enum AuthStatus {
  OK = "OK",
  NotFound = "NOT_FOUND",
  Exists = "EXISTS",
  Disabled = "DISABLED",
  Denied = "DENIED",
  Expired = "EXPIRED",
  ReadOnly = "READONLY",
  UsernameRequired = "USERNAME_REQUIRED",
  NotSupported = "NOT_SUPPORTED",
  ConnectionError = "CONNECTION_ERROR",
  InternalError = "INTERNAL_ERROR",
  InvalidUsername = "INVALID_USERNAME",
  UnknownError = "UNKNOWN_ERROR",
  InvalidToken = "INVALID_TOKEN",
  Subscribed = "SUBSCRIBED",
  InvalidRequest = "INVALID_REQUEST",
  Pending = "PENDING",
}

export type ApiToken = {
  name: string,
};

export enum AuthProvider {
  Internal = "Internal",
  NVIDIA = "NVIDIA",
  Starfleet = "Starfleet",
  GFN = "GFN",
  NGC = "NGC",
  System = "System",
  SAML = "SAML",
  OpenID = "OpenID",
}

export type SSOGetSettingsServerVersion = SSOGetSettingsServerRemoteVersion;

export type ProfilesGetSettingsServerVersion = ProfilesGetSettingsServerRemoteVersion;

export type Profile = {
  first_name?: string,
  last_name?: string,
  email?: string,
  admin?: boolean,
  provider?: string,
  readonly?: boolean,
  nucleus_ro?: boolean,
  enabled?: boolean,
  activated?: boolean,
};

export type CredentialsGetSettingsServerVersion = CredentialsGetSettingsServerRemoteVersion;

export type Auth = {
  status: AuthStatus,
  version: number,
  access_token?: string,
  refresh_token?: string,
  username?: string,
  profile?: Profile,
  nonce?: string,
};

export type DeviceFlowTokenClientVersion = DeviceFlowTokenClientLocalVersion;

export type DeviceSubmit = {
  version: number,
  status: AuthStatus,
};

export type DeviceFlowSubmitClientVersion = DeviceFlowSubmitClientLocalVersion;

export type DeviceAuthorize = {
  version: number,
  user_code: string,
  verification_uri: string,
  verification_uri_complete: string,
  prompt_url: string,
  device_code: string,
  interval: number,
  expires_in: number,
};

export type DeviceFlowAuthorizeClientVersion = DeviceFlowAuthorizeClientLocalVersion;

export type UserStoreResult = {
  status: AuthStatus,
  version: number,
  value?: string,
};

export type UserStoreRemoveClientVersion = UserStoreRemoveClientLocalVersion;

export type UserStoreSetClientVersion = UserStoreSetClientLocalVersion;

export type UserStoreGetClientVersion = UserStoreGetClientLocalVersion;

export type TokensAuthWithApiTokenClientVersion = TokensAuthWithApiTokenClientLocalVersion;

export type GetApiTokens = {
  status: AuthStatus,
  version: number,
  tokens?: ApiToken[],
};

export type TokensGetApiTokensClientVersion = TokensGetApiTokensClientLocalVersion;

export type DeleteApiToken = {
  status: AuthStatus,
  version: number,
};

export type TokensDeleteApiTokenClientVersion = TokensDeleteApiTokenClientLocalVersion;

export type CreateApiToken = {
  status: AuthStatus,
  version: number,
  token?: string,
};

export type TokensCreateApiTokenClientVersion = TokensCreateApiTokenClientLocalVersion;

export type TokensSubscribeClientVersion = TokensSubscribeClientLocalVersion;

export type TokensInvalidateClientVersion = TokensInvalidateClientLocalVersion;

export type TokensRefreshClientVersion = TokensRefreshClientLocalVersion;

export type TokensGenerateClientVersion = TokensGenerateClientLocalVersion;

export type SSORedirect = {
  status: AuthStatus,
  redirect: string,
};

export type SSORedirectClientVersion = SSORedirectClientLocalVersion;

export type SSOParams = {
  [key: string]: string,
};

export type SSOAuthClientVersion = SSOAuthClientLocalVersion;

export type SSOSettings = {
  public_name: string,
  type: string,
  redirect?: string,
  image: string,
  version: SSOGetSettingsServerVersion,
  interactive: boolean,
};

export type SSOGetSettingsClientVersion = SSOGetSettingsClientLocalVersion;

export type ProfileResponse = {
  status: AuthStatus,
  version: number,
  username?: string,
  profile?: Profile,
};

export type ProfilesAddClientVersion = ProfilesAddClientLocalVersion;

export type ProfilesSetNucleusRoClientVersion = ProfilesSetNucleusRoClientLocalVersion;

export type ProfilesSetAdminClientVersion = ProfilesSetAdminClientLocalVersion;

export type ProfilesSetEnabledClientVersion = ProfilesSetEnabledClientLocalVersion;

export type ProfilesSetInfoClientVersion = ProfilesSetInfoClientLocalVersion;

export type ProfilesGetClientVersion = ProfilesGetClientLocalVersion;

export type ProfilesGetAllClientVersion = ProfilesGetAllClientLocalVersion;

export type ProfileSettings = {
  can_manage: boolean,
  version: ProfilesGetSettingsServerVersion,
};

export type ProfilesGetSettingsClientVersion = ProfilesGetSettingsClientLocalVersion;

export type CredentialsResetClientVersion = CredentialsResetClientLocalVersion;

export type CredentialsRegisterClientVersion = CredentialsRegisterClientLocalVersion;

export type CredentialsAuthClientVersion = CredentialsAuthClientLocalVersion;

export type CredentialSettings = {
  login_url?: string,
  can_register?: boolean,
  is_ui_visible?: boolean,
  version?: CredentialsGetSettingsServerVersion,
};

export type CredentialsGetSettingsClientVersion = CredentialsGetSettingsClientLocalVersion;



export type DeviceFlowAuthorizeRequest = {
  client_id: string,
};

export type DeviceFlowSubmitRequest = {
  access_token: string,
  user_code: string,
};

export type DeviceFlowTokenRequest = {
  client_id: string,
  device_code: string,
};

export type UserStoreGetRequest = {
  key: string,
  token: string,
};

export type UserStoreSetRequest = {
  key: string,
  value: string,
  token: string,
};

export type UserStoreRemoveRequest = {
  key: string,
  token: string,
};

export type TokensGenerateRequest = {
  username: string,
  admin_token: string,
  client_id?: string,
};

export type TokensRefreshRequest = {
  refresh_token: string,
  client_id?: string,
};

export type TokensInvalidateRequest = {
  username: string,
  admin_token: string,
  refresh_token?: string,
};

export type TokensSubscribeRequest = {
};

export type TokensCreateApiTokenRequest = {
  access_token: string,
  name: string,
  expire_at?: string,
  client_id?: string,
};

export type TokensDeleteApiTokenRequest = {
  access_token: string,
  name: string,
};

export type TokensGetApiTokensRequest = {
  access_token: string,
};

export type TokensAuthWithApiTokenRequest = {
  api_token: string,
  client_id?: string,
};

export type SSOGetSettingsRequest = {
};

export type SSOAuthRequest = {
  type: string,
  params: SSOParams,
  nonce?: string,
  client_id?: string,
};

export type SSORedirectRequest = {
  type: string,
  state?: string,
  nonce?: string,
};

export type ProfilesGetSettingsRequest = {
};

export type ProfilesGetAllRequest = {
  token: string,
};

export type ProfilesGetRequest = {
  username: string,
};

export type ProfilesSetInfoRequest = {
  username: string,
  token: string,
  first_name?: string,
  last_name?: string,
  email?: string,
  new_username?: string,
};

export type ProfilesSetEnabledRequest = {
  username: string,
  token: string,
  enabled: boolean,
};

export type ProfilesSetAdminRequest = {
  username: string,
  token: string,
  admin: boolean,
};

export type ProfilesSetNucleusRoRequest = {
  username: string,
  token: string,
  nucleus_ro: boolean,
};

export type ProfilesAddRequest = {
  username: string,
  token: string,
  first_name?: string,
  last_name?: string,
  email?: string,
};

export type CredentialsGetSettingsRequest = {
};

export type CredentialsAuthRequest = {
  username: string,
  password: string,
  nonce?: string,
  client_id?: string,
};

export type CredentialsRegisterRequest = {
  username: string,
  password: string,
  profile: Profile,
  nonce?: string,
  client_id?: string,
};

export type CredentialsResetRequest = {
  username: string,
  new_password: string,
  token: string,
  client_id?: string,
};
