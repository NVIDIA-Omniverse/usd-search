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

const SSOSplitter = styled.div`
  text-align: center;
  text-transform: uppercase;
  font-size: 10pt;
  flex: 0 0 100%;
  margin: 1rem 0 0.75rem 0;
  position: relative;

  &:before {
    position: absolute;
    width: 50px;
    height: 50%;
    left: 15px;
    top: 0;
    bottom: 0;
    border-bottom: 1px solid #969696;
    content: " ";
  }

  &:after {
    position: absolute;
    width: 50px;
    height: 50%;
    right: 15px;
    top: 0;
    bottom: 0;
    border-bottom: 1px solid #969696;
    content: " ";
  }
`;

export default SSOSplitter;
