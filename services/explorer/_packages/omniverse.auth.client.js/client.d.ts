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

import Client from "@omniverse/idl/connection/transport";
import Stream from "@omniverse/idl/stream";
import { InterfaceName, InterfaceOrigin, InterfaceCapabilities } from "@omniverse/idl/schema";
import * as data from "./data";

export class DeviceFlow {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    Starts the device flow authentication.
    @param version
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public authorize(request: data.DeviceFlowAuthorizeRequest): Promise<data.DeviceAuthorize>;
  
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
  public submit(request: data.DeviceFlowSubmitRequest): Promise<data.DeviceSubmit>;
  
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
  public token(request: data.DeviceFlowTokenRequest): Promise<data.Auth>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class UserStore {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    Returns value in the user's store by the specified key.
    If the key does not exist, returns AuthStatus.NotFound.
   */
  public get(request: data.UserStoreGetRequest): Promise<data.UserStoreResult>;
  
  /*
    
   */
  public set(request: data.UserStoreSetRequest): Promise<data.UserStoreResult>;
  
  /*
    Removes value from the user's store by the specified key.
    If the key does not exist, returns AuthStatus.NotFound.
   */
  public remove(request: data.UserStoreRemoveRequest): Promise<data.UserStoreResult>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class Tokens {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    Allows administrator to generate tokens for users.
    Can let the user to work in a system for a limited period of time and reset
    his password.
    Returns a one-time API token as an access_token value.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public generate(request: data.TokensGenerateRequest): Promise<data.Auth>;
  
  /*
    Refreshes the authentication using a refresh token.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public refresh(request: data.TokensRefreshRequest): Promise<data.Auth>;
  
  /*
    Invalidates refresh tokens for the specified user.
    This method is only available for administrators.
    Optionally accepts a refresh token that needs to be invalidated.
   */
  public invalidate(request: data.TokensInvalidateRequest): Promise<data.Auth>;
  
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
  public subscribe(request?: data.TokensSubscribeRequest): Promise<Stream<data.Auth>>;
  
  /*
    Create a new API token.
    `expire_at` is an ISO-8601 date describing when this token must be revoked.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public createApiToken(request: data.TokensCreateApiTokenRequest): Promise<data.CreateApiToken>;
  
  /*
    Delete API token
   */
  public deleteApiToken(request: data.TokensDeleteApiTokenRequest): Promise<data.DeleteApiToken>;
  
  /*
    List API tokens
   */
  public getApiTokens(request: data.TokensGetApiTokensRequest): Promise<data.GetApiTokens>;
  
  /*
    Auth using API token
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public authWithApiToken(request: data.TokensAuthWithApiTokenRequest): Promise<data.Auth>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class SSO {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    
   */
  public getSettings(request?: data.SSOGetSettingsRequest): Promise<Stream<data.SSOSettings>>;
  
  /*
    Authenticates the client using the SSO parameters passed by an external
    authentication provider.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public auth(request: data.SSOAuthRequest): Promise<data.Auth>;
  
  /*
    Returns a redirect URL that can be used to navigate to the external
    authentication provider.
    Might be needed for some authentication methods that require to sign the
    query parameters.

    The `state` argument allows to pass local state to be sent the
    authentication provider
    and then restored back in the application when the SSO result is returned.
   */
  public redirect(request: data.SSORedirectRequest): Promise<data.SSORedirect>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class Profiles {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    
   */
  public getSettings(request?: data.ProfilesGetSettingsRequest): Promise<data.ProfileSettings>;
  
  /*
    
   */
  public getAll(request: data.ProfilesGetAllRequest): Promise<Stream<data.ProfileResponse>>;
  
  /*
    
   */
  public get(request: data.ProfilesGetRequest): Promise<data.ProfileResponse>;
  
  /*
    Provide option to change users username
    @param new_username
   */
  public setInfo(request: data.ProfilesSetInfoRequest): Promise<data.ProfileResponse>;
  
  /*
    
   */
  public setEnabled(request: data.ProfilesSetEnabledRequest): Promise<data.ProfileResponse>;
  
  /*
    
   */
  public setAdmin(request: data.ProfilesSetAdminRequest): Promise<data.ProfileResponse>;
  
  /*
    
   */
  public setNucleusRo(request: data.ProfilesSetNucleusRoRequest): Promise<data.ProfileResponse>;
  
  /*
    
   */
  public add(request: data.ProfilesAddRequest): Promise<data.ProfileResponse>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class Credentials {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    
   */
  public getSettings(request?: data.CredentialsGetSettingsRequest): Promise<data.CredentialSettings>;
  
  /*
    Authenticates the client using the specified credentials.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public auth(request: data.CredentialsAuthRequest): Promise<data.Auth>;
  
  /*
    Register the client using the specified credentials and profile.
    Supports `nonce` that represents a random string generated by the service
    to let clients subscribe to
    the authentication results.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
    @deprecated
   */
  public register(request: data.CredentialsRegisterRequest): Promise<data.Auth>;
  
  /*
    Resets the current user password with the specified API token.
    @param client_id Defines an identifier representing the client app. Can be
    any string like "Navigator 3.3.0".
   */
  public reset(request: data.CredentialsResetRequest): Promise<data.Auth>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}
