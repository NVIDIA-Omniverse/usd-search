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

export const NumberType = {
  kind: Symbol("Number"),
  validate: (data) => typeof data === "number",
};

export const StringType = {
  kind: Symbol("String"),
  validate: (data) => typeof data === "string",
};

export const BooleanType = {
  kind: Symbol("Boolean"),
  validate: (data) => typeof data === "boolean",
};

export const StreamType = {
  kind: Symbol("Stream"),
  validate: (data) =>
    data instanceof Stream ||
    (data && data.constructor && data.constructor.name === "Stream"),
};

const LiteralKind = Symbol("Literal");
export const LiteralType = (value) => ({
  kind: LiteralKind,
  value,
  validate: (data) => data === value,
});
LiteralType.kind = LiteralKind;

const OptionalKind = Symbol("Optional");
export const OptionalType = (type) => ({
  kind: OptionalKind,
  type,
  validate: (data) => typeof data === "undefined" || type.validate(data),
});
OptionalType.kind = OptionalKind;

const ArrayKind = Symbol("Array");
export const ArrayType = (type) => ({
  kind: ArrayKind,
  type,
  validate: (data) =>
    data instanceof Array && data.every((item) => type.validate(item)),
});
ArrayType.kind = ArrayKind;

const ObjectKind = Symbol("Object");
export const ObjectType = (fields) => ({
  kind: ObjectKind,
  fields,
  validate: (data) =>
    typeof data === "object" &&
    Object.entries(fields).every(([field, type]) => type.validate(data[field])),
});
ObjectType.kind = ObjectKind;

const MapKind = Symbol("Map");
export const MapType = (type) => ({
  kind: MapKind,
  type,
  validate: (data) =>
    typeof data === "object" &&
    Object.values(data).every((value) => type.validate(value)),
});
MapType.kind = MapKind;

const EnumKind = Symbol("Enum");
export const EnumType = (members) => ({
  ...members,
  members,
  kind: EnumKind,
  validate: (data) => Object.values(members).includes(data),
});
EnumType.kind = EnumKind;

export const InterfaceName = Symbol("InterfaceName");
export const InterfaceOrigin = Symbol("InterfaceOrigin");
export const InterfaceCapabilities = Symbol("InterfaceCapabilities");

const Schema = {
  Number: NumberType,
  String: StringType,
  Boolean: BooleanType,
  Stream: StreamType,
  Array: ArrayType,
  Object: ObjectType,
  Optional: OptionalType,
  Map: MapType,
  Enum: EnumType,
  Literal: LiteralType,
  InterfaceName: InterfaceName,
  InterfaceOrigin: InterfaceOrigin,
  InterfaceCapabilities: InterfaceCapabilities,
};

export default Schema;
