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
import styled from "styled-components";
var Input = styled.input(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  display: block;\n  font-family: inherit;\n  font-size: 14px;\n  box-sizing: border-box;\n  width: 100%;\n  padding: 5px 15px;\n  border-radius: 3px;\n  border: none;\n  background: ", ";\n  color: #6e6e6e;\n  z-index: 1;\n\n  &::placeholder {\n    color: ", ";\n  }\n"], ["\n  display: block;\n  font-family: inherit;\n  font-size: 14px;\n  box-sizing: border-box;\n  width: 100%;\n  padding: 5px 15px;\n  border-radius: 3px;\n  border: none;\n  background: ", ";\n  color: #6e6e6e;\n  z-index: 1;\n\n  &::placeholder {\n    color: ", ";\n  }\n"])), function (_a) {
    var disabled = _a.disabled;
    return (disabled ? "#a5a5a5" : "#e0e0e0");
}, function (_a) {
    var disabled = _a.disabled;
    return (disabled ? "#909090" : "#bbb");
});
export default Input;
var templateObject_1;
