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

import Stream from "./stream";

export interface SchemaType<T = any> {
  kind: symbol;
  validate(data: T): boolean;
}

export type NumberType = SchemaType<number>;
export type StringType = SchemaType<string>;
export type BooleanType = SchemaType<boolean>;
export type StreamType = SchemaType<Stream<ArrayBuffer>>;
export type LiteralType = <T extends number | string | boolean>(literal: T) => ({
  kind: symbol,
  value: T,
  validate(data: T): boolean;
});
export type OptionalType = <T extends SchemaType>(type: T) => ({
  kind: symbol;
  type: T;
  validate(data: any): boolean;
});

export type ArrayType = <T extends SchemaType>(type: T) => ({
  kind: symbol;
  type: T;
  validate(data: any): boolean;
});

export type ObjectType = <T extends { [field: string]: SchemaType }>(fields: T) => ({
  kind: symbol;
  fields: T;
  validate(data: object): boolean;
});

export type MapType = <T extends SchemaType>(type: T) => ({
  kind: symbol;
  type: T;
  validate(data: object): boolean;
});

export type EnumType = <T extends { [field: string]: string | number }>(members: T) => T & ({
  kind: symbol;
  members: T;
  validate(data: object): boolean;
});

export const InterfaceName: unique symbol;
export const InterfaceOrigin: unique symbol;
export const InterfaceCapabilities: unique symbol;

declare var Schema: {
  Number: NumberType,
  String: StringType,
  Boolean: BooleanType,
  Stream: StreamType,
  Literal: LiteralType,
  Optional: OptionalType,
  Array: ArrayType,
  Object: ObjectType,
  Map: MapType,
  Enum: EnumType,
  InterfaceName: typeof InterfaceName,
  InterfaceOrigin: typeof InterfaceOrigin,
  InterfaceCapabilities: typeof InterfaceCapabilities,
}

export default Schema;