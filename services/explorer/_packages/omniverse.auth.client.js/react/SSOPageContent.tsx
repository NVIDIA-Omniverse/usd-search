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

import { AuthStatus } from "@omniverse/auth/data";
import React from "react";
import { AuthenticationResult } from "./AuthForm";
import FormError from "./FormError";
import LoginSuccess from "./LoginSuccess";

export interface SSOPageContentProps {
  auth?: AuthenticationResult | null;
  error?: Error | null;
}

const SSOPageContent: React.FC<SSOPageContentProps> = ({ auth, error }) => {
  if (error) {
    return <FormError>{error.message ?? error.toString()}</FormError>;
  }

  if (!auth) {
    return <FormError>Service is not responding.</FormError>;
  }

  if (auth.errors && auth.errors.length) {
    return (
      <>
        {auth.errors.map((error) => (
          <FormError key={error}>{error}</FormError>
        ))}
      </>
    );
  }

  if (auth.status === AuthStatus.OK) {
    return <LoginSuccess />;
  }

  return <>{auth.status}</>;
};

export default SSOPageContent;
