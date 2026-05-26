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

import Schema from "@omniverse/idl/schema";


export const Capabilities = Schema.Map(Schema.Number);

export const DeviceFlowServerRemoteCapabilities = Capabilities;

export const DeviceFlowServerLocalCapabilities = Schema.Literal({'authorize': 0, 'submit': 0, 'token': 0});

export const DeviceFlowServerCapabilities = DeviceFlowServerRemoteCapabilities;

export const DeviceFlowClientRemoteCapabilities = Capabilities;

export const DeviceFlowClientLocalCapabilities = Schema.Literal({'authorize': 0, 'submit': 0, 'token': 0});

export const DeviceFlowClientCapabilities = DeviceFlowClientLocalCapabilities;

export const DeviceFlowTokenServerRemoteVersion = Schema.Number;

export const DeviceFlowTokenServerLocalVersion = Schema.Literal(0);

export const DeviceFlowTokenServerVersion = DeviceFlowTokenServerRemoteVersion;

export const DeviceFlowTokenClientRemoteVersion = Schema.Number;

export const DeviceFlowTokenClientLocalVersion = Schema.Literal(0);

export const DeviceFlowSubmitServerRemoteVersion = Schema.Number;

export const DeviceFlowSubmitServerLocalVersion = Schema.Literal(0);

export const DeviceFlowSubmitServerVersion = DeviceFlowSubmitServerRemoteVersion;

export const DeviceFlowSubmitClientRemoteVersion = Schema.Number;

export const DeviceFlowSubmitClientLocalVersion = Schema.Literal(0);

export const DeviceFlowAuthorizeServerRemoteVersion = Schema.Number;

export const DeviceFlowAuthorizeServerLocalVersion = Schema.Literal(0);

export const DeviceFlowAuthorizeServerVersion = DeviceFlowAuthorizeServerRemoteVersion;

export const DeviceFlowAuthorizeClientRemoteVersion = Schema.Number;

export const DeviceFlowAuthorizeClientLocalVersion = Schema.Literal(0);

export const UserStoreServerRemoteCapabilities = Capabilities;

export const UserStoreServerLocalCapabilities = Schema.Literal({'get': 0, 'set': 0, 'remove': 0});

export const UserStoreServerCapabilities = UserStoreServerRemoteCapabilities;

export const UserStoreClientRemoteCapabilities = Capabilities;

export const UserStoreClientLocalCapabilities = Schema.Literal({'get': 0, 'set': 0, 'remove': 0});

export const UserStoreClientCapabilities = UserStoreClientLocalCapabilities;

export const UserStoreRemoveServerRemoteVersion = Schema.Number;

export const UserStoreRemoveServerLocalVersion = Schema.Literal(0);

export const UserStoreRemoveServerVersion = UserStoreRemoveServerRemoteVersion;

export const UserStoreRemoveClientRemoteVersion = Schema.Number;

export const UserStoreRemoveClientLocalVersion = Schema.Literal(0);

export const UserStoreSetServerRemoteVersion = Schema.Number;

export const UserStoreSetServerLocalVersion = Schema.Literal(0);

export const UserStoreSetServerVersion = UserStoreSetServerRemoteVersion;

export const UserStoreSetClientRemoteVersion = Schema.Number;

export const UserStoreSetClientLocalVersion = Schema.Literal(0);

export const UserStoreGetServerRemoteVersion = Schema.Number;

export const UserStoreGetServerLocalVersion = Schema.Literal(0);

export const UserStoreGetServerVersion = UserStoreGetServerRemoteVersion;

export const UserStoreGetClientRemoteVersion = Schema.Number;

export const UserStoreGetClientLocalVersion = Schema.Literal(0);

export const TokensServerRemoteCapabilities = Capabilities;

export const TokensServerLocalCapabilities = Schema.Literal({'generate': 2, 'refresh': 1, 'invalidate': 0, 'subscribe': 0, 'create_api_token': 2, 'delete_api_token': 0, 'get_api_tokens': 0, 'auth_with_api_token': 1});

