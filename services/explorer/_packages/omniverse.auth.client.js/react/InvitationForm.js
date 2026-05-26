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
import React, { useMemo } from "react";
import styled from "styled-components";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useCredentialSettings from "./hooks/CredentialSettings";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import useSSORedirect from "./hooks/SSORedirect";
import useSSOSettings from "./hooks/SSOSettings";
import { default as OmniverseInput } from "./Input";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";
import SSOButtonGroup from "./SSOButtonGroup";
import SSOSplitter from "./SSOSplitter";
import Headline from "./Headline";
var InvitationForm = function (_a) {
    var username = _a.username, server = _a.server, _b = _a.ssoRedirectBackTo, ssoRedirectBackTo = _b === void 0 ? window.location.origin + "/sso" : _b, onSubmit = _a.onSubmit;
    var _c = useInput(""), newPassword = _c[0], setNewPassword = _c[1];
    var _d = useInput(""), confirmNewPassword = _d[0], setConfirmNewPassword = _d[1];
    var credentialSettings = useCredentialSettings(server);
    var ssoSettings = useSSOSettings(server);
    var redirect = useSSORedirect(server, ssoRedirectBackTo);
    var ssoAvailable = useMemo(function () { return Boolean(username.includes("@") && (ssoSettings === null || ssoSettings === void 0 ? void 0 : ssoSettings.settings) && ssoSettings.settings.length > 0); }, [username, ssoSettings]);
    var credentialsAvailable = useMemo(function () { var _a; return Boolean(!username.includes("@") && ((_a = credentialSettings === null || credentialSettings === void 0 ? void 0 : credentialSettings.settings) === null || _a === void 0 ? void 0 : _a.is_ui_visible)); }, [username, credentialSettings]);
    var form = useForm({
        fields: {
            newPassword: newPassword,
            confirmNewPassword: confirmNewPassword,
        },
        onSubmit: submit,
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
                return [2 /*return*/, onSubmit(newPassword)];
            });
        });
    }
    if (!credentialSettings || !ssoSettings) {
        return (React.createElement(Form, null,
            React.createElement(NvidiaLogo, null),
            React.createElement(OmniverseLogo, null)));
    }
    return (React.createElement(Form, null,
        React.createElement(NvidiaLogo, null),
        React.createElement(OmniverseLogo, null),
        form.errors && (React.createElement(FormGroup, null,
            React.createElement(FormErrorList, { errors: form.errors }))),
        React.createElement(Headline, null,
            "Welcome to Omniverse! ",
            React.createElement("br", null),
            "Your username is: ",
            React.createElement("br", null),
            "\"",
            username,
            "\" ",
            React.createElement("br", null),
            " on ",
            React.createElement("br", null),
            " ",
            React.createElement("b", null, server)),
        React.createElement(Caption, { credentialsAvailable: credentialsAvailable, ssoAvailable: ssoAvailable }),
        credentialsAvailable && (React.createElement(React.Fragment, null,
            React.createElement(FormGroup, null,
                React.createElement(OmniverseInput, { autoFocus: true, type: "password", placeholder: "Type Password", name: "newPassword", disabled: form.loading, value: newPassword, onChange: setNewPassword })),
            React.createElement(FormGroup, null,
                React.createElement(OmniverseInput, { type: "password", placeholder: "Confirm Password", name: "confirmNewPassword", disabled: form.loading, value: confirmNewPassword, onChange: setConfirmNewPassword })),
            React.createElement(ButtonGroup, null,
                React.createElement(LoginButton, { name: "submit", disabled: form.loading, onClick: form.submit },
                    form.loading && React.createElement(Spinner, null),
                    "Log in")))),
        credentialsAvailable && ssoAvailable && React.createElement(SSOSplitter, null, "or"),
        ssoAvailable && ssoSettings.settings && React.createElement(SSOButtonGroup, { ssoSettings: ssoSettings.settings, onClick: redirect })));
};
var Caption = function (_a) {
    var credentialsAvailable = _a.credentialsAvailable, ssoAvailable = _a.ssoAvailable;
    if (credentialsAvailable && ssoAvailable) {
        return React.createElement(StyledCaption, null, "Please continue by providing a new password or logging in with SSO.");
    }
    if (credentialsAvailable) {
        return React.createElement(StyledCaption, null, "Please continue by providing a new password.");
    }
    if (ssoAvailable) {
        return React.createElement(StyledCaption, null, "Please continue by logging in with SSO.");
    }
    return null;
};
var StyledCaption = styled.div(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  font-weight: 400;\n  font-size: 11pt;\n  position: relative;\n  text-align: center;\n  padding: 1em 0.5em;\n  margin: 0 1em;\n  border-top: 1px solid #bbbbbb;\n  z-index: 1;\n"], ["\n  font-weight: 400;\n  font-size: 11pt;\n  position: relative;\n  text-align: center;\n  padding: 1em 0.5em;\n  margin: 0 1em;\n  border-top: 1px solid #bbbbbb;\n  z-index: 1;\n"])));
export default InvitationForm;
var templateObject_1;
