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

import { AuthStatus } from "@omniverse/auth/data";
import React from "react";
import FormError from "./FormError";
import LoginSuccess from "./LoginSuccess";
var SSOPageContent = function (_a) {
    var _b;
    var auth = _a.auth, error = _a.error;
    if (error) {
        return React.createElement(FormError, null, (_b = error.message) !== null && _b !== void 0 ? _b : error.toString());
    }
    if (!auth) {
        return React.createElement(FormError, null, "Service is not responding.");
    }
    if (auth.errors && auth.errors.length) {
        return (React.createElement(React.Fragment, null, auth.errors.map(function (error) { return (React.createElement(FormError, { key: error }, error)); })));
    }
    if (auth.status === AuthStatus.OK) {
        return React.createElement(LoginSuccess, null);
    }
    return React.createElement(React.Fragment, null, auth.status);
};
export default SSOPageContent;
