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

import { FontAwesomeIcon, FontAwesomeIconProps } from "@fortawesome/react-fontawesome";
import React from "react";
import styled from "styled-components";

export interface IconProps extends FontAwesomeIconProps {
  clickable?: boolean;
  disabled?: boolean;
}

export type PredefinedIconProps = Omit<IconProps, "icon">;

/**
 * Icons from Font Awesome.
 * https://fontawesome.com/icons?d=gallery
 */
const Icon: React.FC<IconProps> = React.forwardRef<HTMLElement, IconProps>(
  ({ clickable: $clickable = false, disabled: $disabled = false, ...props }, ref) => {
    return (
      <StyledIcon
        forwardedRef={ref as any}
        clickable={$clickable}
        disabled={$disabled}
        aria-hidden={$clickable ? "false" : "true"}
        fixedWidth={true}
        {...props}
      />
    );
  }
);
Icon.displayName = "Icon";

export const StyledIcon = styled(({ clickable, disabled, ...props }: IconProps) => <FontAwesomeIcon {...props} />)`
  display: inline-block;
  cursor: ${({ clickable, disabled }) => (clickable && !disabled ? "pointer" : "unset")};
  pointer-events: ${({ disabled }) => (disabled ? "none" : "all")};
  user-select: none;
`;

export default Icon;
