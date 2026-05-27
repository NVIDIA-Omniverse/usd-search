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
import { faPencilAlt } from "@fortawesome/free-solid-svg-icons/faPencilAlt";
import React, { useCallback, useState } from "react";
import styled from "styled-components";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import FormSpinner from "./FormSpinner";
import useCredentialAuth from "./hooks/CredentialAuth";
import useCredentialSettings from "./hooks/CredentialSettings";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import useSSORedirect from "./hooks/SSORedirect";
import useSSOSettings from "./hooks/SSOSettings";
import Icon from "./Icon";
import Input from "./Input";
import Link from "./Link";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import ServerForm from "./ServerForm";
import ServerName from "./ServerName";
import Spinner from "./Spinner";
import SSOButtonGroup from "./SSOButtonGroup";
import SSOSplitter from "./SSOSplitter";
import { getBaseURL, joinURL } from "./util/URL";
var AuthForm = function (_a) {
    var _b, _c;
    var _d = _a.initial, initial = _d === void 0 ? {} : _d, _e = _a.extras, extras = _e === void 0 ? {} : _e, errors = _a.errors, className = _a.className, _f = _a.forceCredentials, forceCredentials = _f === void 0 ? false : _f, _g = _a.readonly, readonly = _g === void 0 ? {} : _g, loading = _a.loading, ssoRedirectBackTo = _a.ssoRedirectBackTo, nonce = _a.nonce, _h = _a.visibility, visibility = _h === void 0 ? { server: true } : _h, onSignIn = _a.onSignIn, onStart = _a.onStart, onSuccess = _a.onSuccess, onRegister = _a.onRegister, onFail = _a.onFail, children = _a.children;
    if (!ssoRedirectBackTo) {
        var baseURL = getBaseURL();
        if (baseURL.startsWith("/")) {
            ssoRedirectBackTo = joinURL(window.location.origin, baseURL, "/sso");
        }
        else if (baseURL) {
            ssoRedirectBackTo = joinURL(baseURL, "/sso");
        }
        else {
            ssoRedirectBackTo = joinURL(window.location.origin, "/sso");
        }
    }
    var _j = useInput(initial.username || ""), username = _j[0], setUsername = _j[1];
    var _k = useInput(initial.password || ""), password = _k[0], setPassword = _k[1];
    var _l = useState(typeof initial.server === "undefined" ? "" : validateServer(initial.server)), server = _l[0], setServer = _l[1];
    var authenticate = useCredentialAuth();
    var form = useForm({
        fields: {
            username: username,
            password: password,
            server: server,
            nonce: nonce,
            extras: extras,
        },
        onStart: onStart,
        onSubmit: onSignIn || authenticate,
        onSuccess: onSuccess,
        onFail: onFail,
    });
    var credentialSettings = useCredentialSettings(server);
    var ssoSettings = useSSOSettings(server);
    var _m = useState(false), redirecting = _m[0], setRedirecting = _m[1];
    var redirect = useSSORedirect(server, ssoRedirectBackTo, extras, nonce);
    var handleRedirect = useCallback(function (settings) {
        setRedirecting(true);
        return redirect(settings);
    }, [redirect]);
    var register = useCallback(function (event) {
        event.preventDefault();
        if (loading || form.loading) {
            return;
        }
        if (!server) {
            form.setErrors(["You must specify the server."]);
            return;
        }
        if (onRegister) {
            onRegister(server);
        }
    }, [server, form, loading, onRegister]);
    var chooseServer = useCallback(function (fields) {
        setServer(validateServer(fields.server));
    }, []);
    var resetServer = useCallback(function () {
        form.setErrors([]);
        setServer("");
    }, [form]);
    var retry = useCallback(function () {
        credentialSettings.retry();
        ssoSettings.retry();
    }, [credentialSettings, ssoSettings]);
    var supportsCredentials = forceCredentials || ((_b = credentialSettings.settings) === null || _b === void 0 ? void 0 : _b.is_ui_visible);
    var supportsRegistration = !forceCredentials && onRegister && ((_c = credentialSettings.settings) === null || _c === void 0 ? void 0 : _c.can_register);
    if (!server) {
        return React.createElement(ServerForm, { className: className, onSuccess: chooseServer });
    }
    if (!credentialSettings.settings) {
        return (React.createElement(Form, { className: className },
            React.createElement(NvidiaLogo, null),
            React.createElement(OmniverseLogo, null),
            credentialSettings.errors.length === 0 ? (React.createElement(FormSpinner, null)) : (React.createElement(React.Fragment, null,
                visibility.server && (React.createElement(ServerName, { title: server },
                    server,
                    readonly && !readonly.server && React.createElement(EditIcon, { onClick: resetServer }))),
                React.createElement(FormGroup, null,
                    React.createElement(FormErrorList, { errors: credentialSettings.errors })),
                React.createElement(ButtonGroup, null,
                    React.createElement(LoginButton, { onClick: retry }, "Retry"))))));
    }
    return (React.createElement(Form, { className: className },
        React.createElement(NvidiaLogo, null),
        React.createElement(OmniverseLogo, null),
        visibility.server && (React.createElement(ServerName, { title: server },
            server,
            readonly && !readonly.server && React.createElement(EditIcon, { title: "Edit server", onClick: resetServer }))),
        React.createElement(FormGroup, null,
            React.createElement(FormErrorList, { errors: errors }),
            React.createElement(FormErrorList, { errors: form.errors })),
        supportsCredentials && (React.createElement(React.Fragment, null,
            React.createElement(FormGroup, null,
                React.createElement(Input, { autoFocus: true, id: "username", name: "username", disabled: loading || form.loading || readonly.username, placeholder: "Username", value: username, onChange: setUsername })),
            React.createElement(FormGroup, null,
                React.createElement(Input, { id: "password", type: "password", name: "password", disabled: loading || form.loading, placeholder: "Password", value: password, onChange: setPassword })),
            React.createElement(ButtonGroup, null,
                React.createElement(LoginButton, { disabled: loading || form.loading, onClick: form.submit },
                    (loading || form.loading) && React.createElement(Spinner, null),
                    " Log in"),
                supportsRegistration && React.createElement(Link, { onClick: register }, "Create Account")))),
        ssoSettings.settings && ssoSettings.settings.length > 0 && credentialSettings.settings.is_ui_visible && (React.createElement(SSOSplitter, null, "or")),
        ssoSettings.settings && (React.createElement(SSOButtonGroup, { ssoSettings: ssoSettings.settings, loading: loading || redirecting, onClick: handleRedirect })),
        children));
};
var EditIcon = styled(Icon).attrs({
    icon: faPencilAlt,
    clickable: true,
    tabIndex: 0,
})(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: block;\n  margin: 0 auto;\n"], ["\n  display: block;\n  margin: 0 auto;\n"])));
var validateServer = function (server) {
    var portIndex = server.indexOf(":3009");
    if (portIndex !== -1) {
        server = server.substring(0, portIndex);
    }
    return server;
};
export default AuthForm;
var templateObject_1;
