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
var __rest = (this && this.__rest) || function (s, e) {
    var t = {};
    for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p) && e.indexOf(p) < 0)
        t[p] = s[p];
    if (s != null && typeof Object.getOwnPropertySymbols === "function")
        for (var i = 0, p = Object.getOwnPropertySymbols(s); i < p.length; i++) {
            if (e.indexOf(p[i]) < 0 && Object.prototype.propertyIsEnumerable.call(s, p[i]))
                t[p[i]] = s[p[i]];
        }
    return t;
};
import { useCallback, useState } from "react";
import { useHistory, useLocation } from "react-router-dom";
import useNucleusSession from "./NucleusSession";
export default function useAuthSync() {
    var _this = this;
    var _a = useState(), result = _a[0], setResult = _a[1];
    var location = useLocation();
    var search = new URLSearchParams(location.search);
    var redirectURL = decodeURI(search.get("redirect") || "");
    var history = useHistory();
    var setSession = useNucleusSession().setSession;
    var sync = useCallback(function (auth) { return __awaiter(_this, void 0, void 0, function () {
        var redirectTo, nonce, navigateURL;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    setSession({ server: auth.server, accessToken: auth.accessToken, refreshToken: auth.refreshToken });
                    redirectTo = (auth.extras && auth.extras.redirect) || redirectURL;
                    nonce = auth.nonce;
                    if (!(redirectTo && !nonce)) return [3 /*break*/, 2];
                    // `nonce` argument is only used by new clients that
                    // don't need to run an HTTP server for receiving authentication results.
                    return [4 /*yield*/, sendAuth(redirectTo, auth)];
                case 1:
                    // `nonce` argument is only used by new clients that
                    // don't need to run an HTTP server for receiving authentication results.
                    _a.sent();
                    _a.label = 2;
                case 2:
                    setResult(auth);
                    navigateURL = auth.extras && auth.extras.navigate;
                    if (navigateURL) {
                        if (navigateURL.startsWith("http")) {
                            window.location.href = navigateURL;
                        }
                        else {
                            history.push(navigateURL);
                        }
                    }
                    return [2 /*return*/];
            }
        });
    }); }, [redirectURL, setSession, history]);
    return {
        redirectURL: redirectURL,
        result: result,
        sync: sync,
    };
}
function sendAuth(url, auth) {
    return __awaiter(this, void 0, void 0, function () {
        var extras, body, response, error_1;
        return __generator(this, function (_a) {
            switch (_a.label) {
                case 0:
                    extras = auth.extras, body = __rest(auth, ["extras"]);
                    _a.label = 1;
                case 1:
                    _a.trys.push([1, 3, , 4]);
                    return [4 /*yield*/, fetch(url, {
                            body: JSON.stringify(body),
                            method: "POST",
                        })];
                case 2:
                    response = _a.sent();
                    return [3 /*break*/, 4];
                case 3:
                    error_1 = _a.sent();
                    console.error(error_1);
                    throw new Error("Unable to send results back to the application that initiated the authentication. " +
                        "This error message is expected if your client was released prior to year 2021.");
                case 4:
                    if (!response.ok) {
                        throw new Error("Unable to send results back to the application that initiated the authentication. " +
                            "This error message is expected if your client was released prior to year 2021.");
                    }
                    return [2 /*return*/];
            }
        });
    });
}
