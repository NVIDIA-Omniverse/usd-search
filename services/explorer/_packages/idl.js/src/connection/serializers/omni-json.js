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

import JSONSerializer from "./json";
import { SerializerName } from "./index";

export default class OmniJSONSerializer extends JSONSerializer {
  static [SerializerName] = "omni_json";

  async serialize(data) {
    this.validate(data);
    return super.serialize(data);
  }

  validate(data) {
    if (data instanceof Array) {
      for (const item of data) {
        this.validate(item);
      }
    } else if (typeof data === "object") {
      for (const item of Object.values(data)) {
        this.validate(item);
      }
    } else if (typeof data === "string") {
      if (data.includes("\0")) {
        throw new Error(`String ${data} contains the terminate symbol.`);
      }
    }
  }
}
