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
import { faUser } from "@fortawesome/free-solid-svg-icons/faUser";
import jwtDecode from "jwt-decode";
import React from "react";
import styled from "styled-components";
import useRedirectURL from "./hooks/LoginRedirect";
import useNucleusSession from "./hooks/NucleusSession";
import Icon from "./Icon";
import NavLink from "./NavLink";
var Header = function () {
    var session = useNucleusSession();
    var logout = useRedirectURL({ redirect: "/logout" });
    if (!session.established) {
        return null;
    }
    return (React.createElement(StyledHeader, null,
        React.createElement(Username, { refreshToken: session.refreshToken }),
        React.createElement(NavLink, { to: logout }, "Log out")));
};
var Username = React.memo(function (_a) {
    var refreshToken = _a.refreshToken;
    var payload = jwtDecode(refreshToken);
    var username = payload.sub;
    return (React.createElement(StyledUsername, null,
        React.createElement(Icon, { icon: faUser }),
        username));
});
var StyledHeader = styled.header(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: flex;\n  padding: 1em;\n  gap: 2rem;\n"], ["\n  display: flex;\n  padding: 1em;\n  gap: 2rem;\n"])));
var StyledUsername = styled.div(templateObject_2 || (templateObject_2 = __makeTemplateObject(["\n  display: inline-flex;\n  align-items: center;\n  gap: 0.25em;\n  font-size: 9pt;\n  margin-left: auto;\n  color: #2d2d2d;\n"], ["\n  display: inline-flex;\n  align-items: center;\n  gap: 0.25em;\n  font-size: 9pt;\n  margin-left: auto;\n  color: #2d2d2d;\n"])));
export default Header;
var templateObject_1, templateObject_2;
