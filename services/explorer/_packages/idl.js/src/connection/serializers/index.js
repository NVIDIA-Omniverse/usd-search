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

export default class Serializer {
  async serialize(data) {
    throw new Error("Not implemented.");
  }

  async deserialize(data) {
    throw new Error("Not implemented.");
  }
}

export const SerializerName = Symbol("SerializerName");

export function fromStringToArrayBuffer(str) {
  return new TextEncoder().encode(str).buffer;
}

export function fromArrayBufferToString(buffer) {
  return new TextDecoder().decode(buffer);
}

export function concatBuffers(...buffers) {
  const result = new Uint8Array(
    new ArrayBuffer(
      buffers.reduce((size, buffer) => size + buffer.byteLength, 0),
    ),
  );

  let offset = 0;
  for (const buffer of buffers) {
    result.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  }
  return result.buffer;
}

export class SerializerFactory {
  static serializers = {};

  static register(serializerType) {
    SerializerFactory.serializers[serializerType[SerializerName]] =
      serializerType;
  }

  static create(serializerName) {
    const serializerType = SerializerFactory.serializers[serializerName];
    if (!serializerType) {
      throw new Error(`Serializer ${serializerName} is not registered.`);
    }
    return new serializerType();
  }
}
