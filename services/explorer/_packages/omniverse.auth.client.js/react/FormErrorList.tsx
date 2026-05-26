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

import React from "react";
import styled from "styled-components";
import FormError from "./FormError";

export interface FormErrorListProps {
  errors?: string[];
}

export const FormErrorList: React.FC<FormErrorListProps> = ({
  errors = [],
  ...props
}) => {
  if (!errors || !errors.length) {
    return null;
  }

  return (
    <StyledFormErrorList {...props} as={"ul"}>
      {errors.map((error, index) => (
        <FormErrorListItem key={index}>{error}</FormErrorListItem>
      ))}
    </StyledFormErrorList>
  );
};

const StyledFormErrorList = styled(FormError)`
  list-style: none;
`;

const FormErrorListItem = styled.li``;

export default FormErrorList;
