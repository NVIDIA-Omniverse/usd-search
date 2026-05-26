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
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import React from "react";
import styled from "styled-components";
/**
 * Icons from Font Awesome.
 * https://fontawesome.com/icons?d=gallery
 */
var Icon = React.forwardRef(function (_a, ref) {
    var _b = _a.clickable, $clickable = _b === void 0 ? false : _b, _c = _a.disabled, $disabled = _c === void 0 ? false : _c, props = __rest(_a, ["clickable", "disabled"]);
    return (React.createElement(StyledIcon, __assign({ forwardedRef: ref, clickable: $clickable, disabled: $disabled, "aria-hidden": $clickable ? "false" : "true", fixedWidth: true }, props)));
});
Icon.displayName = "Icon";
export var StyledIcon = styled(function (_a) {
    var clickable = _a.clickable, disabled = _a.disabled, props = __rest(_a, ["clickable", "disabled"]);
    return React.createElement(FontAwesomeIcon, __assign({}, props));
})(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: inline-block;\n  cursor: ", ";\n  pointer-events: ", ";\n  user-select: none;\n"], ["\n  display: inline-block;\n  cursor: ", ";\n  pointer-events: ", ";\n  user-select: none;\n"])), function (_a) {
    var clickable = _a.clickable, disabled = _a.disabled;
    return (clickable && !disabled ? "pointer" : "unset");
}, function (_a) {
    var disabled = _a.disabled;
    return (disabled ? "none" : "all");
});
export default Icon;
var templateObject_1;
