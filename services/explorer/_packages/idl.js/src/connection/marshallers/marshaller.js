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

import { ObjectType, OptionalType, StreamType } from "../../schema.js";
import { SerializerFactory } from "../serializers";

export const MarshallerName = Symbol("MarshallerName");

export default class Marshaller {
  static [MarshallerName] = "bs"; // Binary separately

  constructor(serializer) {
    this.serializer = serializer;
  }

  async marshal(data, schema) {
    const marshaling = { ...data };

    const binary = [];
    const fields = [];

    for (const binaryField of this.introspect(marshaling, schema)) {
      fields.push(binaryField);
      binary.push(binaryField.get());
      binaryField.delete();
    }

    const content = await this.serializer.serialize(marshaling, schema);

    for (let i = 0; i < binary.length; i++) {
      const field = fields[i];
      const blob = binary[i];
      field.set(blob);
    }

    return [content, fields];
  }

  async unmarshal(data) {
    return this.serializer.deserialize(data);
  }

  *introspect(data, schema) {
    for (const [field, type] of Object.entries(schema.fields)) {
      if (type.kind === StreamType.kind) {
        yield new BinaryField(field, data);
      } else if (
        type.kind === OptionalType.kind &&
        type.type.kind === StreamType.kind
      ) {
        yield new BinaryField(field, data);
      } else if (type.kind === ObjectType.kind) {
        yield* this.introspect(data[field], type);
      }
    }
  }
}

export class BinaryField {
  constructor(name, owner) {
    this.name = name;
    this.owner = owner;
  }

  get() {
    return this.owner[this.name];
  }

  set(value) {
    this.owner[this.name] = value;
  }

  delete() {
    delete this.owner[this.name];
  }
}

export class MarshallerFactory {
  static marshallers = {};

  static register(marshallerType) {
    MarshallerFactory.marshallers[marshallerType[MarshallerName]] =
      marshallerType;
  }

  static create(marshallerName, serializerName) {
    const serializer = SerializerFactory.create(serializerName);
    const marshallerType = MarshallerFactory.marshallers[marshallerName];
    if (!marshallerType) {
      throw new Error(`Marshaller ${marshallerName} is not registered.`);
    }
    return new marshallerType(serializer);
  }
}

MarshallerFactory.register(Marshaller);
