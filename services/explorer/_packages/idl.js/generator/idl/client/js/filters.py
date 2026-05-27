# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from idl.formatting import pascal
from idl.schema import BuiltinType, InterfaceSchema, MethodSchema, PropertySchema
from idl.spec import Spec
from idl.templates.filters.ts import ts_type


def include(spec: Spec):
    return {
        "schema_type": schema_type,
        "schema_type_name": schema_type_name,
        "schema_dtype": schema_dtype,
        "schema_dtype_name": schema_dtype_name,
        "request": request,
        "has_all_optional_params": has_all_optional_params,
        "has_methods_with_multiple_responses": has_methods_with_multiple_responses,
        "has_binary_data": has_binary_data,
        "has_user_params": has_user_params,
    }


schema_types = {
    BuiltinType.number: "Schema.Number",
    BuiltinType.int8: "Schema.Number",
    BuiltinType.int16: "Schema.Number",
    BuiltinType.int32: "Schema.Number",
    BuiltinType.int64: "Schema.Number",
    BuiltinType.uint8: "Schema.Number",
    BuiltinType.uint16: "Schema.Number",
    BuiltinType.uint32: "Schema.Number",
    BuiltinType.uint64: "Schema.Number",
    BuiltinType.float: "Schema.Number",
    BuiltinType.double: "Schema.Number",
    BuiltinType.string: "Schema.String",
    BuiltinType.boolean: "Schema.Boolean",
    BuiltinType.bytes: "Schema.Stream",
    BuiltinType.blob: "Schema.Stream",
}


def schema_type(prop: PropertySchema) -> str:
    name = schema_type_name(prop.type)
    if prop.is_array:
        name = f"Schema.Array({name})"
    if prop.get("optional"):
        name = f"Schema.Optional({name})"
    return name


def schema_type_name(name: str):
    return schema_types.get(name, name)


def schema_dtype(prop: PropertySchema) -> str:
    name = schema_dtype_name(prop.type)
    if prop.is_array:
        name += "[]"
    return name


def schema_dtype_name(name: str):
    if name in (BuiltinType.bytes, BuiltinType.blob):
        return "Stream<ArrayBuffer>"
    return ts_type(name)


def request(function: MethodSchema, interface: InterfaceSchema):
    return f"{interface.name}{pascal(function.name)}Request"


def has_all_optional_params(function: MethodSchema, interface: InterfaceSchema) -> bool:
    for param in function.params:
        if not param.is_const and not param.optional:
            return False
    for field in interface.fields:
        if not field.is_const and not field.optional:
            return False
    return True


def has_methods_with_multiple_responses(spec: Spec) -> bool:
    for interface in spec.interfaces.values():
        for func in interface.functions:
            if func.returns.is_many:
                return True
    return False


def has_binary_data(spec: Spec) -> bool:
    for struct in spec.structs.values():
        for field in struct.fields:
            if field.type in (BuiltinType.bytes, BuiltinType.blob):
                return True
    return False


def has_user_params(function: MethodSchema, interface: InterfaceSchema) -> bool:
    for param in function.params:
        if not param.is_const:
            return True
    for field in interface.fields:
        if not field.is_const:
            return True
    return False
