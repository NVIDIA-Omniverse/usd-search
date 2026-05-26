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

import { Meta, SupportedTransport } from "@omniverse/discovery/data";
import { default as ClientTransport } from "@omniverse/idl/connection/transport";
import WebSocketClient from "@omniverse/idl/connection/transport/websocket";
import {
  InterfaceCapabilities,
  InterfaceName,
  InterfaceOrigin,
} from "@omniverse/idl/schema";

export default class DiscoverySearch {
  constructor(uri: string, options?: DiscoverySearchOptions);
  find<T>(
    clientType: ClientType<T>,
    meta?: Meta,
    supportedTransport?: SupportedTransport[],
    capabilities?: { [method: string]: number },
    accessToken?: string,
  ): Promise<T & DiscoverySearchInfo>;

  close(): void;
}

export type DiscoverySearchOptions = ConnectOptions;

export interface DiscoverySearchInfo {
  [InterfaceCapabilities]?: Record<string, number>;
  [ServiceMeta]?: Record<string, string>;
}

export interface ClientType<T> {
  readonly [InterfaceName]: string;
  readonly [InterfaceOrigin]: string;
  new (transport: ClientTransport): T;
}

export class DiscoveryError extends Error {}

interface ConnectOptions {
  timeout?: number;

  /**
   * Forces to use secure connections.
   */
  secure?: boolean;

  /**
   * JSON Web Token to authenticate the connection.
   */
  accessToken?: string;
}

/**
 * Creates a WebSocketClient instance for communicating with the discovery service
 * prioritizing secure path-based routing.
 */
export function connect(
  uri: string,
  options?: ConnectOptions
): Promise<WebSocketClient>;
export function createPathBasedClient(
  uri: string,
  protocol?: string,
  accessToken?: string,
): Promise<WebSocketClient | undefined>;
export function createPortBasedClient(
  uri: string,
  accessToken?: string
): Promise<WebSocketClient | undefined>;

export const ServiceMeta: unique symbol;
