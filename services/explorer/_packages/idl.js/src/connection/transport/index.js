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

import EventEmitter from "../../emitter";

export default class Client {
  constructor() {
    this.events = new EventEmitter(["prepare", "close", "error"]);
    this.prepared = false;
  }

  async prepare() {
    this.prepared = true;
    this.events.emit("prepare");
  }

  async close() {
    this.prepared = false;
    this.events.emit("close");
  }

  async call({ interfaceName, methodName, request, schemas }) {
    throw new Error("Not implemented.");
  }

  async callMany({ interfaceName, methodName, request, schemas }) {
    throw new Error("Not implemented.");
  }

  on(event, callback) {
    this.events.on(event, callback);
  }

  once(event, callback) {
    this.events.once(event, callback);
  }

  off(event, callback) {
    this.events.off(event, callback);
  }
}

export const TransportName = Symbol("TransportName");

export class TransportError extends Error {
  constructor(message, code = -1) {
    super();
    this.message = message;
    this.code = code;
  }
}

export class ClientFactory {
  static registered = {};

  static register(client, meta, options) {
    const transportName = client[TransportName];

    let registered;
    if (transportName in ClientFactory.registered) {
      registered = ClientFactory.registered[transportName];
    } else {
      registered = ClientFactory.registered[transportName] = [];
    }

    registered.push({ name: transportName, meta, options, type: client });
  }

  static create(settings) {
    const transportName = settings.name;
    if (!(transportName in ClientFactory.registered)) {
      throw new Error(
        `Client with '${transportName}' transport name is not registered.`,
      );
    }

    const registered = ClientFactory.registered[transportName];
    const receivedMeta = settings.meta || {};

    for (const { meta, options, type } of registered) {
      if (metaEqual(meta, receivedMeta)) {
        return type.create(settings, options);
      }
    }

    throw new Error(
      `Meta for specified '${transportName}' transport is not registered.`,
    );
  }

  static getSupported() {
    const supported = [];
    for (const registered of Object.values(ClientFactory.registered)) {
      for (const { name, meta = {} } of registered) {
        supported.push({ name, meta });
      }
    }
    return supported;
  }
}

function metaEqual(a, b) {
  if (Object.keys(a).length !== Object.keys(b).length) {
    return false;
  }

  for (const key of Object.keys(a)) {
    if (a[key] !== b[key]) {
      return false;
    }
  }
  return true;
}
