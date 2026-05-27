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

import styled from "styled-components";

const Button = styled.button`
  background: #e0e0e0;
  color: #6e6e6e;
  box-sizing: border-box;
  height: 30px;
  padding: 0 10px;
  min-width: 100px;
  border: 1px solid transparent;
  border-radius: 2px;
  box-shadow: 0 3px 5px -2px #222;
  font-family: unset;
  font-size: 11pt;
  cursor: pointer;
  outline: none;
  line-height: 1;

  &:not(&[disabled]):active {
    box-shadow: inset 0 2px 5px -3px #222;
    outline: none;
  }

  &[disabled] {
    cursor: default;
    filter: grayscale(80%) brightness(0.5);
  }

  & > svg.fa-spinner {
    margin-right: 0.5em;
  }
`;

export default Button;
