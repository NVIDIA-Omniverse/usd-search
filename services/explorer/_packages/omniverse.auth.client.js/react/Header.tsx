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

import { faUser } from "@fortawesome/free-solid-svg-icons/faUser";
import jwtDecode, { JwtPayload } from "jwt-decode";
import React from "react";
import styled from "styled-components";
import useRedirectURL from "./hooks/LoginRedirect";
import useNucleusSession from "./hooks/NucleusSession";
import Icon from "./Icon";
import NavLink from "./NavLink";

const Header: React.FC = () => {
  const session = useNucleusSession();
  const logout = useRedirectURL({ redirect: "/logout" });

  if (!session.established) {
    return null;
  }

  return (
    <StyledHeader>
      <Username refreshToken={session.refreshToken} />
      <NavLink to={logout}>Log out</NavLink>
    </StyledHeader>
  );
};

const Username: React.FC<{ refreshToken: string }> = React.memo(({ refreshToken }) => {
  const payload = jwtDecode<JwtPayload>(refreshToken);
  const username = payload.sub;
  return (
    <StyledUsername>
      <Icon icon={faUser} />
      {username}
    </StyledUsername>
  );
});

const StyledHeader = styled.header`
  display: flex;
  padding: 1em;
  gap: 2rem;
`;

const StyledUsername = styled.div`
  display: inline-flex;
  align-items: center;
  gap: 0.25em;
  font-size: 9pt;
  margin-left: auto;
  color: #2d2d2d;
`;

export default Header;
