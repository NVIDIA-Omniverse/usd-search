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

export function joinURL() {
    var args = [];
    for (var _i = 0; _i < arguments.length; _i++) {
        args[_i] = arguments[_i];
    }
    return args.reduce(function (path, value, index) {
        if (!value) {
            return path;
        }
        if (index !== 0 && !value.startsWith("/")) {
            value = "/" + value;
        }
        if (index !== args.length - 1 && value.endsWith("/")) {
            value = value.substring(0, value.length - 1);
        }
        return path + value;
    }, "");
}
export function getBaseURL() {
    var _a;
    var base = document.getElementById("public-url");
    var baseURL = (_a = base === null || base === void 0 ? void 0 : base.href) !== null && _a !== void 0 ? _a : window.location.href;
    if (baseURL) {
        if (baseURL === "/") {
            baseURL = "";
        }
        else {
            if (baseURL.endsWith("/")) {
                baseURL = baseURL.substr(0, baseURL.length - 1);
            }
        }
    }
    return baseURL;
}
