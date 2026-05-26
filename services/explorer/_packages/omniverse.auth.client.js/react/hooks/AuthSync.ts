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

import { useCallback, useState } from "react";
import { useHistory, useLocation } from "react-router-dom";
import { AuthenticationResult } from "../AuthForm";
import useNucleusSession from "./NucleusSession";

export default function useAuthSync() {
  const [result, setResult] = useState<AuthenticationResult | null>();
  const location = useLocation();
  const search = new URLSearchParams(location.search);
  const redirectURL = decodeURI(search.get("redirect") || "");
  const history = useHistory();

  const { setSession } = useNucleusSession();
  const sync = useCallback(
    async (auth: AuthenticationResult) => {
      setSession({ server: auth.server!, accessToken: auth.accessToken!, refreshToken: auth.refreshToken! });

      const redirectTo = (auth.extras && auth.extras.redirect) || redirectURL;
      const nonce = auth.nonce;
      if (redirectTo && !nonce) {
        // `nonce` argument is only used by new clients that
        // don't need to run an HTTP server for receiving authentication results.
        await sendAuth(redirectTo, auth);
      }
      setResult(auth);

      const navigateURL = auth.extras && auth.extras.navigate;
      if (navigateURL) {
        if (navigateURL.startsWith("http")) {
          window.location.href = navigateURL;
        } else {
          history.push(navigateURL);
        }
      }
    },
    [redirectURL, setSession, history]
  );

  return {
    redirectURL,
    result,
    sync,
  };
}

async function sendAuth(url: string, auth: AuthenticationResult): Promise<void> {
  const { extras, ...body } = auth;
  let response;
  try {
    response = await fetch(url, {
      body: JSON.stringify(body),
      method: "POST",
    });
  } catch (error) {
    console.error(error);
    throw new Error(
      "Unable to send results back to the application that initiated the authentication. " +
        "This error message is expected if your client was released prior to year 2021."
    );
  }

  if (!response.ok) {
    throw new Error(
      "Unable to send results back to the application that initiated the authentication. " +
        "This error message is expected if your client was released prior to year 2021."
    );
  }
}
