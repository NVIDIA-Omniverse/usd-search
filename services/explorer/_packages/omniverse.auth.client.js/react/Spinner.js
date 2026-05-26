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
import { faSpinner } from "@fortawesome/free-solid-svg-icons/faSpinner";
import styled from "styled-components";
import Icon from "./Icon";
var Spinner = styled(Icon).attrs(function () { return ({
    icon: faSpinner,
    "aria-busy": true,
    "aria-live": "polite",
    spin: true,
}); })(templateObject_1 || (templateObject_1 = __makeTemplateObject(["\n  cursor: default;\n"], ["\n  cursor: default;\n"])));
export default Spinner;
var templateObject_1;