export const TokensServerCapabilities = TokensServerRemoteCapabilities;

export const TokensClientRemoteCapabilities = Capabilities;

export const TokensClientLocalCapabilities = Schema.Literal({'generate': 2, 'refresh': 1, 'invalidate': 0, 'subscribe': 0, 'create_api_token': 2, 'delete_api_token': 0, 'get_api_tokens': 0, 'auth_with_api_token': 1});

export const TokensClientCapabilities = TokensClientLocalCapabilities;

export const TokensAuthWithApiTokenServerRemoteVersion = Schema.Number;

export const TokensAuthWithApiTokenServerLocalVersion = Schema.Literal(1);

export const TokensAuthWithApiTokenServerVersion = TokensAuthWithApiTokenServerRemoteVersion;

export const TokensAuthWithApiTokenClientRemoteVersion = Schema.Number;

export const TokensAuthWithApiTokenClientLocalVersion = Schema.Literal(1);

export const TokensGetApiTokensServerRemoteVersion = Schema.Number;

export const TokensGetApiTokensServerLocalVersion = Schema.Literal(0);

export const TokensGetApiTokensServerVersion = TokensGetApiTokensServerRemoteVersion;

export const TokensGetApiTokensClientRemoteVersion = Schema.Number;

export const TokensGetApiTokensClientLocalVersion = Schema.Literal(0);

export const TokensDeleteApiTokenServerRemoteVersion = Schema.Number;

export const TokensDeleteApiTokenServerLocalVersion = Schema.Literal(0);

export const TokensDeleteApiTokenServerVersion = TokensDeleteApiTokenServerRemoteVersion;

export const TokensDeleteApiTokenClientRemoteVersion = Schema.Number;

export const TokensDeleteApiTokenClientLocalVersion = Schema.Literal(0);

export const TokensCreateApiTokenServerRemoteVersion = Schema.Number;

export const TokensCreateApiTokenServerLocalVersion = Schema.Literal(2);

export const TokensCreateApiTokenServerVersion = TokensCreateApiTokenServerRemoteVersion;

export const TokensCreateApiTokenClientRemoteVersion = Schema.Number;

export const TokensCreateApiTokenClientLocalVersion = Schema.Literal(2);

export const TokensSubscribeServerRemoteVersion = Schema.Number;

export const TokensSubscribeServerLocalVersion = Schema.Literal(0);

export const TokensSubscribeServerVersion = TokensSubscribeServerRemoteVersion;

export const TokensSubscribeClientRemoteVersion = Schema.Number;

export const TokensSubscribeClientLocalVersion = Schema.Literal(0);

export const TokensInvalidateServerRemoteVersion = Schema.Number;

export const TokensInvalidateServerLocalVersion = Schema.Literal(0);

export const TokensInvalidateServerVersion = TokensInvalidateServerRemoteVersion;

export const TokensInvalidateClientRemoteVersion = Schema.Number;

export const TokensInvalidateClientLocalVersion = Schema.Literal(0);

export const TokensRefreshServerRemoteVersion = Schema.Number;

export const TokensRefreshServerLocalVersion = Schema.Literal(1);

export const TokensRefreshServerVersion = TokensRefreshServerRemoteVersion;

export const TokensRefreshClientRemoteVersion = Schema.Number;

export const TokensRefreshClientLocalVersion = Schema.Literal(1);

export const TokensGenerateServerRemoteVersion = Schema.Number;

export const TokensGenerateServerLocalVersion = Schema.Literal(2);

export const TokensGenerateServerVersion = TokensGenerateServerRemoteVersion;

export const TokensGenerateClientRemoteVersion = Schema.Number;

export const TokensGenerateClientLocalVersion = Schema.Literal(2);

export const SSOServerRemoteCapabilities = Capabilities;

export const SSOServerLocalCapabilities = Schema.Literal({'get_settings': 0, 'auth': 2, 'redirect': 1});

