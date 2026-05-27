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

var _a;
import { AuthStatus } from "@omniverse/auth/data";
var AuthMessages = (_a = {},
    _a[AuthStatus.Disabled] = "This account is disabled by administrator.",
    _a[AuthStatus.Expired] = "The session is expired.",
    _a[AuthStatus.Exists] = "This user already exists.",
    _a[AuthStatus.NotFound] = "User is not found.",
    _a[AuthStatus.ReadOnly] = "The setting for this user can be changed only by the " +
        "system administrator or with the service configuration.",
    _a[AuthStatus.Denied] = "Wrong credentials or the user does not exist.",
    _a[AuthStatus.UsernameRequired] = "Username is required.",
    _a[AuthStatus.NotSupported] = "This authentication method is not supported.",
    _a[AuthStatus.InternalError] = "Internal server error has occurred. Please contact administrator or try again later.",
    _a[AuthStatus.ConnectionError] = "Cannot establish a connection to remote authentication servers. Try again later.",
    _a[AuthStatus.InvalidUsername] = "Username can only contain alphanumeric characters and underscores.",
    _a[AuthStatus.UnknownError] = "Unknown error has occurred. Please contact administrator.",
    _a[AuthStatus.InvalidToken] = "The provided token is invalid.",
    _a[AuthStatus.Subscribed] = "Failed to subscribe to authentication results.",
    _a[AuthStatus.InvalidRequest] = "Invalid request.",
    _a[AuthStatus.Pending] = "Please try again later.",
    _a);
export default AuthMessages;
