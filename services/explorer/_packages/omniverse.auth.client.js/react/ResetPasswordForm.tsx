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
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import Input from "./Input";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";

export interface ResetPasswordFormProps {
  payload: string;
  onSubmit(newPassword: string, payload: string): Promise<void>;
}

interface ResetPasswordFormFields {
  newPassword: string;
  confirmNewPassword: string;
}

const ResetPasswordForm: React.FC<ResetPasswordFormProps> = ({ payload, onSubmit }) => {
  const [newPassword, setNewPassword] = useInput("");
  const [confirmNewPassword, setConfirmNewPassword] = useInput("");

  const form = useForm({
    fields: {
      newPassword,
      confirmNewPassword
    },
    onSubmit: submit
  });

  async function submit({ newPassword, confirmNewPassword }: ResetPasswordFormFields) {
    if (!newPassword) {
      throw new Error("You should specify a new password.");
    }

    if (newPassword !== confirmNewPassword) {
      throw new Error("Passwords don't match.");
    }

    return onSubmit(newPassword, payload);
  }

  return (
    <Form>
      <NvidiaLogo/>
      <OmniverseLogo/>

      <FormGroup>{form.errors && <FormErrorList errors={form.errors}/>}</FormGroup>

      <FormGroup>
        <Input
          autoFocus
          type={"password"}
          placeholder={"New Password"}
          name={"newPassword"}
          disabled={form.loading}
          value={newPassword}
          onChange={setNewPassword}
        />
      </FormGroup>

      <FormGroup>
        <Input
          type={"password"}
          placeholder={"Confirm New Password"}
          name={"confirmNewPassword"}
          disabled={form.loading}
          value={confirmNewPassword}
          onChange={setConfirmNewPassword}
        />
      </FormGroup>

      <ButtonGroup>
        <LoginButton name={"submit"} disabled={form.loading} onClick={form.submit}>
          {form.loading && <Spinner/>}
          Reset password
        </LoginButton>
      </ButtonGroup>
    </Form>
  );
};

export default ResetPasswordForm;
