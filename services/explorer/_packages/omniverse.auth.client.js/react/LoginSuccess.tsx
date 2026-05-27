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
import React from "react";
import styled from "styled-components";
import Icon from "./Icon";

interface LoginSuccessProps {
  className?: string;
}

const LoginSuccess: React.FC<LoginSuccessProps> = ({ className, children }) => {
  if (!children) {
    children = (
      <>
        You have successfully logged in. <br/>
        You can continue to work in your application. <br/>
      </>
    );
  }

  return (
    <Authenticated className={className}>
      <AuthenticatedIcon icon={faCheck} />
      {children}
    </Authenticated>
  );
};

const Authenticated = styled.div`
  background: #e0e0e0;
  color: #6e6e6e;
  margin: 0 auto;
  max-width: 450px;
  text-align: center;
`;

const AuthenticatedIcon = styled(Icon)`
  display: block;
  margin: 0 auto;
  text-align: center;
  color: #71a376;
  font-size: 24pt;
  line-height: 48pt;
`;

export default LoginSuccess;
