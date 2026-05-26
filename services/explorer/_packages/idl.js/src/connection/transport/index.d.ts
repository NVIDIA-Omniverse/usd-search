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

import { SchemaType } from "../../schema";
import Stream from "../../stream";

export const TransportName: unique symbol;

export default abstract class Client {
  public static readonly [TransportName]: string;
  public static create(
    settings: TransportSettings,
    options?: TransportOptions
  ): Client;

  protected prepared: boolean;
  public prepare(): Promise<void>;
  public close(): Promise<void>;
  public abstract call<TData extends object, TResult>(
    request: Request<TData>
  ): Promise<TResult>;
  public abstract callMany<TData extends object, TResult>(
    request: Request<TData>
  ): Promise<Stream<TResult>>;

  public off(event: "prepare" | "close", callback: () => void): void;
  public off(event: "error", callback: (error: Error) => void): void;

  public on(event: "prepare" | "close", callback: () => void): void;
  public on(event: "error", callback: (error: Error) => void): void;

  public once(event: "prepare" | "close", callback: () => void): void;
  public once(event: "error", callback: (error: Error) => void): void;
}

export interface Request<TData extends object> {
  interfaceName: string;
  methodName: string;
  request: TData;
  schemas: {
    request: SchemaType;
    response: SchemaType;
  };
}

export type TransportEvent = "prepare" | "close" | "error";
export type Callback = () => void;

export interface TransportSettings {
  name: string;
  params: string;
  meta?: TransportMeta;
}

export type TransportMeta = { [key: string]: string };
export type TransportOptions = { [name: string]: any };

export declare class TransportError extends Error {
  constructor(message: string, code?: number);
}

export interface ClientType<T extends Client> {
  new (...args: any[]): T;
}

export interface SupportedTransport {
  name: string;
  meta?: TransportMeta;
}

export declare class ClientFactory {
  public static register<T extends Client>(
    client: ClientType<T>,
    meta: TransportMeta,
    options?: TransportOptions
  ): void;

  public static create<T extends Client>(settings: TransportSettings): T;
  public static getSupported(): SupportedTransport[];
}
