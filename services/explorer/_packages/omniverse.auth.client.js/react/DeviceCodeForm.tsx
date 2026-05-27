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

import { AuthStatus, DeviceSubmit } from "@omniverse/auth/data";
import React, { useState } from "react";
import CodeInput from "react-code-input";
import { Redirect } from "react-router-dom";
import { AuthenticationResult } from "./AuthForm";
import ButtonGroup from "./ButtonGroup";
import DeviceCodeStatus from "./DeviceCodeStatus";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import Headline from "./Headline";
import { useDeviceFlowSubmit } from "./hooks/DeviceFlow";
import useForm from "./hooks/Form";
import useNucleusSession from "./hooks/NucleusSession";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";
import styled from "styled-components";

export interface DeviceCodeFormProps {
  initial?: Partial<DeviceCodeFormFields>;
  onStart?(fields: DeviceCodeFormFields): boolean;
  onSubmit?(fields: DeviceCodeFormFields): Promise<AuthenticationResult>;
  onSuccess?(): void;
  onFail?(errors: string[]): void;
}

interface DeviceCodeFormFields {
  code: string;
}

const DeviceCodeForm: React.FC<DeviceCodeFormProps> = ({ initial = {}, onStart, onSubmit, onSuccess, onFail }) => {
  const [code, setCode] = useState<string>(initial.code || "");
  const submitUserCode = useDeviceFlowSubmit();

  const form = useForm<DeviceCodeFormFields, DeviceSubmit>({
    fields: {
      code,
    },
    onStart,
    onSubmit: onSubmit || submitUserCode,
    onSuccess,
    onFail,
  });

  const session = useNucleusSession();
  if (!session.established) {
    return <Redirect to={"/"} />;
  }

  return (
    <StyledDeviceCodeForm>
      <NvidiaLogo />
      <OmniverseLogo />

      <FormErrorList errors={form.errors} />

      {form.result?.status !== AuthStatus.OK && (
        <Headline>
          Please enter the verification code to log in. <br />({session.server})
        </Headline>
      )}

      {form.result && <DeviceCodeStatus status={form.result.status} />}

      {form.result?.status !== AuthStatus.OK && (
        <>
          <CodeInputGroup>
            <CodeInput
              name={"code"}
              autoFocus
              inputMode={"verbatim"}
              inputStyle={inputStyle}
              forceUppercase
              fields={8}
              type={"text"}
              value={code}
              disabled={form.loading}
              onChange={setCode}
            />
          </CodeInputGroup>

          <ButtonGroup>
            <LoginButton name={"submit"} disabled={form.loading} onClick={form.submit}>
              {form.loading && <Spinner />}
              Verify
            </LoginButton>
          </ButtonGroup>
        </>
      )}
    </StyledDeviceCodeForm>
  );
};

const StyledDeviceCodeForm = styled(Form)`
  width: 475px;
`;

const CodeInputGroup = styled(FormGroup)`
  display: flex;
  justify-content: center;
`;

const inputStyle: React.CSSProperties = {
  appearance: "textfield",
  borderRadius: "6px",
  border: "1px solid lightgrey",
  boxShadow: "rgba(0, 0, 0, 0.1) 0px 0px 10px 0px",
  margin: "4px",
  width: "42px",
  height: "42px",
  fontSize: "24px",
  fontFamily: "inherit",
  boxSizing: "border-box",
  color: "black",
  backgroundColor: "white",
  overflow: "visible",
  textAlign: "center"
};

export default DeviceCodeForm;
