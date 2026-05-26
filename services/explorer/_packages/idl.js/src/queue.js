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

export default class Queue {
  constructor(capacity = 0) {
    this.getters = [];
    this.putters = [];
    this.buffer = [];
    this.capacity = capacity;
  }

  get length() {
    return this.buffer.length;
  }

  put = (data) => {
    return new Promise((resolve) => {
      const getter = this.getters.pop();
      if (getter) {
        getter(data);
        resolve();
      } else if (!this.capacity || this.buffer.length < this.capacity) {
        this.buffer = [data].concat(this.buffer);
        resolve();
      } else {
        const putter = () => {
          resolve();
          return data;
        };
        this.putters = [putter].concat(this.putters);
      }
    });
  };

  get = () => {
    return new Promise((resolve) => {
      if (this.buffer.length) {
        const item = this.buffer.pop();
        resolve(item);
      } else {
        const putter = this.putters.pop();
        if (putter) {
          const item = putter();
          resolve(item);
        } else {
          this.getters = [resolve].concat(this.getters);
        }
      }
    });
  };
}
