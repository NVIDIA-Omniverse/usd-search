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
import * as _data from "./data";

export class DiscoverySearch {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    Finds an entry for specified origin and interface.
    A query can specify the required capabilities, connection settings and
    other metadata.
   */
  async find({query, }) {
    const _request = {query, version: _data.DiscoverySearchFindClientVersion.value, };
    if (!_data.DiscoverySearchFindRequest.validate(_request)) {
      throw new Error("Invalid DiscoverySearchFindRequest.");
    }
    return await this.transport.call({ interfaceName: "DiscoverySearch", methodName: "find", request: _request, schemas: { request: _data.DiscoverySearchFindRequest, response: _data.SearchResult }});
  }
  
  /*
    Retrieves all registered interfaces for this discovery service.
   */
  async findAll() {
    const _request = {version: _data.DiscoverySearchFindAllClientVersion.value, };
    if (!_data.DiscoverySearchFindAllRequest.validate(_request)) {
      throw new Error("Invalid DiscoverySearchFindAllRequest.");
    }
    return await this.transport.callMany({ interfaceName: "DiscoverySearch", methodName: "find_all", request: _request, schemas: { request: _data.DiscoverySearchFindAllRequest, response: _data.SearchResult }});
  }
  
}
DiscoverySearch[Schema.InterfaceName] = "DiscoverySearch";
DiscoverySearch[Schema.InterfaceOrigin] = "Discovery.idl.ts";
DiscoverySearch[Schema.InterfaceCapabilities] = _data.DiscoverySearchClientLocalCapabilities.value;

export class DiscoveryRegistration {
  constructor(transport) {
    this.transport = transport;
  }
  
  /*
    Registers a new service with specified connection settings and interfaces.
    The discovery keeps a subscription to ensure that registered service is
    still available.
    The service is removed from discovery as soon as it stops receiving health
    checks from the subscription.

    You can use `register_unsafe` to register a service without a subscription
    and health checks.
   */
  async register({manifest, }) {
    const _request = {manifest, version: _data.DiscoveryRegistrationRegisterClientVersion.value, };
    if (!_data.DiscoveryRegistrationRegisterRequest.validate(_request)) {
      throw new Error("Invalid DiscoveryRegistrationRegisterRequest.");
    }
    return await this.transport.callMany({ interfaceName: "DiscoveryRegistration", methodName: "register", request: _request, schemas: { request: _data.DiscoveryRegistrationRegisterRequest, response: _data.HealthCheck }});
  }
  
  /*
    Registers a new service without a health checking.
    It's a service responsibility to call `unregister_unsafe` when the provided
    functions become not available.
   */
  async registerUnsafe({manifest, }) {
    const _request = {manifest, version: _data.DiscoveryRegistrationRegisterUnsafeClientVersion.value, };
    if (!_data.DiscoveryRegistrationRegisterUnsafeRequest.validate(_request)) {
      throw new Error("Invalid DiscoveryRegistrationRegisterUnsafeRequest.");
    }
    return await this.transport.call({ interfaceName: "DiscoveryRegistration", methodName: "register_unsafe", request: _request, schemas: { request: _data.DiscoveryRegistrationRegisterUnsafeRequest, response: _data.HealthCheck }});
  }
  
  /*
    Removes the service registered with `register_unsafe` from the discovery.
   */
  async unregisterUnsafe({manifest, }) {
    const _request = {manifest, version: _data.DiscoveryRegistrationUnregisterUnsafeClientVersion.value, };
    if (!_data.DiscoveryRegistrationUnregisterUnsafeRequest.validate(_request)) {
      throw new Error("Invalid DiscoveryRegistrationUnregisterUnsafeRequest.");
    }
    return await this.transport.call({ interfaceName: "DiscoveryRegistration", methodName: "unregister_unsafe", request: _request, schemas: { request: _data.DiscoveryRegistrationUnregisterUnsafeRequest, response: _data.HealthCheck }});
  }
  
}
DiscoveryRegistration[Schema.InterfaceName] = "DiscoveryRegistration";
DiscoveryRegistration[Schema.InterfaceOrigin] = "Discovery.idl.ts";
DiscoveryRegistration[Schema.InterfaceCapabilities] = _data.DiscoveryRegistrationClientLocalCapabilities.value;
