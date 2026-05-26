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

import Client, { ClientFactory, TransportName } from "./index";
import Marshaller from "../marshallers/marshaller.js";
import Stream from "../../stream.js";

export default class HttpFileClient extends Client {
  static [TransportName] = "http_file";

  static register() {
    ClientFactory.register(HttpFileClient, {});
  }

  static create({ name, params: paramsJSON, meta = {} }) {
    if (name !== HttpFileClient[TransportName]) {
      throw new Error(`Invalid transport name '${name}'.`);
    }

    const params = JSON.parse(paramsJSON);
    return new HttpFileClient(params);
  }

  constructor({ uri }) {
    super();
    this.uri = uri;
  }

  async call({ interfaceName, methodName, request, schemas }) {
    const marshaller = new Marshaller(null);

    let files = [...marshaller.introspect(request, schemas.request)];
    let file = null;
    if (files.length > 1) {
      throw new Error("Multiple files are not supported.");
    } else if (files.length === 1) {
      file = files[0];
    }

    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(request)) {
      if (!file || file.name !== key) {
        query.set(key, value);
      }
    }

    const url = `${this.uri}/${interfaceName}/${methodName}/?${query}`;

    let data;
    if (file) {
      const stream = file.get();
      data = await stream.readAll();
    }

    const response = await fetch(url, { method: "POST", body: new Blob(data) });
    if (response.status >= 400) {
      throw new Error(`Error ${response.status}.`);
    }

    const result = {};
    for (const header of response.headers.keys()) {
      if (header.startsWith("Http-File-")) {
        const key = header.slice("Http-File-".length);
        result[key] = response.headers.get(header);
      }
    }

    files = [...marshaller.introspect(result, schemas.response)];
    if (files.length > 1) {
      throw new Error("Multiple files are not supported.");
    } else if (files.length === 1) {
      file = files[0];

      const reader = response.body.getReader();
      const stream = (result[file.name] = new Stream());
      stream.on("read", async () => {
        const chunk = await reader.read();
        await stream.write(chunk.value);
        if (chunk.done) {
          await stream.end();
        }
      });
    }

    return result;
  }
}
