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
import React, { useCallback } from "react";
import styled from "styled-components";
import Button from "./Button";
import Spinner from "./Spinner";
var SSOButton = function (_a) {
    var _b = _a.loading, loading = _b === void 0 ? false : _b, setting = _a.setting, onClick = _a.onClick;
    var redirect = useCallback(function () {
        onClick(setting);
    }, [setting, onClick]);
    return (React.createElement(StyledSSOButton, { disabled: loading, onClick: redirect },
        loading ? React.createElement(Spinner, null) : setting.image && React.createElement(StyledPicture, { src: setting.image }),
        "Log in with ",
        setting.public_name));
};
export var StyledSSOButton = styled(Button)(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: flex;\n  justify-content: center;\n  align-items: center;\n  position: relative;\n  background: #666;\n  color: white;\n  padding: 0 10px;\n  border-color: #909090;\n  margin: 0.25rem 0;\n  box-sizing: border-box;\n\n  & > svg.fa-spinner {\n    margin-right: 10px;\n  }\n"], ["\n  display: flex;\n  justify-content: center;\n  align-items: center;\n  position: relative;\n  background: #666;\n  color: white;\n  padding: 0 10px;\n  border-color: #909090;\n  margin: 0.25rem 0;\n  box-sizing: border-box;\n\n  & > svg.fa-spinner {\n    margin-right: 10px;\n  }\n"])));
var StyledPicture = styled.img(templateObject_2 || (templateObject_2 = __makeTemplateObject(["\n  max-width: 100%;\n  max-height: 100%;\n  margin-right: 10px;\n  cursor: pointer;\n  width: 20px;\n  height: 20px;\n"], ["\n  max-width: 100%;\n  max-height: 100%;\n  margin-right: 10px;\n  cursor: pointer;\n  width: 20px;\n  height: 20px;\n"])));
export default SSOButton;
var templateObject_1, templateObject_2;