export const SSOServerCapabilities = SSOServerRemoteCapabilities;

export const SSOClientRemoteCapabilities = Capabilities;

export const SSOClientLocalCapabilities = Schema.Literal({'get_settings': 0, 'auth': 2, 'redirect': 1});

export const SSOClientCapabilities = SSOClientLocalCapabilities;

export const SSORedirectServerRemoteVersion = Schema.Number;

export const SSORedirectServerLocalVersion = Schema.Literal(1);

export const SSORedirectServerVersion = SSORedirectServerRemoteVersion;

export const SSORedirectClientRemoteVersion = Schema.Number;

export const SSORedirectClientLocalVersion = Schema.Literal(1);

export const SSOAuthServerRemoteVersion = Schema.Number;

export const SSOAuthServerLocalVersion = Schema.Literal(2);

export const SSOAuthServerVersion = SSOAuthServerRemoteVersion;

export const SSOAuthClientRemoteVersion = Schema.Number;

export const SSOAuthClientLocalVersion = Schema.Literal(2);

export const SSOGetSettingsServerRemoteVersion = Schema.Number;

export const SSOGetSettingsServerLocalVersion = Schema.Literal(0);

export const SSOGetSettingsClientRemoteVersion = Schema.Number;

export const SSOGetSettingsClientLocalVersion = Schema.Literal(0);

export const ProfilesServerRemoteCapabilities = Capabilities;

export const ProfilesServerLocalCapabilities = Schema.Literal({'get_settings': 0, 'get_all': 0, 'get': 0, 'set_info': 2, 'set_enabled': 0, 'set_admin': 0, 'set_nucleus_ro': 0, 'add': 0});

export const ProfilesServerCapabilities = ProfilesServerRemoteCapabilities;

export const ProfilesClientRemoteCapabilities = Capabilities;

export const ProfilesClientLocalCapabilities = Schema.Literal({'get_settings': 0, 'get_all': 0, 'get': 0, 'set_info': 2, 'set_enabled': 0, 'set_admin': 0, 'set_nucleus_ro': 0, 'add': 0});

export const ProfilesClientCapabilities = ProfilesClientLocalCapabilities;

export const ProfilesAddServerRemoteVersion = Schema.Number;

export const ProfilesAddServerLocalVersion = Schema.Literal(0);

export const ProfilesAddServerVersion = ProfilesAddServerRemoteVersion;

export const ProfilesAddClientRemoteVersion = Schema.Number;

export const ProfilesAddClientLocalVersion = Schema.Literal(0);

export const ProfilesSetNucleusRoServerRemoteVersion = Schema.Number;

export const ProfilesSetNucleusRoServerLocalVersion = Schema.Literal(0);

export const ProfilesSetNucleusRoServerVersion = ProfilesSetNucleusRoServerRemoteVersion;

export const ProfilesSetNucleusRoClientRemoteVersion = Schema.Number;

export const ProfilesSetNucleusRoClientLocalVersion = Schema.Literal(0);

export const ProfilesSetAdminServerRemoteVersion = Schema.Number;

export const ProfilesSetAdminServerLocalVersion = Schema.Literal(0);

export const ProfilesSetAdminServerVersion = ProfilesSetAdminServerRemoteVersion;

export const ProfilesSetAdminClientRemoteVersion = Schema.Number;

export const ProfilesSetAdminClientLocalVersion = Schema.Literal(0);

export const ProfilesSetEnabledServerRemoteVersion = Schema.Number;

export const ProfilesSetEnabledServerLocalVersion = Schema.Literal(0);

export const ProfilesSetEnabledServerVersion = ProfilesSetEnabledServerRemoteVersion;

export const ProfilesSetEnabledClientRemoteVersion = Schema.Number;

export const ProfilesSetEnabledClientLocalVersion = Schema.Literal(0);

export const ProfilesSetInfoServerRemoteVersion = Schema.Number;

export const ProfilesSetInfoServerLocalVersion = Schema.Literal(2);

