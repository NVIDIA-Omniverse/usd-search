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

import Serializer from "../serializers/index";
import { SchemaType } from "../../schema";

export const MarshallerName: unique symbol;

export default class Marshaller {
  public static readonly [MarshallerName]: string;
  constructor(serializer: Serializer);
  public marshal(data: object, schema: SchemaType): Promise<[ArrayBuffer, BinaryField[]]>;
  public unmarshal(data: ArrayBuffer): Promise<object>;
  public introspect(data: object, schema: SchemaType): Iterator<BinaryField>;
}

export interface BinaryField {
  get(): ArrayBuffer;
  set(value: ArrayBuffer): void;
  delete(): void;
}

export interface MarshallerType<T extends Marshaller> {
  new (...args: any[]): T;
}

export class MarshallerFactory {
  public static register<T extends Marshaller>(marshallerType: MarshallerType<T>): void;
  public static create<T extends Marshaller>(marshallerName: string, serializerName: string): T;
}