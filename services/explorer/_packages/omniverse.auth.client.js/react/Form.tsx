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

import React, { useCallback } from "react";
import styled from "styled-components";

export interface FormProps extends React.HTMLAttributes<HTMLFormElement> {}

export const Form = ({ onSubmit, ...props }: FormProps) => {
  const submit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (onSubmit) {
        onSubmit(e);
      }
    },
    [onSubmit]
  );

  return <StyledForm {...props} onSubmit={submit} />;
};

const StyledForm = styled.form`
  position: relative;
  padding: 1rem;
  background: #2d2d2d;
  color: #e0e0e0;
  width: 420px;
  box-sizing: border-box;
  border-radius: 8px;
  margin: 0 auto;
`;

export default Form;