export const ProfilesSetInfoServerVersion = ProfilesSetInfoServerRemoteVersion;

export const ProfilesSetInfoClientRemoteVersion = Schema.Number;

export const ProfilesSetInfoClientLocalVersion = Schema.Literal(2);

export const ProfilesGetServerRemoteVersion = Schema.Number;

export const ProfilesGetServerLocalVersion = Schema.Literal(0);

export const ProfilesGetServerVersion = ProfilesGetServerRemoteVersion;

export const ProfilesGetClientRemoteVersion = Schema.Number;

export const ProfilesGetClientLocalVersion = Schema.Literal(0);

export const ProfilesGetAllServerRemoteVersion = Schema.Number;

export const ProfilesGetAllServerLocalVersion = Schema.Literal(0);

export const ProfilesGetAllServerVersion = ProfilesGetAllServerRemoteVersion;

export const ProfilesGetAllClientRemoteVersion = Schema.Number;

export const ProfilesGetAllClientLocalVersion = Schema.Literal(0);

export const ProfilesGetSettingsServerRemoteVersion = Schema.Number;

export const ProfilesGetSettingsServerLocalVersion = Schema.Literal(0);

export const ProfilesGetSettingsClientRemoteVersion = Schema.Number;

export const ProfilesGetSettingsClientLocalVersion = Schema.Literal(0);

export const CredentialsServerRemoteCapabilities = Capabilities;

export const CredentialsServerLocalCapabilities = Schema.Literal({'get_settings': 0, 'auth': 2, 'register': 3, 'reset': 2});

export const CredentialsServerCapabilities = CredentialsServerRemoteCapabilities;

export const CredentialsClientRemoteCapabilities = Capabilities;

export const CredentialsClientLocalCapabilities = Schema.Literal({'get_settings': 0, 'auth': 2, 'register': 3, 'reset': 2});

export const CredentialsClientCapabilities = CredentialsClientLocalCapabilities;

export const CredentialsResetServerRemoteVersion = Schema.Number;

export const CredentialsResetServerLocalVersion = Schema.Literal(2);

export const CredentialsResetServerVersion = CredentialsResetServerRemoteVersion;

export const CredentialsResetClientRemoteVersion = Schema.Number;

export const CredentialsResetClientLocalVersion = Schema.Literal(2);

export const CredentialsRegisterServerRemoteVersion = Schema.Number;

export const CredentialsRegisterServerLocalVersion = Schema.Literal(3);

export const CredentialsRegisterServerVersion = CredentialsRegisterServerRemoteVersion;

export const CredentialsRegisterClientRemoteVersion = Schema.Number;

export const CredentialsRegisterClientLocalVersion = Schema.Literal(3);

export const CredentialsAuthServerRemoteVersion = Schema.Number;

export const CredentialsAuthServerLocalVersion = Schema.Literal(2);

export const CredentialsAuthServerVersion = CredentialsAuthServerRemoteVersion;

export const CredentialsAuthClientRemoteVersion = Schema.Number;

export const CredentialsAuthClientLocalVersion = Schema.Literal(2);

export const CredentialsGetSettingsServerRemoteVersion = Schema.Number;

export const CredentialsGetSettingsServerLocalVersion = Schema.Literal(0);

export const CredentialsGetSettingsClientRemoteVersion = Schema.Number;

export const CredentialsGetSettingsClientLocalVersion = Schema.Literal(0);

export const AuthStatus = Schema.Enum({
  OK: "OK",
  NotFound: "NOT_FOUND",
  Exists: "EXISTS",
  Disabled: "DISABLED",
  Denied: "DENIED",
  Expired: "EXPIRED",
  ReadOnly: "READONLY",
  UsernameRequired: "USERNAME_REQUIRED",
  NotSupported: "NOT_SUPPORTED",
  ConnectionError: "CONNECTION_ERROR",
  InternalError: "INTERNAL_ERROR",
  InvalidUsername: "INVALID_USERNAME",
  UnknownError: "UNKNOWN_ERROR",
  InvalidToken: "INVALID_TOKEN",
  Subscribed: "SUBSCRIBED",
  InvalidRequest: "INVALID_REQUEST",
  Pending: "PENDING",
});

