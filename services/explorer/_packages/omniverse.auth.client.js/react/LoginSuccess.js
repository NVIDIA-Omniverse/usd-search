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
import { faCheck } from "@fortawesome/free-solid-svg-icons/faCheck";
import React from "react";
import styled from "styled-components";
import Icon from "./Icon";
var LoginSuccess = function (_a) {
    var className = _a.className, children = _a.children;
    if (!children) {
        children = (React.createElement(React.Fragment, null,
            "You have successfully logged in. ",
            React.createElement("br", null),
            "You can continue to work in your application. ",
            React.createElement("br", null)));
    }
    return (React.createElement(Authenticated, { className: className },
        React.createElement(AuthenticatedIcon, { icon: faCheck }),
        children));
};
var Authenticated = styled.div(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  background: #e0e0e0;\n  color: #6e6e6e;\n  margin: 0 auto;\n  max-width: 450px;\n  text-align: center;\n"], ["\n  background: #e0e0e0;\n  color: #6e6e6e;\n  margin: 0 auto;\n  max-width: 450px;\n  text-align: center;\n"])));
var AuthenticatedIcon = styled(Icon)(templateObject_2 || (templateObject_2 = __makeTemplateObject(["\n  display: block;\n  margin: 0 auto;\n  text-align: center;\n  color: #71a376;\n  font-size: 24pt;\n  line-height: 48pt;\n"], ["\n  display: block;\n  margin: 0 auto;\n  text-align: center;\n  color: #71a376;\n  font-size: 24pt;\n  line-height: 48pt;\n"])));
export default LoginSuccess;
var templateObject_1, templateObject_2;
