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

import React, { useRef } from "react";
import styled from "styled-components";
import { AuthenticationResult } from "./AuthForm";
import Button from "./Button";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useCredentialRegistration from "./hooks/CredentialRegistration";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import Input from "./Input";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import ServerName from "./ServerName";
import Spinner from "./Spinner";

interface RegistrationFormProps {
  server: string;
  className?: string;
  loading?: boolean;
  errors?: string[];
  extras?: Record<string, string>;
  nonce?: string;
  onSubmit?(fields: RegistrationFormFields): Promise<AuthenticationResult>;
  onStart?(fields: RegistrationFormFields): boolean;
  onSuccess?(result: AuthenticationResult): void;
  onFail?(errors: string[]): void;
  onCancel(): void;
}

export interface RegistrationFormFields {
  username: string;
  password: string;
  confirmPassword: string;
  server: string;
  firstName: string;
  lastName: string;
  email: string;
  nonce?: string;
  extras?: Record<string, string>;
}

const RegistrationForm: React.FC<RegistrationFormProps> = ({
  server,
  className,
  loading,
  errors,
  extras,
  nonce,
  onSubmit,
  onStart,
  onSuccess,
  onFail,
  onCancel,
}) => {
  const [username, setUsername] = useInput("");
  const [password, setPassword] = useInput("");
  const [confirmPassword, setConfirmPassword] = useInput("");
  const [firstName, setFirstName] = useInput("");
  const [lastName, setLastName] = useInput("");
  const [email, setEmail] = useInput("");

  const emailRef = useRef<HTMLInputElement>(null);

  const register = useCredentialRegistration();
  const form = useForm<RegistrationFormFields, AuthenticationResult>({
    fields: {
      username,
      password,
      confirmPassword,
      server,
      firstName,
      lastName,
      email,
      nonce,
      extras
    },
    onSubmit: async (fields) => {
      const errors: string[] = [];
      if (!emailRef.current?.checkValidity()) {
          errors.push("Email is not valid.");
      }

      if (!fields.password) {
        errors.push("Password is empty.");
      }

      if (fields.password !== fields.confirmPassword) {
        errors.push("Passwords don't match.");
      }

      if (errors.length > 0) {
          return { errors };
      }

      const submit = onSubmit || register;
      return submit(fields);
    },
    onStart,
    onSuccess,
    onFail,
  });

  return (
    <Form className={className}>
      <NvidiaLogo />
      <OmniverseLogo />

      <ServerName title={server}>{server}</ServerName>

      <FormGroup>
        <FormErrorList errors={errors} />
        <FormErrorList errors={form.errors} />
      </FormGroup>

      <FormGroup>
        <Input
          autoFocus
          name={"username"}
          value={username}
          disabled={loading || form.loading}
          onChange={setUsername}
          placeholder={"Username"}
        />
      </FormGroup>

      <FormGroup>
        <Input
          name={"password"}
          type={"password"}
          value={password}
          disabled={loading || form.loading}
          onChange={setPassword}
          placeholder={"Type Password"}
        />
      </FormGroup>

      <FormGroup>
        <Input
          name={"confirmPassword"}
          type={"password"}
          value={confirmPassword}
          disabled={loading || form.loading}
          onChange={setConfirmPassword}
          placeholder={"Confirm Password"}
        />
      </FormGroup>

      <FormGroup>
        <Input
          name={"firstName"}
          value={firstName}
          disabled={loading || form.loading}
          onChange={setFirstName}
          placeholder={"First Name"}
        />
      </FormGroup>

      <FormGroup>
        <Input
          name={"lastName"}
          value={lastName}
          disabled={loading || form.loading}
          onChange={setLastName}
          placeholder={"Last Name"}
        />
      </FormGroup>

      <FormGroup>
        <Input
          name={"email"}
          type={"email"}
          value={email}
          disabled={loading || form.loading}
          onChange={setEmail}
          placeholder={"Email"}
          ref={emailRef as any}
          required
        />
      </FormGroup>

      <RegistrationButtonGroup>
        <Button disabled={loading || form.loading} onClick={form.submit}>
          {(loading || form.loading) && <Spinner />} Create
        </Button>

        <Button disabled={loading || form.loading} onClick={onCancel}>
          Cancel
        </Button>
      </RegistrationButtonGroup>
    </Form>
  );
};

const RegistrationButtonGroup = styled(ButtonGroup)`
  flex-direction: row;
  justify-content: space-between;
`;

export default RegistrationForm;
