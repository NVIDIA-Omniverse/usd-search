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

var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g;
    return g = { next: verb(0), "throw": verb(1), "return": verb(2) }, typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (_) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
import { SSO } from "@omniverse/auth/client";
import { useCallback, useEffect, useState } from "react";
import connect from "../Connection";
import { callAPI } from "../util/API";
export default function useSSOSettings(server) {
    var _this = this;
    var _a = useState(null), settings = _a[0], setSettings = _a[1];
    var _b = useState([]), errors = _b[0], setErrors = _b[1];
    var _c = useState(function () { return new Date(); }), queryDate = _c[0], setQueryDate = _c[1];
    var retry = useCallback(function () {
        setQueryDate(new Date());
    }, []);
    useEffect(function () {
        var subscribed = true;
        setSettings(null);
        setErrors([]);
        var debounced;
        if (server) {
            debounced = window.setTimeout(function () { return __awaiter(_this, void 0, void 0, function () {
                var settings_1, error_1;
                return __generator(this, function (_a) {
                    switch (_a.label) {
                        case 0:
                            _a.trys.push([0, 2, , 3]);
                            return [4 /*yield*/, callAPI({
                                    http: function () { return httpSSOSettings(server); },
                                    ws: function () { return wsSSOSettings(server); },
                                })];
                        case 1:
                            settings_1 = _a.sent();
                            if (subscribed) {
                                setSettings(settings_1);
                            }
                            return [3 /*break*/, 3];
                        case 2:
                            error_1 = _a.sent();
                            setErrors(["Failed to connect to the server (" + error_1 + ")."]);
                            console.warn(error_1);
                            return [3 /*break*/, 3];
                        case 3: return [2 /*return*/];
                    }
                });
            }); }, 300);
        }
        return function () {
            subscribed = false;
            if (debounced) {
                clearTimeout(debounced);
            }
        };
    }, [server, queryDate]);
    return { settings: settings, errors: errors, retry: retry };
}
function httpSSOSettings(server) {
    return __awaiter(this, void 0, void 0, function () {
        var response, json;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, fetch("https://" + server + "/omni/auth/api/sso/settings", { cache: "force-cache" })];
                case 1:
                    response = _a.sent();
                    return [4 /*yield*/, response.json()];
                case 2:
                    json = _a.sent();
                    return [2 /*return*/, json.settings];
            }
        });
    });
}
function wsSSOSettings(server) {
    return __awaiter(this, void 0, void 0, function () {
        var sso, settings;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    sso = null;
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, , 5, 8]);
                    return [4 /*yield*/, connect(server, SSO, { get_settings: 0 })];
                case 2:
                    sso = _a.sent();
                    return [4 /*yield*/, sso.getSettings()];
                case 3:
                    settings = _a.sent();
                    return [4 /*yield*/, settings.readAll()];
                case 4: return [2 /*return*/, _a.sent()];
                case 5:
                    if (!sso) return [3 /*break*/, 7];
                    return [4 /*yield*/, sso.transport.close()];
                case 6:
                    _a.sent();
                    _a.label = 7;
                case 7: return [7 /*endfinally*/];
                case 8: return [2 /*return*/];
            }
        });
    });
}
