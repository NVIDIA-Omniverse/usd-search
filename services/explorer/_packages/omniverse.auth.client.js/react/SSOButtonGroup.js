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
import React from "react";
import styled from "styled-components";
import SSOButton from "./SSOButton";
var SSOButtonGroup = function (_a) {
    var _b = _a.loading, loading = _b === void 0 ? false : _b, ssoSettings = _a.ssoSettings, onClick = _a.onClick;
    return ssoSettings && ssoSettings.length > 0 ? (React.createElement(SSOSettingList, null, ssoSettings.map(function (setting) { return (React.createElement(SSOButton, { key: setting.type, setting: setting, loading: loading, onClick: onClick })); }))) : null;
};
var SSOSettingList = styled.div(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: flex;\n  justify-content: space-around;\n  flex-direction: column;\n  margin: 5px 15px;\n"], ["\n  display: flex;\n  justify-content: space-around;\n  flex-direction: column;\n  margin: 5px 15px;\n"])));
export default SSOButtonGroup;
var templateObject_1;
