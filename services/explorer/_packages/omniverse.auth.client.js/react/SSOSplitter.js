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
var SSOSplitter = styled.div(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  text-align: center;\n  text-transform: uppercase;\n  font-size: 10pt;\n  flex: 0 0 100%;\n  margin: 1rem 0 0.75rem 0;\n  position: relative;\n\n  &:before {\n    position: absolute;\n    width: 50px;\n    height: 50%;\n    left: 15px;\n    top: 0;\n    bottom: 0;\n    border-bottom: 1px solid #969696;\n    content: \" \";\n  }\n\n  &:after {\n    position: absolute;\n    width: 50px;\n    height: 50%;\n    right: 15px;\n    top: 0;\n    bottom: 0;\n    border-bottom: 1px solid #969696;\n    content: \" \";\n  }\n"], ["\n  text-align: center;\n  text-transform: uppercase;\n  font-size: 10pt;\n  flex: 0 0 100%;\n  margin: 1rem 0 0.75rem 0;\n  position: relative;\n\n  &:before {\n    position: absolute;\n    width: 50px;\n    height: 50%;\n    left: 15px;\n    top: 0;\n    bottom: 0;\n    border-bottom: 1px solid #969696;\n    content: \" \";\n  }\n\n  &:after {\n    position: absolute;\n    width: 50px;\n    height: 50%;\n    right: 15px;\n    top: 0;\n    bottom: 0;\n    border-bottom: 1px solid #969696;\n    content: \" \";\n  }\n"])));
export default SSOSplitter;
var templateObject_1;
