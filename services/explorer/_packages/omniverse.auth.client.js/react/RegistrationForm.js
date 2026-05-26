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

var __makeTemplateObject = (this && this.__makeTemplateObject) || function (cooked, raw) {
    if (Object.defineProperty) { Object.defineProperty(cooked, "raw", { value: raw }); } else { cooked.raw = raw; }
    return cooked;
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
import React, { useRef } from "react";
import styled from "styled-components";
import Button from "./Button";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useCredentialRegistration from "./hooks/CredentialRegistration";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import Input from "./Input";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import ServerName from "./ServerName";
import Spinner from "./Spinner";
var RegistrationForm = function (_a) {
    var server = _a.server, className = _a.className, loading = _a.loading, errors = _a.errors, extras = _a.extras, nonce = _a.nonce, onSubmit = _a.onSubmit, onStart = _a.onStart, onSuccess = _a.onSuccess, onFail = _a.onFail, onCancel = _a.onCancel;
    var _b = useInput(""), username = _b[0], setUsername = _b[1];
    var _c = useInput(""), password = _c[0], setPassword = _c[1];
    var _d = useInput(""), confirmPassword = _d[0], setConfirmPassword = _d[1];
    var _e = useInput(""), firstName = _e[0], setFirstName = _e[1];
    var _f = useInput(""), lastName = _f[0], setLastName = _f[1];
    var _g = useInput(""), email = _g[0], setEmail = _g[1];
    var emailRef = useRef(null);
    var register = useCredentialRegistration();
    var form = useForm({
        fields: {
            username: username,
            password: password,
            confirmPassword: confirmPassword,
            server: server,
            firstName: firstName,
            lastName: lastName,
            email: email,
            nonce: nonce,
            extras: extras
        },
        onSubmit: function (fields) { return __awaiter(void 0, void 0, void 0, function () {
            var errors, submit;
            var _a;
            return __generator(this, function (_b) {
                errors = [];
                if (!((_a = emailRef.current) === null || _a === void 0 ? void 0 : _a.checkValidity())) {
                    errors.push("Email is not valid.");
                }
                if (!fields.password) {
                    errors.push("Password is empty.");
                }
                if (fields.password !== fields.confirmPassword) {
                    errors.push("Passwords don't match.");
                }
                if (errors.length > 0) {
                    return [2 /*return*/, { errors: errors }];
                }
                submit = onSubmit || register;
                return [2 /*return*/, submit(fields)];
            });
        }); },
        onStart: onStart,
        onSuccess: onSuccess,
        onFail: onFail,
    });
    return (React.createElement(Form, { className: className },
        React.createElement(NvidiaLogo, null),
        React.createElement(OmniverseLogo, null),
        React.createElement(ServerName, { title: server }, server),
        React.createElement(FormGroup, null,
            React.createElement(FormErrorList, { errors: errors }),
            React.createElement(FormErrorList, { errors: form.errors })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { autoFocus: true, name: "username", value: username, disabled: loading || form.loading, onChange: setUsername, placeholder: "Username" })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { name: "password", type: "password", value: password, disabled: loading || form.loading, onChange: setPassword, placeholder: "Type Password" })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { name: "confirmPassword", type: "password", value: confirmPassword, disabled: loading || form.loading, onChange: setConfirmPassword, placeholder: "Confirm Password" })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { name: "firstName", value: firstName, disabled: loading || form.loading, onChange: setFirstName, placeholder: "First Name" })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { name: "lastName", value: lastName, disabled: loading || form.loading, onChange: setLastName, placeholder: "Last Name" })),
        React.createElement(FormGroup, null,
            React.createElement(Input, { name: "email", type: "email", value: email, disabled: loading || form.loading, onChange: setEmail, placeholder: "Email", ref: emailRef, required: true })),
        React.createElement(RegistrationButtonGroup, null,
            React.createElement(Button, { disabled: loading || form.loading, onClick: form.submit },
                (loading || form.loading) && React.createElement(Spinner, null),
                " Create"),
            React.createElement(Button, { disabled: loading || form.loading, onClick: onCancel }, "Cancel"))));
};
var RegistrationButtonGroup = styled(ButtonGroup)(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  flex-direction: row;\n  justify-content: space-between;\n"], ["\n  flex-direction: row;\n  justify-content: space-between;\n"])));
export default RegistrationForm;
var templateObject_1;
