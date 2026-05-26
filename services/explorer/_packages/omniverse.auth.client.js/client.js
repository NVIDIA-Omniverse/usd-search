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
import * as _data from "./data";

export class DeviceFlow {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    Starts the device flow authentication.
    @param version
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async authorize({client_id, }) {
    const _request = {version: _data.DeviceFlowAuthorizeClientVersion.value, client_id, };
    if (!_data.DeviceFlowAuthorizeRequest.validate(_request)) {
      throw new Error("Invalid DeviceFlowAuthorizeRequest.");
    }
    return await this.transport.call({ interfaceName: "DeviceFlow", methodName: "authorize", request: _request, schemas: { request: _data.DeviceFlowAuthorizeRequest, response: _data.DeviceAuthorize }});
  }
  
  /*
    Sends a signal that the user has entered the specified `user_code`.
    - AuthStatus.Expired, if `access_token` has expired.
    - AuthStatus.InvalidToken, if `access_token` is invalid.
    - AuthStatus.NotFound, if user code is used or expired.
    - AuthStatus.Disabled, if `access_token` is disabled.
    - AuthStatus.OK, if results are submitted successfully.
    @param version
    @param access_token The access token identifying the user.
    @param user_code The user code entered in the form.
   */
  async submit({access_token, user_code, }) {
    const _request = {version: _data.DeviceFlowSubmitClientVersion.value, access_token, user_code, };
    if (!_data.DeviceFlowSubmitRequest.validate(_request)) {
      throw new Error("Invalid DeviceFlowSubmitRequest.");
    }
    return await this.transport.call({ interfaceName: "DeviceFlow", methodName: "submit", request: _request, schemas: { request: _data.DeviceFlowSubmitRequest, response: _data.DeviceSubmit }});
  }
  
