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

export interface StreamOptions {
  capacity?: number;
}

export default class Stream<T> {
  public static IDLE: symbol;
  public static READING: symbol;
  public static END: symbol;
  public static CLOSED: symbol;
  public readonly status: symbol;
  public readonly capacity: number;

  public constructor(options?: StreamOptions);

  public write(data: T): Promise<void>;
  public end(): Promise<void>;
  public error(err: Error): Promise<void>;
  public read(): Promise<T | typeof Stream.END>;
  public readAll(): Promise<T[]>;
  public close(): Promise<void>;
  public [Symbol.asyncIterator](): AsyncIterator<T>;

  public on(event: "write", callback: (data: T) => Promise<void>): void;
  public on(event: Event, callback: Callback): void;
  public once(event: "write", callback: (data: T) => Promise<void>): void;
  public once(event: Event, callback: Callback): void;
  public off(event: "write", callback: (data: T) => Promise<void>): void;
  public off(event: Event, callback: Callback): void;
}

export type Event = "write" | "read" | "end" | "close";
type Callback = () => Promise<void>;