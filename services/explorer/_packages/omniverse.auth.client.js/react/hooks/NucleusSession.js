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
import { Tokens } from "@omniverse/auth";
import { AuthStatus } from "@omniverse/auth/data";
import cookie from "cookie";
import jwtDecode from "jwt-decode";
import { useCallback, useEffect, useMemo, useState } from "react";
import connect from "../Connection";
export default function useNucleusSession() {
    var _this = this;
    var _a = useState(readNucleusSessionCookie), session = _a[0], setSession = _a[1];
    var writeSession = useCallback(function (session) {
        writeNucleusSessionCookie(session);
        var event = new CustomEvent("nucleus-session", { detail: session });
        window.dispatchEvent(event);
        setSession(session);
    }, []);
    useEffect(function () {
        function updateSession(event) {
            var customEvent = event;
            setSession(customEvent.detail);
        }
        window.addEventListener("nucleus-session", updateSession);
        return function () {
            window.removeEventListener("nucleus-session", updateSession);
        };
    });
    var refresh = useRefreshToken();
    var refreshSession = useCallback(function () { return __awaiter(_this, void 0, void 0, function () {
        var result;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    if (!session || !session.refreshToken || !session.server) {
                        return [2 /*return*/, null];
                    }
                    return [4 /*yield*/, refresh(session.refreshToken, session.server)];
                case 1:
                    result = _a.sent();
                    writeSession(result);
                    return [2 /*return*/, result];
            }
        });
    }); }, [session, writeSession, refresh]);
    var getSession = useCallback(function () { return __awaiter(_this, void 0, void 0, function () {
        var payload, expiresAt, willExpireInFiveSeconds;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    if (!session) {
                        return [2 /*return*/, null];
                    }
                    if (!!session.accessToken) return [3 /*break*/, 2];
                    return [4 /*yield*/, refreshSession()];
                case 1: return [2 /*return*/, _a.sent()];
                case 2:
                    payload = jwtDecode(session.accessToken);
                    if (!payload.exp) {
                        return [2 /*return*/, session];
                    }
                    expiresAt = new Date(payload.exp * 1000);
                    willExpireInFiveSeconds = expiresAt && Date.now() + 5000 >= expiresAt.getTime();
                    if (!willExpireInFiveSeconds) return [3 /*break*/, 4];
                    return [4 /*yield*/, refreshSession()];
                case 3: return [2 /*return*/, _a.sent()];
                case 4: return [2 /*return*/, session];
            }
        });
    }); }, [session, refreshSession]);
    useEffect(function () {
        if (!session) {
            return;
        }
        if (!session.accessToken && session.refreshToken) {
            refreshSession().catch(function (error) { return console.error(error); });
        }
    }, [session, refreshSession, writeSession]);
    return useMemo(function () {
        var established = Boolean(session && session.refreshToken && session.server);
        if (established) {
            return {
                established: true,
                server: session.server,
                accessToken: session.accessToken,
                refreshToken: session.refreshToken,
                setSession: writeSession,
                getSession: getSession,
            };
        }
        else {
            return {
                established: false,
                setSession: writeSession,
                getSession: getSession,
            };
        }
    }, [session, writeSession, getSession]);
}
export function useRefreshToken() {
    var _this = this;
    return useCallback(function (refreshToken, server) { return __awaiter(_this, void 0, void 0, function () {
        var tokens, result;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    console.debug("Refreshing Nucleus session...");
                    tokens = null;
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, , 4, 7]);
                    return [4 /*yield*/, connect(server, Tokens)];
                case 2:
                    tokens = _a.sent();
                    return [4 /*yield*/, tokens.refresh({ refresh_token: refreshToken })];
                case 3:
                    result = _a.sent();
                    if (result.status === AuthStatus.OK) {
                        return [2 /*return*/, { server: server, accessToken: result.access_token, refreshToken: result.refresh_token }];
                    }
                    else if (result.status === AuthStatus.Expired) {
                        return [2 /*return*/, null];
                    }
                    else {
                        throw new Error(result.status);
                    }
                    return [3 /*break*/, 7];
                case 4:
                    if (!tokens) return [3 /*break*/, 6];
                    return [4 /*yield*/, tokens.transport.close()];
                case 5:
                    _a.sent();
                    _a.label = 6;
                case 6: return [7 /*endfinally*/];
                case 7: return [2 /*return*/];
            }
        });
    }); }, []);
}
export function readNucleusSessionCookie() {
    var cookies = cookie.parse(document.cookie);
    var accessToken = cookies["nucleus_token"] || undefined;
    var refreshToken = cookies["nucleus_refresh"];
    var server = cookies["nucleus"];
    if (refreshToken) {
        return {
            server: server,
            accessToken: accessToken,
            refreshToken: refreshToken,
        };
    }
    else {
        return null;
    }
}
function writeToken(key, token) {
    var payload = jwtDecode(token);
    var expires = payload.exp ? new Date(payload.exp * 1000) : undefined;
    document.cookie = cookie.serialize(key, token, { path: "/", expires: expires });
    return expires;
}
function deleteCookie(key) {
    document.cookie = cookie.serialize(key, "", { path: "/", maxAge: 0 });
}
export function writeNucleusSessionCookie(session) {
    if (session) {
        var accessExpiration = writeToken("nucleus_token", session.accessToken);
        console.debug("Set Nucleus access token, expire at " + accessExpiration + ".");
        var refreshExpiration = writeToken("nucleus_refresh", session.refreshToken);
        console.debug("Set Nucleus refresh token, expire at " + refreshExpiration + ".");
        document.cookie = cookie.serialize("nucleus", session.server, { path: "/", expires: refreshExpiration });
        console.debug("Set Nucleus server: " + session.server);
    }
    else {
        console.debug("Delete Nucleus session.");
        deleteCookie("nucleus_token");
        deleteCookie("nucleus_refresh");
        deleteCookie("nucleus");
    }
}
