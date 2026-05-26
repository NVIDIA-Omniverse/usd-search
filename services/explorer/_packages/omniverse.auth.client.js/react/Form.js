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
import React, { useCallback } from "react";
import styled from "styled-components";
export var Form = function (_a) {
    var onSubmit = _a.onSubmit, props = __rest(_a, ["onSubmit"]);
    var submit = useCallback(function (e) {
        e.preventDefault();
        if (onSubmit) {
            onSubmit(e);
        }
    }, [onSubmit]);
    return React.createElement(StyledForm, __assign({}, props, { onSubmit: submit }));
};
var StyledForm = styled.form(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  position: relative;\n  padding: 1rem;\n  background: #2d2d2d;\n  color: #e0e0e0;\n  width: 420px;\n  box-sizing: border-box;\n  border-radius: 8px;\n  margin: 0 auto;\n"], ["\n  position: relative;\n  padding: 1rem;\n  background: #2d2d2d;\n  color: #e0e0e0;\n  width: 420px;\n  box-sizing: border-box;\n  border-radius: 8px;\n  margin: 0 auto;\n"])));
export default Form;
var templateObject_1;
