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

import { faCheck } from "@fortawesome/free-solid-svg-icons/faCheck";
import { faExclamationCircle } from "@fortawesome/free-solid-svg-icons/faExclamationCircle";
import { AuthStatus } from "@omniverse/auth/data";
import React from "react";
import styled from "styled-components";
import useRedirectURL from "./hooks/LoginRedirect";
import Icon from "./Icon";
import NavLink from "./NavLink";

export interface DeviceCodeStatusProps {
  status: AuthStatus;
}

const DeviceCodeStatus: React.FC<DeviceCodeStatusProps> = ({ status }) => {
  const loginRedirect = useRedirectURL();
  if (status === AuthStatus.OK) {
    return (
      <StyledDeviceCodeStatus>
        <DeviceCodeStatusIcon icon={faCheck} type={"success"} />
        <DeviceCodeStatusText>
          You have successfully logged in. <br />
          You can continue to work in your application.
        </DeviceCodeStatusText>
      </StyledDeviceCodeStatus>
    );
  } else if (status === AuthStatus.Expired || status === AuthStatus.InvalidToken) {
    return (
      <StyledDeviceCodeStatus>
        <DeviceCodeStatusIcon icon={faExclamationCircle} type={"error"} />
        <DeviceCodeStatusText>
          Your session has expired. <br />
          Please <NavLink to={loginRedirect}>log in</NavLink> again.
        </DeviceCodeStatusText>
      </StyledDeviceCodeStatus>
    );
  } else if (status === AuthStatus.NotFound) {
    return (
      <StyledDeviceCodeStatus>
        <DeviceCodeStatusIcon icon={faExclamationCircle} type={"error"} />
        <DeviceCodeStatusText>
          This user code is not found or expired. <br />
          Please try to authenticate in the application again.
        </DeviceCodeStatusText>
      </StyledDeviceCodeStatus>
    );
  } else if (status === AuthStatus.Disabled) {
    return (
      <StyledDeviceCodeStatus>
        <DeviceCodeStatusIcon icon={faExclamationCircle} type={"error"} />
        <DeviceCodeStatusText>Your account has been disabled.</DeviceCodeStatusText>
      </StyledDeviceCodeStatus>
    );
  } else {
    return (
      <StyledDeviceCodeStatus>
        <DeviceCodeStatusIcon icon={faExclamationCircle} type={"error"} />
        <DeviceCodeStatusText>Unknown error, please try again later ({status}).</DeviceCodeStatusText>
      </StyledDeviceCodeStatus>
    );
  }
};

const StyledDeviceCodeStatus = styled.div`
  display: flex;
  gap: 0.5em;
  padding: 0 15px;
`;

const DeviceCodeStatusIcon = styled(Icon)<{ type: "success" | "error" }>`
  font-size: 18pt;
  margin-top: 5px;
  color: ${({ type }) => (type === "success" ? "#76b900" : "#d46a6a")};
`;

const DeviceCodeStatusText = styled.div`
  font-size: 10pt;
`;

export default DeviceCodeStatus;
