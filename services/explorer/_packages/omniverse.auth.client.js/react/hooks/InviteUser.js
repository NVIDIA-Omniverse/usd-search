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

var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
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
import { AuthStatus } from "@omniverse/auth/data";
import AuthMessages from "../AuthMessages";
import { encodeResetPasswordPayload, GenerateResetPasswordPayloadError, resetPassword, ResetPasswordError } from "./ResetPassword";
export function encodeInvitationPayload(server, username, adminToken, _a) {
    var _b = _a === void 0 ? {} : _a, state = _b.state;
    try {
        return encodeResetPasswordPayload(server, username, adminToken, { state: state });
    }
    catch (error) {
        if (error instanceof GenerateResetPasswordPayloadError) {
            throw new GenerateInvitationPayloadError(error.result);
        }
        throw error;
    }
}
var GenerateInvitationPayloadError = /** @class */ (function (_super) {
    __extends(GenerateInvitationPayloadError, _super);
    function GenerateInvitationPayloadError(result) {
        var _a;
        var _this = _super.call(this) || this;
        _this.messages = __assign(__assign({}, AuthMessages), (_a = {}, _a[AuthStatus.Denied] = "You don't have access to generate tokens for this user.", _a));
        _this.result = result;
        _this.message = _this.messages[result.status] || DefaultErrorMessage(result.status);
        return _this;
    }
    return GenerateInvitationPayloadError;
}(Error));
export { GenerateInvitationPayloadError };
export function decodeInvitationPayload(encoded) {
    var json = JSON.parse(atob(encoded));
    if (!json.username || !json.token || !json.server) {
        throw new Error("Invalid invitation payload.");
    }
    return json;
}
export function inviteUser(password, payload) {
    return __awaiter(this, void 0, void 0, function () {
        return __generator(this, function (_a) {
            try {
                return [2 /*return*/, resetPassword(password, payload)];
            }
            catch (error) {
                if (error instanceof ResetPasswordError) {
                    throw new InvitationError(error.result);
                }
                throw error;
            }
            return [2 /*return*/];
        });
    });
}
var InvitationError = /** @class */ (function (_super) {
    __extends(InvitationError, _super);
    function InvitationError(result) {
        var _a;
        var _this = _super.call(this) || this;
        _this.messages = __assign(__assign({}, AuthMessages), (_a = {}, _a[AuthStatus.Expired] = "The link has expired.", _a));
        _this.result = result;
        _this.message = _this.messages[result.status] || DefaultErrorMessage(result.status);
        return _this;
    }
    return InvitationError;
}(Error));
export { InvitationError };
export var DefaultErrorMessage = function (status) { return "Unknown error, please contact administrator (" + status + ")."; };
