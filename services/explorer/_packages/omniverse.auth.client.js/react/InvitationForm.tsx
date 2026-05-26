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

import React, { useMemo } from "react";
import styled from "styled-components";
import ButtonGroup from "./ButtonGroup";
import Form from "./Form";
import FormErrorList from "./FormErrorList";
import FormGroup from "./FormGroup";
import useCredentialSettings from "./hooks/CredentialSettings";
import useForm from "./hooks/Form";
import { useInput } from "./hooks/Input";
import useSSORedirect from "./hooks/SSORedirect";
import useSSOSettings from "./hooks/SSOSettings";
import { default as OmniverseInput } from "./Input";
import LoginButton from "./LoginButton";
import NvidiaLogo from "./NvidiaLogo";
import OmniverseLogo from "./OmniverseLogo";
import Spinner from "./Spinner";
import SSOButtonGroup from "./SSOButtonGroup";
import SSOSplitter from "./SSOSplitter";
import Headline from "./Headline";

export interface InvitationFormProps {
  username: string;
  server: string;
  ssoRedirectBackTo?: string;
  onSubmit(newPassword: string): Promise<void>;
}

interface InvitationFormFields {
  newPassword: string;
  confirmNewPassword: string;
}

const InvitationForm: React.FC<InvitationFormProps> = ({
  username,
  server,
  ssoRedirectBackTo = window.location.origin + "/sso",
  onSubmit,
}) => {
  const [newPassword, setNewPassword] = useInput("");
  const [confirmNewPassword, setConfirmNewPassword] = useInput("");

  const credentialSettings = useCredentialSettings(server);
  const ssoSettings = useSSOSettings(server);
  const redirect = useSSORedirect(server, ssoRedirectBackTo);

  const ssoAvailable = useMemo(
    () => Boolean(username.includes("@") && ssoSettings?.settings && ssoSettings.settings.length > 0),
    [username, ssoSettings]
  );
  const credentialsAvailable = useMemo(
    () => Boolean(!username.includes("@") && credentialSettings?.settings?.is_ui_visible),
    [username, credentialSettings]
  );

  const form = useForm({
    fields: {
      newPassword,
      confirmNewPassword,
    },
    onSubmit: submit,
  });

  async function submit({ newPassword, confirmNewPassword }: InvitationFormFields) {
    if (!newPassword) {
      throw new Error("You should specify a new password.");
    }

    if (newPassword !== confirmNewPassword) {
      throw new Error("Passwords don't match.");
    }

    return onSubmit(newPassword);
  }

  if (!credentialSettings || !ssoSettings) {
    return (
      <Form>
        <NvidiaLogo />
        <OmniverseLogo />
      </Form>
    );
  }

  return (
    <Form>
      <NvidiaLogo />
      <OmniverseLogo />

      {form.errors && (
        <FormGroup>
          <FormErrorList errors={form.errors} />
        </FormGroup>
      )}

      <Headline>
        Welcome to Omniverse! <br />
        Your username is: <br />"{username}" <br /> on <br /> <b>{server}</b>
      </Headline>

      <Caption credentialsAvailable={credentialsAvailable} ssoAvailable={ssoAvailable} />

      {credentialsAvailable && (
        <>
          <FormGroup>
            <OmniverseInput
              autoFocus
              type={"password"}
              placeholder={"Type Password"}
              name={"newPassword"}
              disabled={form.loading}
              value={newPassword}
              onChange={setNewPassword}
            />
          </FormGroup>

          <FormGroup>
            <OmniverseInput
              type={"password"}
              placeholder={"Confirm Password"}
              name={"confirmNewPassword"}
              disabled={form.loading}
              value={confirmNewPassword}
              onChange={setConfirmNewPassword}
            />
          </FormGroup>

          <ButtonGroup>
            <LoginButton name={"submit"} disabled={form.loading} onClick={form.submit}>
              {form.loading && <Spinner />}
              Log in
            </LoginButton>
          </ButtonGroup>
        </>
      )}

      {credentialsAvailable && ssoAvailable && <SSOSplitter>or</SSOSplitter>}
      {ssoAvailable && ssoSettings.settings && <SSOButtonGroup ssoSettings={ssoSettings.settings} onClick={redirect} />}
    </Form>
  );
};

const Caption: React.FC<{
  credentialsAvailable: boolean;
  ssoAvailable: boolean;
}> = ({ credentialsAvailable, ssoAvailable }) => {
  if (credentialsAvailable && ssoAvailable) {
    return <StyledCaption>Please continue by providing a new password or logging in with SSO.</StyledCaption>;
  }
  if (credentialsAvailable) {
    return <StyledCaption>Please continue by providing a new password.</StyledCaption>;
  }
  if (ssoAvailable) {
    return <StyledCaption>Please continue by logging in with SSO.</StyledCaption>;
  }
  return null;
};

const StyledCaption = styled.div`
  font-weight: 400;
  font-size: 11pt;
  position: relative;
  text-align: center;
  padding: 1em 0.5em;
  margin: 0 1em;
  border-top: 1px solid #bbbbbb;
  z-index: 1;
`;

export default InvitationForm;
