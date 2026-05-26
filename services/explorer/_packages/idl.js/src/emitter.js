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

export default class EventEmitter {
  constructor(eventNames) {
    this.events = {};
    for (const event of eventNames) {
      this.events[event] = [];
    }
  }

  on(event, callback) {
    if (!this.events[event]) {
      throw new Error(`Unknown event '${event}'.`);
    }
    this.events[event].push(callback);
  }

  once(event, callback) {
    const cb = (...args) => {
      this.off(event, cb);
      callback(...args);
    };
    this.on(event, cb);
  }

  off(event, callback) {
    if (!this.events[event]) {
      throw new Error(`Unknown event '${event}'.`);
    }
    this.events[event] = this.events[event].filter((cb) => cb !== callback);
  }

  emit(eventName, event) {
    if (!this.events[eventName]) {
      throw new Error(`Unknown event '${eventName}'.`);
    }

    for (const callback of this.events[eventName]) {
      callback(event);
    }
  }
}
