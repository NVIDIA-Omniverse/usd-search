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

var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
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
import { SSO } from "@omniverse/auth";
import { AuthStatus } from "@omniverse/auth/data";
import React, { useEffect } from "react";
import connect from "./Connection";
import { callAPI } from "./util/API";
var SSOAuth = function (_a) {
    var params = _a.params, _b = _a.search, search = _b === void 0 ? "" : _b, children = _a.children, onAuth = _a.onAuth, onError = _a.onError;
    if (!search) {
        search = window.location.search;
    }
    useEffect(function () {
        authenticate(params, search).then(onAuth).catch(onError);
    }, [params, search, onAuth, onError]);
    return React.createElement(React.Fragment, null, children);
};
export default SSOAuth;
export function redirectToSSO(_a) {
    var settings = _a.settings, server = _a.server, redirectBackTo = _a.redirectBackTo, extras = _a.extras, nonce = _a.nonce;
    return __awaiter(this, void 0, void 0, function () {
        var type, params, state, result, url;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    if (!redirectBackTo.endsWith("/")) {
                        redirectBackTo += "/";
                    }
                    type = settings.type;
                    params = {
                        type: type,
                        redirectBackTo: redirectBackTo,
                        server: server,
                        extras: extras,
                        nonce: nonce,
                    };
                    return [4 /*yield*/, encodeState(params)];
                case 1:
                    state = _b.sent();
                    redirectBackTo += state;
                    return [4 /*yield*/, callAPI({
                            http: function () { return httpRedirectSSO(server, type, state, nonce); },
                            ws: function () { return wsRedirectSSO(server, type, state, nonce); },
                        })];
                case 2:
                    result = _b.sent();
                    url = result.redirect;
                    url = url.replace("{redirect_url}", encodeURIComponent(redirectBackTo));
                    url = url.replace("{redirect_url_state}", btoa(redirectBackTo));
                    window.location.assign(url);
                    return [2 /*return*/];
            }
        });
    });
}
function httpRedirectSSO(server, type, state, nonce) {
    return __awaiter(this, void 0, void 0, function () {
        var params, response;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    params = new URLSearchParams();
                    params.set("type", type);
                    if (state) {
                        params.set("state", state);
                    }
                    if (nonce) {
                        params.set("nonce", nonce);
                    }
                    return [4 /*yield*/, fetch("https://" + server + "/omni/auth/api/sso/redirect?" + params)];
                case 1:
                    response = _a.sent();
                    return [4 /*yield*/, response.json()];
                case 2: return [2 /*return*/, _a.sent()];
            }
        });
    });
}
function wsRedirectSSO(server, type, state, nonce) {
    return __awaiter(this, void 0, void 0, function () {
        var sso, result;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, connect(server, SSO, { redirect: 0 })];
                case 1:
                    sso = _a.sent();
                    _a.label = 2;
                case 2:
                    _a.trys.push([2, , 4, 6]);
                    return [4 /*yield*/, sso.redirect({ type: type, state: state, nonce: nonce })];
                case 3:
                    result = _a.sent();
                    if (result.status !== AuthStatus.OK) {
                        throw result;
                    }
                    return [2 /*return*/, result];
                case 4: return [4 /*yield*/, sso.transport.close()];
                case 5:
                    _a.sent();
                    return [7 /*endfinally*/];
                case 6: return [2 /*return*/];
            }
        });
    });
}
export function authenticate(encodedSSO, urlSearchParams) {
    return __awaiter(this, void 0, void 0, function () {
        var _a, server, type, nonce, extras;
        return __generator(this, function (_b) {
            switch (_b.label) {
                case 0:
                    _a = decodeState(encodedSSO), server = _a.server, type = _a.type, nonce = _a.nonce, extras = _a.extras;
                    if (!type) {
                        throw new Error("The authentication type is not specified.");
                    }
                    return [4 /*yield*/, authenticateSSO(server, type, urlSearchParams, nonce, extras)];
                case 1: return [2 /*return*/, _b.sent()];
            }
        });
    });
}
export function encodeState(params) {
    return __awaiter(this, void 0, void 0, function () {
        var json;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    json = JSON.stringify(params);
                    return [4 /*yield*/, new Promise(function (resolve, reject) {
                            var reader = new FileReader();
                            reader.onerror = reject;
                            reader.onloadend = function () {
                                var result = reader.result.split(",");
                                var data = result[1];
                                resolve(data.replace(/=/g, ""));
                            };
                            reader.readAsDataURL(new Blob([json]));
                        })];
                case 1: return [2 /*return*/, _a.sent()];
            }
        });
    });
}
export function decodeState(state) {
    var json = atob(state);
    return JSON.parse(json);
}
export function authenticateSSO(server, type, query, nonce, extras) {
    return __awaiter(this, void 0, void 0, function () {
        var search, params, auth;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    search = new URLSearchParams(query);
                    params = Array.from(search.entries()).reduce(function (all, _a) {
                        var name = _a[0], value = _a[1];
                        all[name] = value.replace(/ /g, "+");
                        return all;
                    }, {});
                    return [4 /*yield*/, callAPI({
                            http: function () { return httpAuthenticateSSO(server, type, params, nonce); },
                            ws: function () { return wsAuthenticateSSO(server, type, params, nonce); },
                        })];
                case 1:
                    auth = _a.sent();
                    return [2 /*return*/, {
                            accessToken: auth.access_token,
                            refreshToken: auth.refresh_token,
                            status: auth.status,
                            username: auth.username,
                            profile: auth.profile,
                            nonce: auth.nonce,
                            server: server,
                            extras: extras,
                        }];
            }
        });
    });
}
function httpAuthenticateSSO(server, type, params, nonce) {
    return __awaiter(this, void 0, void 0, function () {
        var response;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, fetch("https://" + server + "/omni/auth/api/sso/" + type.toLowerCase(), {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify(__assign(__assign({}, params), { nonce: nonce })),
                    })];
                case 1:
                    response = _a.sent();
                    return [4 /*yield*/, response.json()];
                case 2: return [2 /*return*/, _a.sent()];
            }
        });
    });
}
function wsAuthenticateSSO(server, type, params, nonce) {
    return __awaiter(this, void 0, void 0, function () {
        var sso;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0: return [4 /*yield*/, connect(server, SSO, { auth: 0 })];
                case 1:
                    sso = _a.sent();
                    _a.label = 2;
                case 2:
                    _a.trys.push([2, , 4, 6]);
                    return [4 /*yield*/, sso.auth({ type: type, params: params, nonce: nonce })];
                case 3: return [2 /*return*/, _a.sent()];
                case 4: return [4 /*yield*/, sso.transport.close()];
                case 5:
                    _a.sent();
                    return [7 /*endfinally*/];
                case 6: return [2 /*return*/];
            }
        });
    });
}