export const ApiToken = Schema.Object({
  name: Schema.String,
});

export const AuthProvider = Schema.Enum({
  Internal: "Internal",
  NVIDIA: "NVIDIA",
  Starfleet: "Starfleet",
  GFN: "GFN",
  NGC: "NGC",
  System: "System",
  SAML: "SAML",
  OpenID: "OpenID",
});

export const SSOGetSettingsServerVersion = SSOGetSettingsServerRemoteVersion;

export const ProfilesGetSettingsServerVersion = ProfilesGetSettingsServerRemoteVersion;

export const Profile = Schema.Object({
  first_name: Schema.Optional(Schema.String),
  last_name: Schema.Optional(Schema.String),
  email: Schema.Optional(Schema.String),
  admin: Schema.Optional(Schema.Boolean),
  provider: Schema.Optional(Schema.String),
  readonly: Schema.Optional(Schema.Boolean),
  nucleus_ro: Schema.Optional(Schema.Boolean),
  enabled: Schema.Optional(Schema.Boolean),
  activated: Schema.Optional(Schema.Boolean),
});

export const CredentialsGetSettingsServerVersion = CredentialsGetSettingsServerRemoteVersion;

export const Auth = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
  access_token: Schema.Optional(Schema.String),
  refresh_token: Schema.Optional(Schema.String),
  username: Schema.Optional(Schema.String),
  profile: Schema.Optional(Profile),
  nonce: Schema.Optional(Schema.String),
});

export const DeviceFlowTokenClientVersion = DeviceFlowTokenClientLocalVersion;

export const DeviceSubmit = Schema.Object({
  version: Schema.Number,
  status: AuthStatus,
});

export const DeviceFlowSubmitClientVersion = DeviceFlowSubmitClientLocalVersion;

export const DeviceAuthorize = Schema.Object({
  version: Schema.Number,
  user_code: Schema.String,
  verification_uri: Schema.String,
  verification_uri_complete: Schema.String,
  prompt_url: Schema.String,
  device_code: Schema.String,
  interval: Schema.Number,
  expires_in: Schema.Number,
});

export const DeviceFlowAuthorizeClientVersion = DeviceFlowAuthorizeClientLocalVersion;

export const UserStoreResult = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
  value: Schema.Optional(Schema.String),
});

export const UserStoreRemoveClientVersion = UserStoreRemoveClientLocalVersion;

export const UserStoreSetClientVersion = UserStoreSetClientLocalVersion;

export const UserStoreGetClientVersion = UserStoreGetClientLocalVersion;

export const TokensAuthWithApiTokenClientVersion = TokensAuthWithApiTokenClientLocalVersion;

export const GetApiTokens = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
  tokens: Schema.Optional(Schema.Array(ApiToken)),
});

export const TokensGetApiTokensClientVersion = TokensGetApiTokensClientLocalVersion;

export const DeleteApiToken = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
});

export const TokensDeleteApiTokenClientVersion = TokensDeleteApiTokenClientLocalVersion;

export const CreateApiToken = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
  token: Schema.Optional(Schema.String),
});

export const TokensCreateApiTokenClientVersion = TokensCreateApiTokenClientLocalVersion;

export const TokensSubscribeClientVersion = TokensSubscribeClientLocalVersion;

export const TokensInvalidateClientVersion = TokensInvalidateClientLocalVersion;

export const TokensRefreshClientVersion = TokensRefreshClientLocalVersion;

export const TokensGenerateClientVersion = TokensGenerateClientLocalVersion;

export const SSORedirect = Schema.Object({
  status: AuthStatus,
  redirect: Schema.String,
});

export const SSORedirectClientVersion = SSORedirectClientLocalVersion;

