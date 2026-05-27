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

import { fromStringToArrayBuffer } from "../serializers";
import Stream from "../../stream";
import Schema from "../../schema";
import Client, { ClientFactory, TransportName } from "./index";
import Marshaller from "../marshallers/marshaller";
import OmniJSONSerializer from "../serializers/omni-json";

export default class OmniClientTransport extends Client {
  static [TransportName] = "connlib";

  static register() {
    ClientFactory.register(OmniClientTransport, { throttle: "true" });
    ClientFactory.register(OmniClientTransport, { throttle: "false" });
    ClientFactory.register(OmniClientTransport, {});
  }

  static create({ name, params: paramsJSON, meta = {}, accessToken }) {
    if (name !== OmniClientTransport[TransportName]) {
      throw new Error(`Invalid transport name '${name}'.`);
    }

    const params = JSON.parse(paramsJSON);
    let maxIrc = undefined;
    if (meta.throttle === "true") {
      maxIrc = parseInt(params.max_irc, 10) || undefined;
    }
    return new OmniClientTransport({ ...params, accessToken, maxIrc });
  }

  constructor({ url, accessToken, maxIrc }) {
    super();
    this.url = url;
    if (accessToken) {
      const urlBuilder = new URL(url);
      urlBuilder.searchParams.set("access_token", accessToken);
      this.url = urlBuilder.toString();
    }
    /** connlib transport only supports the default marshaller and JSON serializer. **/
    this.marshaller = new Marshaller(new OmniJSONSerializer());
    this.ws = null;
    this.requestId = 0;
    this.requests = {};
    this.maxIrc = maxIrc;
    this.activeRequestsCount = 0;
    this.waitingQueue = [];
  }

  prepare() {
    return new Promise(async (resolve, reject) => {
      try {
        await super.prepare();
        this.ws = new WebSocket(this.url);
        this.ws.binaryType = "arraybuffer";
        this.ws.onmessage = (msg) => this.receive(msg);
        this.ws.onopen = resolve;
        this.ws.onerror = async (err) => {
          await this.close();
          reject(err);
        };
        this.ws.onclose = () => this.close();
      } catch (err) {
        reject(err);
      }
    });
  }

  async _acquire() {
    if (this.maxIrc && this.activeRequestsCount >= this.maxIrc) {
      await new Promise((res) => {
        this.waitingQueue.push(res);
      });
    }
    this.activeRequestsCount += 1;
  }

  _release() {
    const waiter = this.waitingQueue.shift();
    if (waiter) {
      waiter();
    }
    this.activeRequestsCount -= 1;
  }

  async close() {
    this.ws.close();
    for (const request of Object.values(this.requests)) {
      await request.responses.close();
    }
    await super.close();
  }

  async call({ interfaceName, methodName, request: data, schemas }) {
    await this._acquire();
    const responses = await this.send({ methodName, data, schemas });
    const result = await responses.read();
    await responses.end();
    return result;
  }

  async callMany({ interfaceName, methodName, request: data, schemas }) {
    await this._acquire();

    return await this.send({ methodName, data, schemas });
  }

  async send({ methodName, data, schemas }) {
    if (!this.prepared) {
      throw new Error("You should call prepare() first.");
    }

    const request = { ...data };
    request.id = ++this.requestId;
    request.command = methodName;

    const [params, buffers] = await this.marshaller.marshal(
      request,
      schemas.request,
    );

    request.responses = new Stream();
    const stop = async () => {
      request.responses.off("end", end);
      if (
        request.responses.stopped !== true &&
        request.responses.stopped !== "true"
      )
        await this.stop(request.id);
      delete this.requests[request.id];
    };

    const end = async () => {
      request.responses.off("close", stop);
      delete this.requests[request.id];
    };

    request.responses.once("close", stop);
    request.responses.once("end", end);
    request.schemas = schemas;

    this.requests[request.id] = request;
    if (buffers.length > 1) {
      throw new Error("Multiple binary buffers are not supported.");
    }

    if (buffers.length === 0) {
      this.ws.send(params);
    } else {
      const field = buffers[0];

      let buffer = params;

      const content = field.get();
      if (content) {
        let tmp = new Uint8Array(params.byteLength + 1);
        tmp.set(params, 0);
        tmp.set([0], params.byteLength);

        buffer = tmp.buffer;
        do {
          const chunk = await content.read();
          if (chunk === Stream.END) {
            break;
          }

          const tmp = new Uint8Array(buffer.byteLength + chunk.byteLength);
          tmp.set(new Uint8Array(buffer), 0);
          tmp.set(new Uint8Array(chunk), buffer.byteLength);
          buffer = tmp.buffer;
        } while (true);
      }
      this.ws.send(buffer);
    }
    return request.responses;
  }

  async receive(msg) {
    try {
      let data = msg.data;
      if (typeof data === "string") {
        data = fromStringToArrayBuffer(data);
      }

      const bufferedMessage = new Uint8Array(data);
      const separator = bufferedMessage.indexOf(0);

      const [meta, payload] =
        separator === -1
          ? [bufferedMessage, new Uint8Array(0)]
          : [
              bufferedMessage.slice(0, separator),
              bufferedMessage.slice(separator + 1),
            ];

      const response = await this.marshaller.unmarshal(meta.buffer);
      if (this.maxIrc && (response.fin === true || response.fin === "true")) {
        this._release();
      }
      const request = this.requests[response.id];
      if (!request) {
        return;
      }

      if (stopped in response) {
        request.responses.stopped = response.stopped;
      }

      const buffers = this.marshaller.introspect(
        response,
        request.schemas.response,
      );
      if (buffers.length > 1) {
        console.error(
          `Multiple binary buffers are not supported for response.`,
          request.schemas.response,
        );
        return;
      }

      if (buffers.length === 1) {
        const stream = new Stream();
        await stream.write(payload.buffer);
        await stream.end();

        const field = buffers[0];
        field.set(stream);
      }

      await request.responses.write(response);
    } catch (error) {
      this.events.emit("error", error);
      throw error;
    }
  }

  async stop(requestId) {
    if (
      !this.ws ||
      this.ws.readyState === WebSocket.CLOSED ||
      this.ws.readyState === WebSocket.CLOSING
    ) {
      return;
    }

    const data = { subscription_id: requestId };
    const schemas = {
      request: StopRequest,
      response: StopResponse,
    };
    await this.send({ methodName: "stop", data, schemas });
  }
}

const StopRequest = Schema.Object({
  subscription_id: Schema.Number,
});

const StopResponse = Schema.Object({
  status: Schema.String,
});
