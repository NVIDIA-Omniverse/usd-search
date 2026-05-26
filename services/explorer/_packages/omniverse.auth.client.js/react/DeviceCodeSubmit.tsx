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
import React, { useEffect, useState } from "react";
import { Redirect } from "react-router-dom";
import DeviceCodeStatus from "./DeviceCodeStatus";
import Form from "./Form";
import FormError from "./FormError";
import FormSpinner from "./FormSpinner";
import { useDeviceFlowSubmit } from "./hooks/DeviceFlow";
import useNucleusSession from "./hooks/NucleusSession";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";

export interface DeviceCodeSubmitProps {
  code: string;
}

const DeviceCodeSubmit: React.FC<DeviceCodeSubmitProps> = ({ code }) => {
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [error, setError] = useState("");

  const session = useNucleusSession();

  const submitUserCode = useDeviceFlowSubmit();
  useEffect(() => {
    submitUserCode({ code })
      .then((result) => setStatus(result.status))
      .catch((error) => setError(error.message || error.toString()))
      .finally(() => setLoading(false));
  }, [code, submitUserCode]);

  if (!session.established) {
    return <Redirect to={"/"} />;
  }

  return (
    <Form>
      <NvidiaLogo />
      <OmniverseLogo />
      <DeviceCodeSubmitBody loading={loading} status={status} error={error} />
    </Form>
  );
};

interface DeviceCodeSubmitState {
  loading: boolean;
  status: AuthStatus | null;
  error: string;
}

const DeviceCodeSubmitBody: React.FC<DeviceCodeSubmitState> = ({ loading, status, error }) => {
  if (loading) {
    return <FormSpinner />;
  }
  if (error) {
    return <FormError>{error}</FormError>;
  }
  return <DeviceCodeStatus status={status!} />;
};

export default DeviceCodeSubmit;
