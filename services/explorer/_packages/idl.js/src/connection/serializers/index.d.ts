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

export const SerializerName: unique symbol;

export default class Serializer {
  public static readonly [SerializerName]: string;
  public serialize(data: object): Promise<ArrayBuffer>;
  public deserialize(data: ArrayBuffer): Promise<object>;
}

export function fromArrayBufferToString(buffer: ArrayBuffer): string;
export function fromStringToArrayBuffer(data: string): ArrayBuffer;
export function concatBuffers(...buffers: ArrayBuffer[]): ArrayBuffer;

export interface SerializerType<T extends Serializer> {
  new (...args: any[]): T;
}

export class SerializerFactory {
  public static register<T extends Serializer>(serializerType: SerializerType<T>): void;
  public static create<T extends Serializer>(serializerName: string): T;
}