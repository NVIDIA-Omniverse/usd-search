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
import React from "react";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import Input from "./Input";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";
var ResetPasswordForm = function (_a) {
    var payload = _a.payload, onSubmit = _a.onSubmit;
    var _b = useInput(""), newPassword = _b[0], setNewPassword = _b[1];
    var _c = useInput(""), confirmNewPassword = _c[0], setConfirmNewPassword = _c[1];
    var form = useForm({
        fields: {
            newPassword: newPassword,
            confirmNewPassword: confirmNewPassword
        },
        onSubmit: submit
    });
    function submit(_a) {
        var newPassword = _a.newPassword, confirmNewPassword = _a.confirmNewPassword;
        return __awaiter(this, void 0, void 0, function () {
            return __generator(this, function (_b) {
                if (!newPassword) {
                    throw new Error("You should specify a new password.");
                }
                if (newPassword !== confirmNewPassword) {
                    throw new Error("Passwords don't match.");
                }
                return [2 /*return*/, onSubmit(newPassword, payload)];
            });
        });
    }
    return (React.createElement(Form, null,
        React.createElement(NvidiaLogo, null),
        React.createElement(OmniverseLogo, null),
        React.createElement(FormGroup, null, form.errors && React.createElement(FormErrorList, { errors: form.errors })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { autoFocus: true, type: "password", placeholder: "New Password", name: "newPassword", disabled: form.loading, value: newPassword, onChange: setNewPassword })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { type: "password", placeholder: "Confirm New Password", name: "confirmNewPassword", disabled: form.loading, value: confirmNewPassword, onChange: setConfirmNewPassword })),
        React.createElement(ButtonGroup, null,
            React.createElement(LoginButton, { name: "submit", disabled: form.loading, onClick: form.submit },
                form.loading && React.createElement(Spinner, null),
                "Reset password"))));
};
export default ResetPasswordForm;
