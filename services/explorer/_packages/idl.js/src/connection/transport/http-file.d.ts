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

import Client, {
  Request,
  TransportName,
  TransportOptions,
  TransportSettings,
} from "./index";
import Stream from "../../stream";

export default class HttpFileClient extends Client {
  public static readonly [TransportName]: string;
  public static register(): void;
  public static create(
    settings: TransportSettings,
    options?: TransportOptions
  ): HttpFileClient;

  protected prepared: boolean;
  public readonly uri: string;

  constructor(options: HttpFileClientParams);
  public prepare(): Promise<void>;
  public close(): Promise<void>;
  public call<TData extends object, TResult>(
    request: Request<TData>
  ): Promise<TResult>;
  public callMany<TData extends object, TResult>(
    request: Request<TData>
  ): Promise<Stream<TResult>>;

  public off(event: "prepare" | "close", callback: () => void): void;
  public off(event: "error", callback: (error: Error) => void): void;

  public on(event: "prepare" | "close", callback: () => void): void;
  public on(event: "error", callback: (error: Error) => void): void;

  public once(event: "prepare" | "close", callback: () => void): void;
  public once(event: "error", callback: (error: Error) => void): void;
}

export interface HttpFileClientParams {
  uri: string;
}

