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

import EventEmitter from "./emitter";
import Queue from "./queue";

export default class Stream {
  static IDLE = Symbol("IDLE");
  static READING = Symbol("READING");
  static CLOSED = Symbol("CLOSED");
  static END = Symbol("END");

  constructor({ capacity = 0 } = {}) {
    this.queue = new Queue(capacity);
    this.status = Stream.IDLE;
    this.events = new EventEmitter(["read", "write", "close", "end"]);
  }

  get capacity() {
    return this.queue.capacity;
  }

  async write(data) {
    if (this.status === Stream.CLOSED) {
      throw Stream.CLOSED;
    }
    if (this.status === Stream.END) {
      throw Stream.END;
    }

    await this.queue.put(data);
    this.events.emit("write", data);
  }

  async end() {
    await this.queue.put(Stream.END);
  }

  async error(err) {
    await this.queue.put(err);
  }

  async close() {
    this.status = Stream.CLOSED;
    await this.queue.put(Stream.CLOSED);
    this.queue = new Queue();
    this.events.emit("close");
  }

  async read() {
    if (this.status === Stream.IDLE) {
      this.status = Stream.READING;
    } else if (this.status === Stream.CLOSED) {
      throw Stream.CLOSED;
    }

    this.events.emit("read");

    const item = await this.queue.get();
    if (item === Stream.CLOSED) {
      throw Stream.CLOSED;
    }

    if (item instanceof Error) {
      throw item;
    }

    if (item === Stream.END) {
      this.status = Stream.END;
      this.events.emit("end");
    }
    return item;
  }

  async *[Symbol.asyncIterator]() {
    while (true) {
      const item = await this.read();
      if (item === Stream.END) {
        break;
      } else {
        yield item;
      }
    }
  }

  async readAll() {
    const buffer = [];
    while (true) {
      const item = await this.read();
      if (item === Stream.END) {
        break;
      } else {
        buffer.push(item);
      }
    }
    return buffer;
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
