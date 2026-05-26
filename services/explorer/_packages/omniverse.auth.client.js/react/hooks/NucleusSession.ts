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

import { Tokens } from "@omniverse/auth";
import { AuthStatus } from "@omniverse/auth/data";
import cookie from "cookie";
import jwtDecode, { JwtPayload } from "jwt-decode";
import { useCallback, useEffect, useMemo, useState } from "react";
import connect from "../Connection";

interface NucleusSessionState {
  server: string;
  accessToken?: string;
  refreshToken: string;
}

type EstablishedNucleusSession = {
  established: true;
  server: string;
  accessToken?: string;
  refreshToken: string;
  getSession(): Promise<Required<NucleusSessionState> | null>;
  setSession(session: NucleusSessionState | null): void;
};

type AnonymousNucleusSession = {
  established: false;
  getSession(): Promise<Required<NucleusSessionState> | null>;
  setSession(session: NucleusSessionState | null): void;
};

export type NucleusSession = EstablishedNucleusSession | AnonymousNucleusSession;

export default function useNucleusSession(): NucleusSession {
  const [session, setSession] = useState<NucleusSessionState | null>(readNucleusSessionCookie);

  const writeSession = useCallback((session: NucleusSessionState | null) => {
    writeNucleusSessionCookie(session);

    const event = new CustomEvent("nucleus-session", { detail: session });
    window.dispatchEvent(event);

    setSession(session);
  }, []);

  useEffect(() => {
    function updateSession(event: Event) {
      const customEvent = event as CustomEvent<NucleusSessionState>;
      setSession(customEvent.detail);
    }

    window.addEventListener("nucleus-session", updateSession);
    return () => {
      window.removeEventListener("nucleus-session", updateSession);
    };
  });

  const refresh = useRefreshToken();
  const refreshSession = useCallback(async (): Promise<Required<NucleusSessionState> | null> => {
    if (!session || !session.refreshToken || !session.server) {
      return null;
    }

    const result = await refresh(session.refreshToken, session.server);
    writeSession(result);
    return result;
  }, [session, writeSession, refresh]);

  const getSession = useCallback(async (): Promise<Required<NucleusSessionState> | null> => {
    if (!session) {
      return null;
    }

    if (!session.accessToken) {
      return await refreshSession();
    }

    const payload = jwtDecode<JwtPayload>(session.accessToken);
    if (!payload.exp) {
      return session as Required<NucleusSessionState>;
    }

    const expiresAt = new Date(payload.exp * 1000);
    const willExpireInFiveSeconds = expiresAt && Date.now() + 5000 >= expiresAt.getTime();
    if (willExpireInFiveSeconds) {
      return await refreshSession();
    } else {
      return session as Required<NucleusSessionState>;
    }
  }, [session, refreshSession]);

  useEffect(() => {
    if (!session) {
      return;
    }

    if (!session.accessToken && session.refreshToken) {
      refreshSession().catch((error) => console.error(error));
    }
  }, [session, refreshSession, writeSession]);

  return useMemo(() => {
    const established = Boolean(session && session.refreshToken && session.server);
    if (established) {
      return {
        established: true,
        server: session!.server,
        accessToken: session!.accessToken,
        refreshToken: session!.refreshToken,
        setSession: writeSession,
        getSession,
      };
    } else {
      return {
        established: false,
        setSession: writeSession,
        getSession,
      };
    }
  }, [session, writeSession, getSession]);
}

export function useRefreshToken() {
  return useCallback(async (refreshToken: string, server: string): Promise<Required<NucleusSessionState> | null> => {
    console.debug("Refreshing Nucleus session...");

    let tokens: Tokens | null = null;
    try {
      tokens = await connect(server, Tokens);

      const result = await tokens.refresh({ refresh_token: refreshToken });
      if (result.status === AuthStatus.OK) {
        return { server, accessToken: result.access_token!, refreshToken: result.refresh_token! };
      } else if (result.status === AuthStatus.Expired) {
        return null;
      } else {
        throw new Error(result.status);
      }
    } finally {
      if (tokens) {
        await tokens.transport.close();
      }
    }
  }, []);
}

export function readNucleusSessionCookie(): NucleusSessionState | null {
  const cookies = cookie.parse(document.cookie);
  const accessToken = cookies["nucleus_token"] || undefined;
  const refreshToken = cookies["nucleus_refresh"];
  const server = cookies["nucleus"];
  if (refreshToken) {
    return {
      server,
      accessToken,
      refreshToken,
    };
  } else {
    return null;
  }
}

function writeToken(key: string, token: string): Date | undefined {
  const payload = jwtDecode<JwtPayload>(token);
  const expires = payload.exp ? new Date(payload.exp * 1000) : undefined;
  document.cookie = cookie.serialize(key, token, { path: "/", expires });
  return expires;
}

function deleteCookie(key: string): void {
  document.cookie = cookie.serialize(key, "", { path: "/", maxAge: 0 });
}
export function writeNucleusSessionCookie(session: NucleusSessionState | null) {
  if (session) {
    const accessExpiration = writeToken("nucleus_token", session.accessToken!);
    console.debug(`Set Nucleus access token, expire at ${accessExpiration}.`);

    const refreshExpiration = writeToken("nucleus_refresh", session.refreshToken);
    console.debug(`Set Nucleus refresh token, expire at ${refreshExpiration}.`);

    document.cookie = cookie.serialize("nucleus", session.server, { path: "/", expires: refreshExpiration });
    console.debug(`Set Nucleus server: ${session.server}`);
  } else {
    console.debug("Delete Nucleus session.");
    deleteCookie("nucleus_token");
    deleteCookie("nucleus_refresh");
    deleteCookie("nucleus");
  }
}