  /*
    Returns the authentication for the specified `client_id` and `device_code`.
    - AuthStatus.NotFound, if the service cannot find the pair of `client_id`
    and `device_code`.
    - AuthStatus.Pending, if the client should wand and try again after
    `interval` returned from `Device.authorize`.
    - AuthStatus.Expired, if `device_code` has expired.
    - AuthStatus.OK, if result is ready. Includes `access_token`,
    `refresh_token` and `profile` in this case.
    @param version
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
    @param device_code The code returned from `Device.authorize` method.
   */
  async token({client_id, device_code, }) {
    const _request = {version: _data.DeviceFlowTokenClientVersion.value, client_id, device_code, };
    if (!_data.DeviceFlowTokenRequest.validate(_request)) {
      throw new Error("Invalid DeviceFlowTokenRequest.");
    }
    return await this.transport.call({ interfaceName: "DeviceFlow", methodName: "token", request: _request, schemas: { request: _data.DeviceFlowTokenRequest, response: _data.Auth }});
  }
  
}
DeviceFlow[Schema.InterfaceName] = "DeviceFlow";
DeviceFlow[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
DeviceFlow[Schema.InterfaceCapabilities] = _data.DeviceFlowClientLocalCapabilities.value;

export class UserStore {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    Returns value in the user's store by the specified key.
    If the key does not exist, returns AuthStatus.NotFound.
   */
  async get({key, token, }) {
    const _request = {version: _data.UserStoreGetClientVersion.value, key, token, };
    if (!_data.UserStoreGetRequest.validate(_request)) {
      throw new Error("Invalid UserStoreGetRequest.");
    }
    return await this.transport.call({ interfaceName: "UserStore", methodName: "get", request: _request, schemas: { request: _data.UserStoreGetRequest, response: _data.UserStoreResult }});
  }
  
  /*
    
   */
  async set({key, value, token, }) {
    const _request = {version: _data.UserStoreSetClientVersion.value, key, value, token, };
    if (!_data.UserStoreSetRequest.validate(_request)) {
      throw new Error("Invalid UserStoreSetRequest.");
    }
    return await this.transport.call({ interfaceName: "UserStore", methodName: "set", request: _request, schemas: { request: _data.UserStoreSetRequest, response: _data.UserStoreResult }});
  }
  
  /*
    Removes value from the user's store by the specified key.
    If the key does not exist, returns AuthStatus.NotFound.
   */
  async remove({key, token, }) {
    const _request = {version: _data.UserStoreRemoveClientVersion.value, key, token, };
    if (!_data.UserStoreRemoveRequest.validate(_request)) {
      throw new Error("Invalid UserStoreRemoveRequest.");
    }
    return await this.transport.call({ interfaceName: "UserStore", methodName: "remove", request: _request, schemas: { request: _data.UserStoreRemoveRequest, response: _data.UserStoreResult }});
  }
  
}
UserStore[Schema.InterfaceName] = "UserStore";
UserStore[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
UserStore[Schema.InterfaceCapabilities] = _data.UserStoreClientLocalCapabilities.value;

export class Tokens {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    Allows administrator to generate tokens for users.
    Can let the user to work in a system for a limited period of time and reset
    his password.
    Returns a one-time API token as an access_token value.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async generate({username, admin_token, client_id, }) {
    const _request = {version: _data.TokensGenerateClientVersion.value, username, admin_token, client_id, };
    if (!_data.TokensGenerateRequest.validate(_request)) {
      throw new Error("Invalid TokensGenerateRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "generate", request: _request, schemas: { request: _data.TokensGenerateRequest, response: _data.Auth }});
  }
  
  /*
    Refreshes the authentication using a refresh token.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async refresh({refresh_token, client_id, }) {
    const _request = {version: _data.TokensRefreshClientVersion.value, refresh_token, client_id, };
    if (!_data.TokensRefreshRequest.validate(_request)) {
      throw new Error("Invalid TokensRefreshRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "refresh", request: _request, schemas: { request: _data.TokensRefreshRequest, response: _data.Auth }});
  }
  
  /*
    Invalidates refresh tokens for the specified user.
    This method is only available for administrators.
    Optionally accepts a refresh token that needs to be invalidated.
   */
  async invalidate({username, admin_token, refresh_token, }) {
    const _request = {version: _data.TokensInvalidateClientVersion.value, username, admin_token, refresh_token, };
    if (!_data.TokensInvalidateRequest.validate(_request)) {
      throw new Error("Invalid TokensInvalidateRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "invalidate", request: _request, schemas: { request: _data.TokensInvalidateRequest, response: _data.Auth }});
  }
  
  /*
    Returns `nonce` with a random string and subscribes to its authentication
    results.
    Clients can use the login form with the `nonce` query argument.
    In this case, the login form will pass this `nonce` string back to the
    service to make it
    publish authentication tokens to this subscription.

    The first response returns an object with `status` equal to
    `AuthStatus.Subscribed` and `nonce`
    that should be sent to the login form.
    The following response returns the authentication result from the login
    form.
   */
  async subscribe() {
    const _request = {version: _data.TokensSubscribeClientVersion.value, };
    if (!_data.TokensSubscribeRequest.validate(_request)) {
      throw new Error("Invalid TokensSubscribeRequest.");
    }
    return await this.transport.callMany({ interfaceName: "Tokens", methodName: "subscribe", request: _request, schemas: { request: _data.TokensSubscribeRequest, response: _data.Auth }});
  }
  
  /*
    Create a new API token.
    `expire_at` is an ISO-8601 date describing when this token must be revoked.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async createApiToken({access_token, name, expire_at, client_id, }) {
    const _request = {version: _data.TokensCreateApiTokenClientVersion.value, access_token, name, expire_at, client_id, };
    if (!_data.TokensCreateApiTokenRequest.validate(_request)) {
      throw new Error("Invalid TokensCreateApiTokenRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "create_api_token", request: _request, schemas: { request: _data.TokensCreateApiTokenRequest, response: _data.CreateApiToken }});
  }
  
  /*
    Delete API token
   */
  async deleteApiToken({access_token, name, }) {
    const _request = {version: _data.TokensDeleteApiTokenClientVersion.value, access_token, name, };
    if (!_data.TokensDeleteApiTokenRequest.validate(_request)) {
      throw new Error("Invalid TokensDeleteApiTokenRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "delete_api_token", request: _request, schemas: { request: _data.TokensDeleteApiTokenRequest, response: _data.DeleteApiToken }});
  }
  
  /*
    List API tokens
   */
  async getApiTokens({access_token, }) {
    const _request = {version: _data.TokensGetApiTokensClientVersion.value, access_token, };
    if (!_data.TokensGetApiTokensRequest.validate(_request)) {
      throw new Error("Invalid TokensGetApiTokensRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "get_api_tokens", request: _request, schemas: { request: _data.TokensGetApiTokensRequest, response: _data.GetApiTokens }});
  }
  
  /*
    Auth using API token
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async authWithApiToken({api_token, client_id, }) {
    const _request = {version: _data.TokensAuthWithApiTokenClientVersion.value, api_token, client_id, };
    if (!_data.TokensAuthWithApiTokenRequest.validate(_request)) {
      throw new Error("Invalid TokensAuthWithApiTokenRequest.");
    }
    return await this.transport.call({ interfaceName: "Tokens", methodName: "auth_with_api_token", request: _request, schemas: { request: _data.TokensAuthWithApiTokenRequest, response: _data.Auth }});
  }
  
}
Tokens[Schema.InterfaceName] = "Tokens";
Tokens[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
Tokens[Schema.InterfaceCapabilities] = _data.TokensClientLocalCapabilities.value;

export class SSO {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    
   */
  async getSettings() {
    const _request = {version: _data.SSOGetSettingsClientVersion.value, };
    if (!_data.SSOGetSettingsRequest.validate(_request)) {
      throw new Error("Invalid SSOGetSettingsRequest.");
    }
    return await this.transport.callMany({ interfaceName: "SSO", methodName: "get_settings", request: _request, schemas: { request: _data.SSOGetSettingsRequest, response: _data.SSOSettings }});
  }
  
  /*
    Authenticates the client using the SSO parameters passed by an external
    authentication provider.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async auth({type, params, nonce, client_id, }) {
    const _request = {version: _data.SSOAuthClientVersion.value, type, params, nonce, client_id, };
    if (!_data.SSOAuthRequest.validate(_request)) {
      throw new Error("Invalid SSOAuthRequest.");
    }
    return await this.transport.call({ interfaceName: "SSO", methodName: "auth", request: _request, schemas: { request: _data.SSOAuthRequest, response: _data.Auth }});
  }
  
  /*
    Returns a redirect URL that can be used to navigate to the external
    authentication provider.
    Might be needed for some authentication methods that require to sign the
    query parameters.

    The `state` argument allows to pass local state to be sent the
    authentication provider
    and then restored back in the application when the SSO result is returned.
   */
  async redirect({type, state, nonce, }) {
    const _request = {version: _data.SSORedirectClientVersion.value, type, state, nonce, };
    if (!_data.SSORedirectRequest.validate(_request)) {
      throw new Error("Invalid SSORedirectRequest.");
    }
    return await this.transport.call({ interfaceName: "SSO", methodName: "redirect", request: _request, schemas: { request: _data.SSORedirectRequest, response: _data.SSORedirect }});
  }
  
}
SSO[Schema.InterfaceName] = "SSO";
SSO[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
SSO[Schema.InterfaceCapabilities] = _data.SSOClientLocalCapabilities.value;

export class Profiles {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    
   */
  async getSettings() {
    const _request = {version: _data.ProfilesGetSettingsClientVersion.value, };
    if (!_data.ProfilesGetSettingsRequest.validate(_request)) {
      throw new Error("Invalid ProfilesGetSettingsRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "get_settings", request: _request, schemas: { request: _data.ProfilesGetSettingsRequest, response: _data.ProfileSettings }});
  }
  
  /*
    
   */
  async getAll({token, }) {
    const _request = {version: _data.ProfilesGetAllClientVersion.value, token, };
    if (!_data.ProfilesGetAllRequest.validate(_request)) {
      throw new Error("Invalid ProfilesGetAllRequest.");
    }
    return await this.transport.callMany({ interfaceName: "Profiles", methodName: "get_all", request: _request, schemas: { request: _data.ProfilesGetAllRequest, response: _data.ProfileResponse }});
  }
  
  /*
    
   */
  async get({username, }) {
    const _request = {version: _data.ProfilesGetClientVersion.value, username, };
    if (!_data.ProfilesGetRequest.validate(_request)) {
      throw new Error("Invalid ProfilesGetRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "get", request: _request, schemas: { request: _data.ProfilesGetRequest, response: _data.ProfileResponse }});
  }
  
  /*
    Provide option to change users username
    @param new_username
   */
  async setInfo({username, token, first_name, last_name, email, new_username, }) {
    const _request = {version: _data.ProfilesSetInfoClientVersion.value, username, token, first_name, last_name, email, new_username, };
    if (!_data.ProfilesSetInfoRequest.validate(_request)) {
      throw new Error("Invalid ProfilesSetInfoRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "set_info", request: _request, schemas: { request: _data.ProfilesSetInfoRequest, response: _data.ProfileResponse }});
  }
  
  /*
    
   */
  async setEnabled({username, token, enabled, }) {
    const _request = {version: _data.ProfilesSetEnabledClientVersion.value, username, token, enabled, };
    if (!_data.ProfilesSetEnabledRequest.validate(_request)) {
      throw new Error("Invalid ProfilesSetEnabledRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "set_enabled", request: _request, schemas: { request: _data.ProfilesSetEnabledRequest, response: _data.ProfileResponse }});
  }
  
  /*
    
   */
  async setAdmin({username, token, admin, }) {
    const _request = {version: _data.ProfilesSetAdminClientVersion.value, username, token, admin, };
    if (!_data.ProfilesSetAdminRequest.validate(_request)) {
      throw new Error("Invalid ProfilesSetAdminRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "set_admin", request: _request, schemas: { request: _data.ProfilesSetAdminRequest, response: _data.ProfileResponse }});
  }
  
  /*
    
   */
  async setNucleusRo({username, token, nucleus_ro, }) {
    const _request = {version: _data.ProfilesSetNucleusRoClientVersion.value, username, token, nucleus_ro, };
    if (!_data.ProfilesSetNucleusRoRequest.validate(_request)) {
      throw new Error("Invalid ProfilesSetNucleusRoRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "set_nucleus_ro", request: _request, schemas: { request: _data.ProfilesSetNucleusRoRequest, response: _data.ProfileResponse }});
  }
  
  /*
    
   */
  async add({username, token, first_name, last_name, email, }) {
    const _request = {version: _data.ProfilesAddClientVersion.value, username, token, first_name, last_name, email, };
    if (!_data.ProfilesAddRequest.validate(_request)) {
      throw new Error("Invalid ProfilesAddRequest.");
    }
    return await this.transport.call({ interfaceName: "Profiles", methodName: "add", request: _request, schemas: { request: _data.ProfilesAddRequest, response: _data.ProfileResponse }});
  }
  
}
Profiles[Schema.InterfaceName] = "Profiles";
Profiles[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
Profiles[Schema.InterfaceCapabilities] = _data.ProfilesClientLocalCapabilities.value;

export class Credentials {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    
   */
  async getSettings() {
    const _request = {version: _data.CredentialsGetSettingsClientVersion.value, };
    if (!_data.CredentialsGetSettingsRequest.validate(_request)) {
      throw new Error("Invalid CredentialsGetSettingsRequest.");
    }
    return await this.transport.call({ interfaceName: "Credentials", methodName: "get_settings", request: _request, schemas: { request: _data.CredentialsGetSettingsRequest, response: _data.CredentialSettings }});
  }
  
  /*
    Authenticates the client using the specified credentials.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async auth({username, password, nonce, client_id, }) {
    const _request = {version: _data.CredentialsAuthClientVersion.value, username, password, nonce, client_id, };
    if (!_data.CredentialsAuthRequest.validate(_request)) {
      throw new Error("Invalid CredentialsAuthRequest.");
    }
    return await this.transport.call({ interfaceName: "Credentials", methodName: "auth", request: _request, schemas: { request: _data.CredentialsAuthRequest, response: _data.Auth }});
  }
  
  /*
    Register the client using the specified credentials and profile.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
    @deprecated
   */
  async register({username, password, profile, nonce, client_id, }) {
    const _request = {version: _data.CredentialsRegisterClientVersion.value, username, password, profile, nonce, client_id, };
    if (!_data.CredentialsRegisterRequest.validate(_request)) {
      throw new Error("Invalid CredentialsRegisterRequest.");
    }
    return await this.transport.call({ interfaceName: "Credentials", methodName: "register", request: _request, schemas: { request: _data.CredentialsRegisterRequest, response: _data.Auth }});
  }
  
  /*
    Resets the current user password with the specified API token.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  async reset({username, new_password, token, client_id, }) {
    const _request = {version: _data.CredentialsResetClientVersion.value, username, new_password, token, client_id, };
    if (!_data.CredentialsResetRequest.validate(_request)) {
      throw new Error("Invalid CredentialsResetRequest.");
    }
    return await this.transport.call({ interfaceName: "Credentials", methodName: "reset", request: _request, schemas: { request: _data.CredentialsResetRequest, response: _data.Auth }});
  }
  
}
Credentials[Schema.InterfaceName] = "Credentials";
Credentials[Schema.InterfaceOrigin] = "OmniAuth.idl.ts";
Credentials[Schema.InterfaceCapabilities] = _data.CredentialsClientLocalCapabilities.value;