export const SSOParams = Schema.Map(Schema.String);

export const SSOAuthClientVersion = SSOAuthClientLocalVersion;

export const SSOSettings = Schema.Object({
  public_name: Schema.String,
  type: Schema.String,
  redirect: Schema.Optional(Schema.String),
  image: Schema.String,
  version: SSOGetSettingsServerVersion,
  interactive: Schema.Boolean,
});

export const SSOGetSettingsClientVersion = SSOGetSettingsClientLocalVersion;

export const ProfileResponse = Schema.Object({
  status: AuthStatus,
  version: Schema.Number,
  username: Schema.Optional(Schema.String),
  profile: Schema.Optional(Profile),
});

export const ProfilesAddClientVersion = ProfilesAddClientLocalVersion;

export const ProfilesSetNucleusRoClientVersion = ProfilesSetNucleusRoClientLocalVersion;

export const ProfilesSetAdminClientVersion = ProfilesSetAdminClientLocalVersion;

export const ProfilesSetEnabledClientVersion = ProfilesSetEnabledClientLocalVersion;

export const ProfilesSetInfoClientVersion = ProfilesSetInfoClientLocalVersion;

export const ProfilesGetClientVersion = ProfilesGetClientLocalVersion;

export const ProfilesGetAllClientVersion = ProfilesGetAllClientLocalVersion;

export const ProfileSettings = Schema.Object({
  can_manage: Schema.Boolean,
  version: ProfilesGetSettingsServerVersion,
});

export const ProfilesGetSettingsClientVersion = ProfilesGetSettingsClientLocalVersion;

export const CredentialsResetClientVersion = CredentialsResetClientLocalVersion;

export const CredentialsRegisterClientVersion = CredentialsRegisterClientLocalVersion;

export const CredentialsAuthClientVersion = CredentialsAuthClientLocalVersion;

export const CredentialSettings = Schema.Object({
  login_url: Schema.Optional(Schema.String),
  can_register: Schema.Optional(Schema.Boolean),
  is_ui_visible: Schema.Optional(Schema.Boolean),
  version: Schema.Optional(CredentialsGetSettingsServerVersion),
});

export const CredentialsGetSettingsClientVersion = CredentialsGetSettingsClientLocalVersion;



export const DeviceFlowAuthorizeRequest = Schema.Object({
  version: DeviceFlowAuthorizeClientVersion,
  client_id: Schema.String,
});

export const DeviceFlowSubmitRequest = Schema.Object({
  version: DeviceFlowSubmitClientVersion,
  access_token: Schema.String,
  user_code: Schema.String,
});

export const DeviceFlowTokenRequest = Schema.Object({
  version: DeviceFlowTokenClientVersion,
  client_id: Schema.String,
  device_code: Schema.String,
});

export const UserStoreGetRequest = Schema.Object({
  version: UserStoreGetClientVersion,
  key: Schema.String,
  token: Schema.String,
});

export const UserStoreSetRequest = Schema.Object({
  version: UserStoreSetClientVersion,
  key: Schema.String,
  value: Schema.String,
  token: Schema.String,
});

export const UserStoreRemoveRequest = Schema.Object({
  version: UserStoreRemoveClientVersion,
  key: Schema.String,
  token: Schema.String,
});

export const TokensGenerateRequest = Schema.Object({
  version: TokensGenerateClientVersion,
  username: Schema.String,
  admin_token: Schema.String,
  client_id: Schema.Optional(Schema.String),
});

export const TokensRefreshRequest = Schema.Object({
  version: TokensRefreshClientVersion,
  refresh_token: Schema.String,
  client_id: Schema.Optional(Schema.String),
});

export const TokensInvalidateRequest = Schema.Object({
  version: TokensInvalidateClientVersion,
  username: Schema.String,
  admin_token: Schema.String,
  refresh_token: Schema.Optional(Schema.String),
});

export const TokensSubscribeRequest = Schema.Object({
  version: TokensSubscribeClientVersion,
});

