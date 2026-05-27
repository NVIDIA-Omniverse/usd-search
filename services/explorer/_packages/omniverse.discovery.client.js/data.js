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

import Schema from "@omniverse/idl/schema";


export const Capabilities = Schema.Map(Schema.Number);

export const DiscoverySearchServerRemoteCapabilities = Capabilities;

export const DiscoverySearchServerLocalCapabilities = Schema.Literal({'find': 2, 'find_all': 2});

export const DiscoverySearchServerCapabilities = DiscoverySearchServerRemoteCapabilities;

export const DiscoverySearchClientRemoteCapabilities = Capabilities;

export const DiscoverySearchClientLocalCapabilities = Schema.Literal({'find': 2, 'find_all': 2});

export const DiscoverySearchClientCapabilities = DiscoverySearchClientLocalCapabilities;

export const DiscoverySearchFindAllServerRemoteVersion = Schema.Number;

export const DiscoverySearchFindAllServerLocalVersion = Schema.Literal(2);

export const DiscoverySearchFindAllServerVersion = DiscoverySearchFindAllServerRemoteVersion;

export const DiscoverySearchFindAllClientRemoteVersion = Schema.Number;

export const DiscoverySearchFindAllClientLocalVersion = Schema.Literal(2);

export const DiscoverySearchFindServerRemoteVersion = Schema.Number;

export const DiscoverySearchFindServerLocalVersion = Schema.Literal(2);

export const DiscoverySearchFindServerVersion = DiscoverySearchFindServerRemoteVersion;

export const DiscoverySearchFindClientRemoteVersion = Schema.Number;

export const DiscoverySearchFindClientLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationServerRemoteCapabilities = Capabilities;

export const DiscoveryRegistrationServerLocalCapabilities = Schema.Literal({'register': 2, 'register_unsafe': 2, 'unregister_unsafe': 2});

export const DiscoveryRegistrationServerCapabilities = DiscoveryRegistrationServerRemoteCapabilities;

export const DiscoveryRegistrationClientRemoteCapabilities = Capabilities;

export const DiscoveryRegistrationClientLocalCapabilities = Schema.Literal({'register': 2, 'register_unsafe': 2, 'unregister_unsafe': 2});

export const DiscoveryRegistrationClientCapabilities = DiscoveryRegistrationClientLocalCapabilities;

export const DiscoveryRegistrationUnregisterUnsafeServerRemoteVersion = Schema.Number;

export const DiscoveryRegistrationUnregisterUnsafeServerLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationUnregisterUnsafeServerVersion = DiscoveryRegistrationUnregisterUnsafeServerRemoteVersion;

export const DiscoveryRegistrationUnregisterUnsafeClientRemoteVersion = Schema.Number;

export const DiscoveryRegistrationUnregisterUnsafeClientLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationRegisterUnsafeServerRemoteVersion = Schema.Number;

export const DiscoveryRegistrationRegisterUnsafeServerLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationRegisterUnsafeServerVersion = DiscoveryRegistrationRegisterUnsafeServerRemoteVersion;

export const DiscoveryRegistrationRegisterUnsafeClientRemoteVersion = Schema.Number;

export const DiscoveryRegistrationRegisterUnsafeClientLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationRegisterServerRemoteVersion = Schema.Number;

export const DiscoveryRegistrationRegisterServerLocalVersion = Schema.Literal(2);

export const DiscoveryRegistrationRegisterServerVersion = DiscoveryRegistrationRegisterServerRemoteVersion;

export const DiscoveryRegistrationRegisterClientRemoteVersion = Schema.Number;

export const DiscoveryRegistrationRegisterClientLocalVersion = Schema.Literal(2);

export const Meta = Schema.Map(Schema.String);

export const HealthStatus = Schema.Enum({
  OK: "OK",
  Closed: "CLOSED",
  Denied: "DENIED",
  AlreadyExists: "ALREADY_EXISTS",
  InvalidSettings: "INVALID_SETTINGS",
  InvalidCapabilities: "INVALID_CAPABILITIES",
});

export const ServiceInterface = Schema.Object({
  origin: Schema.String,
  name: Schema.String,
  capabilities: Schema.Optional(Capabilities),
});

export const TransportSettings = Schema.Object({
  name: Schema.String,
  params: Schema.String,
  meta: Meta,
});

export const ServiceInterfaceMap = Schema.Map(ServiceInterface);

export const SupportedTransport = Schema.Object({
  name: Schema.String,
  meta: Schema.Optional(Meta),
});

export const SearchResult = Schema.Object({
  found: Schema.Boolean,
  version: Schema.Optional(Schema.Number),
  service_interface: Schema.Optional(ServiceInterface),
  transport: Schema.Optional(TransportSettings),
  meta: Schema.Optional(Meta),
});

export const DiscoverySearchFindAllClientVersion = DiscoverySearchFindAllClientLocalVersion;

export const DiscoverySearchFindClientVersion = DiscoverySearchFindClientLocalVersion;

export const DiscoverInterfaceQuery = Schema.Object({
  service_interface: ServiceInterface,
  supported_transport: Schema.Optional(Schema.Array(SupportedTransport)),
  meta: Schema.Optional(Meta),
});

export const HealthCheck = Schema.Object({
  status: HealthStatus,
  time: Schema.String,
  version: Schema.Optional(Schema.Number),
  message: Schema.Optional(Schema.String),
  meta: Schema.Optional(Meta),
});

export const DiscoveryRegistrationUnregisterUnsafeClientVersion = DiscoveryRegistrationUnregisterUnsafeClientLocalVersion;

export const Manifest = Schema.Object({
  interfaces: ServiceInterfaceMap,
  transport: TransportSettings,
  token: Schema.String,
  meta: Schema.Optional(Meta),
});

export const DiscoveryRegistrationRegisterUnsafeClientVersion = DiscoveryRegistrationRegisterUnsafeClientLocalVersion;

export const DiscoveryRegistrationRegisterClientVersion = DiscoveryRegistrationRegisterClientLocalVersion;



export const DiscoverySearchFindRequest = Schema.Object({
  query: DiscoverInterfaceQuery,
  version: Schema.Optional(DiscoverySearchFindClientVersion),
});

export const DiscoverySearchFindAllRequest = Schema.Object({
  version: Schema.Optional(DiscoverySearchFindAllClientVersion),
});

export const DiscoveryRegistrationRegisterRequest = Schema.Object({
  manifest: Manifest,
  version: Schema.Optional(DiscoveryRegistrationRegisterClientVersion),
});

export const DiscoveryRegistrationRegisterUnsafeRequest = Schema.Object({
  manifest: Manifest,
  version: Schema.Optional(DiscoveryRegistrationRegisterUnsafeClientVersion),
});

export const DiscoveryRegistrationUnregisterUnsafeRequest = Schema.Object({
  manifest: Manifest,
  version: Schema.Optional(DiscoveryRegistrationUnregisterUnsafeClientVersion),
});
