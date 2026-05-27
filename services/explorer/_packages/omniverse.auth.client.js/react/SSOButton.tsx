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

import { SSOSettings } from "@omniverse/auth/data";
import React, { useCallback } from "react";
import styled from "styled-components";
import Button from "./Button";
import Spinner from "./Spinner";

export interface SSOButtonProps {
  loading?: boolean;
  setting: SSOSettings;
  onClick(setting: SSOSettings): void;
}

const SSOButton: React.FC<SSOButtonProps> = ({ loading = false, setting, onClick }) => {
  const redirect = useCallback(() => {
    onClick(setting);
  }, [setting, onClick]);

  return (
    <StyledSSOButton disabled={loading} onClick={redirect}>
      {loading ? <Spinner /> : setting.image && <StyledPicture src={setting.image} />}
      Log in with {setting.public_name}
    </StyledSSOButton>
  );
};

export const StyledSSOButton = styled(Button)`
  display: flex;
  justify-content: center;
  align-items: center;
  position: relative;
  background: #666;
  color: white;
  padding: 0 10px;
  border-color: #909090;
  margin: 0.25rem 0;
  box-sizing: border-box;

  & > svg.fa-spinner {
    margin-right: 10px;
  }
`;

const StyledPicture = styled.img`
  max-width: 100%;
  max-height: 100%;
  margin-right: 10px;
  cursor: pointer;
  width: 20px;
  height: 20px;
`;

export default SSOButton;
