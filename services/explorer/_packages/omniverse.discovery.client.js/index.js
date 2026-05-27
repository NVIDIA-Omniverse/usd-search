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

import { ClientFactory } from "@omniverse/idl/connection/transport";
import WebSocketClient from "@omniverse/idl/connection/transport/websocket";
import { DiscoverySearch as DiscoverySearchClient } from "@omniverse/discovery/client";
import {
  InterfaceCapabilities,
  InterfaceName,
  InterfaceOrigin,
} from "@omniverse/idl/schema";

// We will allow insecure contexts in a few cases:
// 1) If we're in Node environment
// 2) If we are on an HTTPS site, we cannot mix content with http:/ws: so don't even try.
// 3) We are on localhost which is special cased to allow mixed content
const SUPPORTS_INSECURE_CONTEXT =
  typeof window === "undefined" ||
  !window ||
  !window.location ||
  window.location.protocol !== "https:" ||
  window.location.hostname === "localhost" ||
  window.location.hostname === "127.0.0.1";

export default class DiscoverySearch {
  constructor(uri, { timeout, secure } = {}) {
    this.uri = uri;

    if (typeof timeout === "undefined") {
      // Firefox does not support parallel WebSocket connections to the same host,
      // therefore we have to drastically increase the default timeout
      // to let the library sequentially check which deployment is currently available.
      if (typeof navigator === "undefined") {
        timeout = 5000;
      } else {
        timeout = navigator.userAgent.match(/Firefox\//i) ? 30000 : 5000;
      }
    }
    this.timeout = timeout;
    this.secure = secure;
    this._ws = null;
  }

  find = async (
    clientType,
    meta,
    supportedTransport,
    capabilities,
    accessToken
  ) => {
    if (!supportedTransport) {
      supportedTransport = ClientFactory.getSupported();
    }

    const discovery = await this._connect(accessToken);
    const origin = clientType[InterfaceOrigin];
    const interfaceName = clientType[InterfaceName];

    if (!capabilities) {
      capabilities = clientType[InterfaceCapabilities];
    }

    let response;
    try {
      response = await discovery.find({
        query: {
          service_interface: {
            origin,
            name: interfaceName,
            capabilities,
          },
          supported_transport: supportedTransport,
          meta,
        },
      });
    } catch (error) {
      console.error(error);
      throw new DiscoveryError(
        `Failed to communicate with the discovery service ${this.uri}.`
      );
    }

    if (!response.found) {
      throw new DiscoveryError(
        `Interface "${interfaceName}" from "${origin}" has not been found.`
      );
    }

    const clientTransport = ClientFactory.create({
      ...response.transport,
      accessToken,
    });
    clientTransport.once("error", () => clientTransport.close());

    try {
      await clientTransport.prepare();
    } catch (error) {
      console.error(error);
      throw new DiscoveryError(
        `Failed to establish a connection with ${interfaceName} interface.`
      );
    }
    const instance = new clientType(clientTransport);
    if (response.service_interface?.capabilities) {
      instance[InterfaceCapabilities] = response.service_interface.capabilities;
    }

    if (response.meta) {
      instance[ServiceMeta] = response.meta;
    }
    return instance;
  };

  close = () => {
    if (this._ws) {
      this._ws.close();
      this._ws = null;
    }
  };

  _connect = async (accessToken) => {
    if (!this._ws) {
      await this._establish(accessToken);
    }
    return new DiscoverySearchClient(this._ws);
  };

  _establish = createPromiseSingleton(async (accessToken) => {
    const ws = await connect(this.uri, {
      timeout: this.timeout,
      secure: this.secure,
      accessToken,
    });
    ws.once("close", () => {
      if (this._ws === ws) {
        this._ws = null;
      }
      this._establish.invalidate();
    });

    this._ws = ws;
  });
}

function ensureWebsocketCloses(wsPromise) {
  return wsPromise.then((ws) => {
    // The createXBasedClient will return undefined if there is some error establishing the websocket
    if (ws && ws.close) {
      ws.close();
    }
  });
}

export async function connect(
  uri,
  { timeout = 5000, secure = !SUPPORTS_INSECURE_CONTEXT, accessToken } = {}
) {
  const url = createURL(uri);
  const tasks = [];

  // The priority order of websockets we wish to use is `wss`, `ws`, `port` so we append
  // them to our task array in priority order as appropriate for the environment.

  if (!["localhost", "127.0.0.1", "::1"].includes(url.hostname)) {
    tasks.push(testPathBasedClient(uri, "wss:", accessToken));

    if (!secure) {
      tasks.push(testPathBasedClient(uri, "ws:", accessToken));
    }
  }

  // This is the only approach used in workstation mode, but it is the lowest priority approach.
  if (!secure) {
    tasks.push(testPortBasedClient(uri, accessToken));
  }

  // Since all websocket connection promises are run in parallel we can share
  // one global timeout to use in our `Promise.race` checks to find the first websocket
  // to resolve within the timeout window.
  const timeoutTask = wait(timeout);
  let ws;

  // We want to use the websockets in priority order, so find the
  // first one that works and use that.
  for (const task of tasks) {
    // We want to use the websockets in priority order, so if a previous
    // higher priority websocket resolved, then we want to close (but not await)
    // our connection if/when it does resolve.
    if (ws) {
      ensureWebsocketCloses(task);
    } else {
      ws = await Promise.race([task, timeoutTask]);

      // If this task was not resolved before the timeout ensure we clean
      // it up as well if it ever resolves.
      if (!ws) {
        ensureWebsocketCloses(task);
      }
    }
  }

  if (!ws) {
    throw new DiscoveryError(
      `Failed to connect to the discovery service: ${uri}`
    );
  }

  return ws;
}

export async function testPathBasedClient(uri, protocol = "wss:", accessToken) {
  if (!uri.endsWith("/")) {
    uri += "/";
  }

  const url = createPathBasedURL(
    uri,
    protocol === "wss:" ? "https:" : "http:",
    accessToken
  );
  url.pathname += "/healthcheck";

  try {
    const response = await fetch(url);
    // HTTP426 - Update Required, means that the server requires a WebSocket connection
    if (response.status === 426 || response.ok) {
      console.info(
        `Found the (${protocol}) path-based deployment via HTTP for ${url}.`
      );
      return createPathBasedClient(uri, protocol, accessToken);
    }
  } catch {
    return false;
  }
}

/**
 * Connects to the discovery service using path-based routing.
 * @param {string} uri
 * @param {string} protocol Specifies the default protocol used to create a connection if it's missing in the uri.
 * @param {string} [accessToken]
 */
export async function createPathBasedClient(
  uri,
  protocol = "wss:",
  accessToken
) {
  const url = createPathBasedURL(uri, protocol, accessToken);
  try {
    const ws = new WebSocketClient({ uri: url.toString() });
    ws.once("error", () => ws.close());

    await ws.prepare();
    return ws;
  } catch (err) {
    console.debug(
      `Failed to connect to the discovery service using path-based routing: (${url}): `,
      err
    );
  }
}

export async function testPortBasedClient(uri, accessToken) {
  if (!uri.endsWith("/")) {
    uri += "/";
  }

  const url = createPortBasedURL(uri, "http:", accessToken);
  url.pathname = "/healthcheck";

  try {
    const response = await fetch(url);
    // HTTP426 - Update Required, means that the server requires a WebSocket connection
    if (response.status === 426 || response.ok) {
      console.info(`Found the port-based deployment via HTTP for ${url}.`);
      return createPortBasedClient(uri, accessToken);
    }
  } catch {
    return createPortBasedClient(uri, accessToken);
  }
}

/**
 * Connects to the discovery service using port-based routing.
 * @param {string} uri
 * @param {string} [accessToken]
 */
export async function createPortBasedClient(uri, accessToken) {
  const url = createPortBasedURL(uri, "ws:", accessToken);
  try {
    const ws = new WebSocketClient({ uri: url.toString() });
    ws.once("error", () => ws.close());

    await ws.prepare();
    return ws;
  } catch (err) {
    console.debug(
      `Failed to connect to the discovery service using port-based routing: (${url}): `,
      err
    );
  }
}

function createURL(value, { defaultProtocol = "ws:" } = {}) {
  const serverPattern = /^([\w\d\-_.]+)(:(\d+))?(\/[\w\d-_.]+)*\/?$/;
  if (serverPattern.test(value)) {
    return new URL(`${defaultProtocol}//${value}`);
  }
  return new URL(value);
}

/**
 * Creates a URL instance for path-based deployment using the specified hostname and protocol.
 * Path-based deployments include `/omni/discovery` pathname in the URL.
 * @param uri
 * @param protocol
 * @param [accessToken]
 * @returns {URL}
 */
function createPathBasedURL(uri, protocol, accessToken) {
  const url = createURL(uri, { defaultProtocol: protocol });
  if (!url.pathname.endsWith("/")) {
    url.pathname += "/";
  }

  url.pathname += endpoint;
  if (accessToken) {
    url.searchParams.set("access_token", accessToken);
  }
  return url;
}

/**
 * Creates a URL instance for port-based deployment using the specified hostname and protocol.
 * @param uri
 * @param protocol
 * @param accessToken
 * @returns {URL}
 */
function createPortBasedURL(uri, protocol = "ws:", accessToken) {
  const url = createURL(uri, { defaultProtocol: protocol });

  if (!url.port) {
    url.port = "3333";
  }

  if (accessToken) {
    url.searchParams.set("access_token", accessToken);
  }

  return url;
}

function wait(timeout) {
  return new Promise((resolve) => setTimeout(() => resolve(), timeout));
}

/**
 * Creates a singleton for the specified async operation allowing only one operation running at time.
 * @param loader
 */
function createPromiseSingleton(loader) {
  let promise = null;

  const singleton = async (...args) => {
    if (promise) {
      return promise;
    }

    promise = loader(...args);

    // Invalidate cached promise if it failed.
    // This allows retries for failed operations.
    promise.catch(() => (promise = null));
    return await promise;
  };
  singleton.invalidate = () => {
    promise = null;
  };
  return singleton;
}

const endpoint = "omni/discovery";
const healthcheckEndpoint = "healthcheck";

export class DiscoveryError extends Error {}

export const ServiceMeta = Symbol("ServiceMeta");
