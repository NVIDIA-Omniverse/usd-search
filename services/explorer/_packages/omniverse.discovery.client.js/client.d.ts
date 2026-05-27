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

import Client from "@omniverse/idl/connection/transport";
import Stream from "@omniverse/idl/stream";
import { InterfaceName, InterfaceOrigin, InterfaceCapabilities } from "@omniverse/idl/schema";
import * as data from "./data";

export class DiscoverySearch {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    Finds an entry for specified origin and interface.
    A query can specify the required capabilities, connection settings and
    other metadata.
   */
  public find(request: data.DiscoverySearchFindRequest): Promise<data.SearchResult>;
  
  /*
    Retrieves all registered interfaces for this discovery service.
   */
  public findAll(request?: data.DiscoverySearchFindAllRequest): Promise<Stream<data.SearchResult>>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}

export class DiscoveryRegistration {
  public readonly transport: Client;
  constructor(transport: Client);

  
  /*
    Registers a new service with specified connection settings and interfaces.
    The discovery keeps a subscription to ensure that registered service is
    still available.
    The service is removed from discovery as soon as it stops receiving health
    checks from the subscription.

    You can use `register_unsafe` to register a service without a subscription
    and health checks.
   */
  public register(request: data.DiscoveryRegistrationRegisterRequest): Promise<Stream<data.HealthCheck>>;
  
  /*
    Registers a new service without a health checking.
    It's a service responsibility to call `unregister_unsafe` when the provided
    functions become not available.
   */
  public registerUnsafe(request: data.DiscoveryRegistrationRegisterUnsafeRequest): Promise<data.HealthCheck>;
  
  /*
    Removes the service registered with `register_unsafe` from the discovery.
   */
  public unregisterUnsafe(request: data.DiscoveryRegistrationUnregisterUnsafeRequest): Promise<data.HealthCheck>;
  

  public static readonly [InterfaceName]: string;
  public static readonly [InterfaceOrigin]: string;
  public static readonly [InterfaceCapabilities]?: { [method: string]: number };
}
