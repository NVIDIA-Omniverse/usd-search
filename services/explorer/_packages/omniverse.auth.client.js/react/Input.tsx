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

const Input = styled.input`
  display: block;
  font-family: inherit;
  font-size: 14px;
  box-sizing: border-box;
  width: 100%;
  padding: 5px 15px;
  border-radius: 3px;
  border: none;
  background: ${({ disabled }) => (disabled ? "#a5a5a5" : "#e0e0e0")};
  color: #6e6e6e;
  z-index: 1;

  &::placeholder {
    color: ${({ disabled }) => (disabled ? "#909090" : "#bbb")};
  }
`;

export default Input;