export const TokensCreateApiTokenRequest = Schema.Object({
  version: TokensCreateApiTokenClientVersion,
  access_token: Schema.String,
  name: Schema.String,
  expire_at: Schema.Optional(Schema.String),
  client_id: Schema.Optional(Schema.String),
});

export const TokensDeleteApiTokenRequest = Schema.Object({
  version: TokensDeleteApiTokenClientVersion,
  access_token: Schema.String,
  name: Schema.String,
});

export const TokensGetApiTokensRequest = Schema.Object({
  version: TokensGetApiTokensClientVersion,
  access_token: Schema.String,
});

export const TokensAuthWithApiTokenRequest = Schema.Object({
  version: TokensAuthWithApiTokenClientVersion,
  api_token: Schema.String,
  client_id: Schema.Optional(Schema.String),
});

export const SSOGetSettingsRequest = Schema.Object({
  version: SSOGetSettingsClientVersion,
});

export const SSOAuthRequest = Schema.Object({
  version: SSOAuthClientVersion,
  type: Schema.String,
  params: SSOParams,
  nonce: Schema.Optional(Schema.String),
  client_id: Schema.Optional(Schema.String),
});

export const SSORedirectRequest = Schema.Object({
  version: SSORedirectClientVersion,
  type: Schema.String,
  state: Schema.Optional(Schema.String),
  nonce: Schema.Optional(Schema.String),
});

export const ProfilesGetSettingsRequest = Schema.Object({
  version: ProfilesGetSettingsClientVersion,
});

export const ProfilesGetAllRequest = Schema.Object({
  version: ProfilesGetAllClientVersion,
  token: Schema.String,
});

export const ProfilesGetRequest = Schema.Object({
  version: ProfilesGetClientVersion,
  username: Schema.String,
});

export const ProfilesSetInfoRequest = Schema.Object({
  version: ProfilesSetInfoClientVersion,
  username: Schema.String,
  token: Schema.String,
  first_name: Schema.Optional(Schema.String),
  last_name: Schema.Optional(Schema.String),
  email: Schema.Optional(Schema.String),
  new_username: Schema.Optional(Schema.String),
});

export const ProfilesSetEnabledRequest = Schema.Object({
  version: ProfilesSetEnabledClientVersion,
  username: Schema.String,
  token: Schema.String,
  enabled: Schema.Boolean,
});

export const ProfilesSetAdminRequest = Schema.Object({
  version: ProfilesSetAdminClientVersion,
  username: Schema.String,
  token: Schema.String,
  admin: Schema.Boolean,
});

export const ProfilesSetNucleusRoRequest = Schema.Object({
  version: ProfilesSetNucleusRoClientVersion,
  username: Schema.String,
  token: Schema.String,
  nucleus_ro: Schema.Boolean,
});

export const ProfilesAddRequest = Schema.Object({
  version: ProfilesAddClientVersion,
  username: Schema.String,
  token: Schema.String,
  first_name: Schema.Optional(Schema.String),
  last_name: Schema.Optional(Schema.String),
  email: Schema.Optional(Schema.String),
});

export const CredentialsGetSettingsRequest = Schema.Object({
  version: CredentialsGetSettingsClientVersion,
});

export const CredentialsAuthRequest = Schema.Object({
  version: CredentialsAuthClientVersion,
  username: Schema.String,
  password: Schema.String,
  nonce: Schema.Optional(Schema.String),
  client_id: Schema.Optional(Schema.String),
});

export const CredentialsRegisterRequest = Schema.Object({
  version: CredentialsRegisterClientVersion,
  username: Schema.String,
  password: Schema.String,
  profile: Profile,
  nonce: Schema.Optional(Schema.String),
  client_id: Schema.Optional(Schema.String),
});

export const CredentialsResetRequest = Schema.Object({
  version: CredentialsResetClientVersion,
  username: Schema.String,
  new_password: Schema.String,
  token: Schema.String,
  client_id: Schema.Optional(Schema.String),
});
