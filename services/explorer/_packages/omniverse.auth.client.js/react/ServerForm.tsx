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
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useCredentialServerCheck from "./hooks/CredentialServerCheck";
import useForm, { FormErrors } from "./hooks/Form";
import { useInput } from "./hooks/Input";
import Input from "./Input";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";

export interface ServerFormProps {
  className?: string;
  loading?: boolean;
  errors?: string[];
  onStart?(fields: ServerFormFields): boolean;
  onSubmit?(fields: ServerFormFields): Promise<ServerFormFields>;
  onSuccess(result: ServerFormFields): void;
  onFail?(errors: string[]): void;
}

export interface ServerFormFields {
  server: string;
}

export type ServerFormResult = ServerFormFields & FormErrors;

const ServerForm: React.FC<ServerFormProps> = ({
  className,
  loading,
  errors,
  onStart,
  onSubmit,
  onSuccess,
  onFail,
}) => {
  const [server, setServer] = useInput("");

  const check = useCredentialServerCheck();
  const connect = useCallback(
    async ({ server }: ServerFormFields): Promise<ServerFormResult> => {
      const connection = await check(server);
      if (connection.ok) {
        return { server: connection.server };
      }
      return { server: connection.server, errors: connection.errors };
    },
    [check]
  );

  const form = useForm<ServerFormFields, ServerFormResult>({
    fields: {
      server,
    },
    onStart,
    onSubmit: onSubmit || connect,
    onSuccess,
    onFail,
  });

  return (
    <Form className={className}>
      <NvidiaLogo />
      <OmniverseLogo />

      <FormGroup>
        <FormErrorList errors={form.errors} />
        <FormErrorList errors={errors} />
      </FormGroup>

      <FormGroup>
        <Input autoFocus name={"server"} placeholder={"Type Server Name"} value={server} onChange={setServer} />
      </FormGroup>

      <ButtonGroup>
        <LoginButton disabled={loading || form.loading} onClick={form.submit}>
          {(loading || form.loading) && <Spinner />} Next
        </LoginButton>
      </ButtonGroup>
    </Form>
  );
};

export default ServerForm;
