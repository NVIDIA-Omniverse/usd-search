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
var Button = styled.button(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  background: #e0e0e0;\n  color: #6e6e6e;\n  box-sizing: border-box;\n  height: 30px;\n  padding: 0 10px;\n  min-width: 100px;\n  border: 1px solid transparent;\n  border-radius: 2px;\n  box-shadow: 0 3px 5px -2px #222;\n  font-family: unset;\n  font-size: 11pt;\n  cursor: pointer;\n  outline: none;\n  line-height: 1;\n\n  &:not(&[disabled]):active {\n    box-shadow: inset 0 2px 5px -3px #222;\n    outline: none;\n  }\n\n  &[disabled] {\n    cursor: default;\n    filter: grayscale(80%) brightness(0.5);\n  }\n\n  & > svg.fa-spinner {\n    margin-right: 0.5em;\n  }\n"], ["\n  background: #e0e0e0;\n  color: #6e6e6e;\n  box-sizing: border-box;\n  height: 30px;\n  padding: 0 10px;\n  min-width: 100px;\n  border: 1px solid transparent;\n  border-radius: 2px;\n  box-shadow: 0 3px 5px -2px #222;\n  font-family: unset;\n  font-size: 11pt;\n  cursor: pointer;\n  outline: none;\n  line-height: 1;\n\n  &:not(&[disabled]):active {\n    box-shadow: inset 0 2px 5px -3px #222;\n    outline: none;\n  }\n\n  &[disabled] {\n    cursor: default;\n    filter: grayscale(80%) brightness(0.5);\n  }\n\n  & > svg.fa-spinner {\n    margin-right: 0.5em;\n  }\n"])));
export default Button;
var templateObject_1;
