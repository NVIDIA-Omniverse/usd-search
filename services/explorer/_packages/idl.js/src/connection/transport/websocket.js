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

import Stream from "../../stream";
import Client, { ClientFactory, TransportError, TransportName } from "./index";
import Marshaller, {
  MarshallerFactory,
  MarshallerName,
} from "../marshallers/marshaller";
import JSONSerializer from "../serializers/json";
import { SerializerFactory, SerializerName } from "../serializers";

export const Errors = {
  UnexpectedMessage: 0x01,
  UnknownInterface: 0x02,
  UnknownMethod: 0x03,
  InvalidParams: 0x04,
  InternalServerError: 0xff,
  ServiceError: 0x100,
};

export default class WebSocketClient extends Client {
  static [TransportName] = "sows";

  static register() {
    for (const marshallerType of Object.values(MarshallerFactory.marshallers)) {
      for (const serializerType of Object.values(
        SerializerFactory.serializers,
      )) {
        for (const usingSSL of ["true", "false"]) {
          ClientFactory.register(WebSocketClient, {
            marshaller: marshallerType[MarshallerName],
            serializer: serializerType[SerializerName],
            ssl: usingSSL,
          });
          ClientFactory.register(WebSocketClient, {
            marshaller: marshallerType[MarshallerName],
            serializer: serializerType[SerializerName],
            ssl: usingSSL,
            supports_path: "true",
          });
        }
      }
    }
  }

  static create({ name, params: paramsJSON, meta = {}, accessToken }) {
    if (name !== WebSocketClient[TransportName]) {
      throw new Error(`Invalid transport name ${name}.`);
    }

    const params = JSON.parse(paramsJSON);
    const {
      marshaller: marshallerName,
      serializer: serializerName,
      ssl,
    } = meta;

    const options = {};
    options.marshaller = MarshallerFactory.create(
      marshallerName,
      serializerName,
    );

    const path = params.path || "";
    const scheme = ssl === "true" ? "wss" : "ws";
    options.uri = `${scheme}://${params.host}:${params.port}${path}`;
    if (accessToken) {
      options.uri += `?access_token=${accessToken}`;
    }

    return new WebSocketClient(options);
  }

  constructor({ uri, marshaller = new Marshaller(new JSONSerializer()) }) {
    super();
    this.uri = uri;
    this.marshaller = marshaller;
    this.ws = null;
    this.requests = {};
    this.requestId = 0;
  }

  prepare() {
    return new Promise(async (resolve, reject) => {
      try {
        await super.prepare();
        this.ws = new WebSocket(this.uri);
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

  async close() {
    this.ws.close();
    for (const request of Object.values(this.requests)) {
      await request.responses.close();
    }
    await super.close();
  }

  async call({
    interfaceName,
    methodName,
    request: data,
    schemas: { request, response },
  }) {
    const responses = await this.send({
      interfaceName,
      methodName,
      data,
      schemas: { request, response },
    });
    return await responses.read();
  }

  async callMany({
    interfaceName,
    methodName,
    request: data,
    schemas: { request, response },
  }) {
    return await this.send({
      interfaceName,
      methodName,
      data,
      schemas: { request, response },
    });
  }

  async send({ interfaceName, methodName, data, schemas }) {
    if (!this.prepared) {
      throw new TransportError("You should call prepare() first.");
    }

    const [params, fields] = await this.marshaller.marshal(
      data,
      schemas.request,
    );
    const request = {};
    request.id = ++this.requestId;
    request.buffer = new Stream();
    request.messages = new Stream();
    request.responses = new Stream();
    request.responses.once("read", async () => this.process(request.id));

    const close = async () => {
      await end();
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(new Stop({ requestId: request.id }).pack());
      }
    };

    const end = async () => {
      request.responses.off("close", close);
      request.responses.off("end", end);
      await request.messages.end();
      delete this.requests[request.id];
    };

    request.responses.once("close", close);
    request.responses.once("end", end);
    request.schemas = schemas;

    this.requests[request.id] = request;

    let streaming = false;
    for (const field of fields) {
      const buffer = field.get();
      while (buffer) {
        const content = await buffer.read();
        if (content === Stream.END) {
          break;
        }
        if (!streaming) {
          this.ws.send(
            new StartRequest({
              requestId: request.id,
              interfaceName,
              methodName,
              params,
            }).pack(),
          );
          streaming = true;
        }

        this.ws.send(
          new ContinueRequest({
            requestId: request.id,
            buffer: content,
          }).pack(),
        );
      }
    }

    if (streaming) {
      this.ws.send(new EndRequest({ requestId: request.id }).pack());
    } else {
      this.ws.send(
        new SendRequest({
          requestId: request.id,
          interfaceName,
          methodName,
          params,
        }).pack(),
      );
    }
    return request.responses;
  }

  async receive(msg) {
    try {
      const [{ requestId, type }] = Packet.parse(msg.data);
      const request = this.requests[requestId];
      if (request) {
        await request.messages.write({ type, data: msg.data });
      }
    } catch (error) {
      this.events.emit("error", error);
      throw error;
    }
  }

  async process(requestId) {
    const request = this.requests[requestId];
    if (!request) {
      return;
    }

    do {
      const msg = await request.messages.read();
      if (msg === Stream.END) {
        break;
      }

      const { type, data } = msg;
      switch (type) {
        case ErrorResponse.TYPE:
          await this.receiveError(data);
          break;
        case SendResponse.TYPE:
        case StartResponse.TYPE:
          await this.receiveResponse(data, type);
          break;
        case ContinueResponse.TYPE:
          await this.receiveContinueResponse(data);
          break;
        case EndResponse.TYPE:
          await this.receiveEndResponse(data);
          break;
        case Done.TYPE:
          await this.receiveDone(data);
          break;
        default:
          break;
      }
    } while (true);
  }

  async receiveError(data) {
    const [error] = await ErrorResponse.parse(data);
    const request = this.requests[error.requestId];
    if (request && request.responses.status !== Stream.CLOSED) {
      await request.responses.error(
        new TransportError(error.message, error.code),
      );
    }
  }

  async receiveResponse(data, type) {
    const responseType =
      type === SendResponse.TYPE ? SendResponse : StartResponse;
    const [response] = await responseType.parse(data);
    const request = this.requests[response.requestId];

    if (!request || request.responses.status === Stream.CLOSED) {
      return;
    }

    const result = await this.marshaller.unmarshal(response.params);
    const buffer = (request.buffer = new Stream());
    for (const field of this.marshaller.introspect(
      result,
      request.schemas.response,
    )) {
      field.set(buffer);
      if (response.buffer) {
        await buffer.write(response.buffer);
      }
    }

    if (response.type === SendResponse.TYPE) {
      await buffer.end();
    }

    await request.responses.write(result);
    if (response.last) {
      await request.responses.end();
    }
  }

  async receiveContinueResponse(data) {
    const [continueResponse] = await ContinueResponse.parse(data);
    const request = this.requests[continueResponse.requestId];
    if (request && request.buffer) {
      await request.buffer.write(continueResponse.buffer);
    }
  }

  async receiveEndResponse(data) {
    const [endResponse] = await EndResponse.parse(data);
    const request = this.requests[endResponse.requestId];
    if (!request) {
      return;
    }

    if (endResponse.buffer) {
      await request.buffer.write(endResponse.buffer);
    }
    await request.buffer.end();
  }

  async receiveDone(data) {
    const [done] = await Done.parse(data);
    const request = this.requests[done.requestId];
    if (request && request.responses.status !== Stream.CLOSED) {
      await request.responses.end();
    }
  }
}

class Packet {
  constructor({ requestId }) {
    this.requestId = requestId;
    this.type = null;
  }

  static parse(buffer) {
    let offset = 0;
    const view = new DataView(buffer);
    const type = view.getUint8(0);
    offset += 1;

    const requestId = view.getUint32(1, LITTLE_ENDIAN);
    offset += 4;

    return [{ type, requestId }, offset];
  }

  pack() {
    const buffer = new ArrayBuffer(5);
    const view = new DataView(buffer);
    view.setUint8(0, this.type);
    view.setUint32(1, this.requestId, LITTLE_ENDIAN);
    return buffer;
  }
}

class Stop extends Packet {
  static TYPE = 0;

  constructor({ requestId }) {
    super({ requestId });
    this.type = Stop.TYPE;
  }
}

class SendRequest extends Packet {
  static TYPE = 1;

  constructor({ requestId, interfaceName, methodName, params, buffer = null }) {
    super({ requestId });
    this.type = SendRequest.TYPE;
    this.interfaceName = interfaceName;
    this.methodName = methodName;
    this.params = params;
    this.buffer = buffer;
  }

  pack() {
    const base = super.pack();
    const call = `${this.interfaceName}.${this.methodName}`;
    const callBuffer = new Uint8Array(new ArrayBuffer(call.length + 1));
    for (let i = 0; i < call.length; i++) {
      callBuffer[i] = call.charCodeAt(i);
    }
    callBuffer[call.length] = 0;

    const paramsLen = new Uint32Array(1);
    paramsLen[0] = this.params.byteLength;

    const buffer = new ArrayBuffer(
      base.byteLength +
        callBuffer.byteLength +
        paramsLen.byteLength +
        this.params.byteLength,
    );
    const bufferView = new Uint8Array(buffer);
    let offset = 0;

    bufferView.set(new Uint8Array(base), 0);
    offset += base.byteLength;

    bufferView.set(callBuffer, offset);
    offset += callBuffer.byteLength;

    bufferView.set(new Uint8Array(paramsLen.buffer), offset);
    offset += paramsLen.byteLength;

    bufferView.set(new Uint8Array(this.params), offset);
    return buffer;
  }
}

class StartRequest extends SendRequest {
  static TYPE = 2;

  constructor({ requestId, interfaceName, methodName, params, buffer }) {
    super({ requestId, interfaceName, methodName, params, buffer });
    this.type = StartRequest.TYPE;
  }
}

class ContinueRequest extends Packet {
  static TYPE = 3;

  constructor({ requestId, buffer }) {
    super({ requestId });
    this.type = ContinueRequest.TYPE;
    this.buffer = buffer;
  }

  pack() {
    const base = super.pack();
    const baseView = new DataView(base);

    const bufferLen = this.buffer
      ? this.buffer.byteLength + base.byteLength
      : base.byteLength;
    const buffer = new ArrayBuffer(bufferLen);
    const view = new DataView(buffer);

    for (let i = 0; i < base.byteLength; i++) {
      view.setUint8(i, baseView.getUint8(i));
    }

    let offset = base.byteLength;

    if (this.buffer) {
      const dataBufferView = new DataView(this.buffer);
      for (let i = 0; i < this.buffer.byteLength; i++) {
        view.setUint8(i + offset, dataBufferView.getUint8(i));
      }
    }
    return buffer;
  }
}

class EndRequest extends ContinueRequest {
  static TYPE = 4;

  constructor({ requestId, buffer }) {
    super({ requestId, buffer });
    this.type = EndRequest.TYPE;
  }
}

class ErrorResponse extends Packet {
  static TYPE = 0;

  constructor({ requestId, code, message }) {
    super({ requestId });
    this.type = ErrorResponse.TYPE;
    this.code = code;
    this.message = message;
  }

  static parse(buffer) {
    let [packet, offset] = Packet.parse(buffer);

    const view = new DataView(buffer);
    const code = view.getUint16(offset, LITTLE_ENDIAN);
    offset += 2;

    const messageLen = buffer.byteLength - offset;
    const messageBuffer = new Uint8Array(messageLen);
    for (let i = 0; i < messageLen; i++) {
      messageBuffer[i] = view.getUint8(i + offset);
    }

    const message = String.fromCharCode(...messageBuffer);

    offset += messageBuffer.byteLength;
    return [{ ...packet, code, message }, offset];
  }
}

class SendResponse extends Packet {
  static TYPE = 1;

  constructor({ requestId, params, last, buffer }) {
    super({ requestId });
    this.type = SendResponse.TYPE;
    this.params = params;
    this.last = last;
    this.buffer = buffer;
  }

  static parse(buffer) {
    let [packet, offset] = Packet.parse(buffer);

    const view = new DataView(buffer);
    const last = view.getUint8(offset);
    offset += 1;

    const paramsSize = view.getUint32(offset, LITTLE_ENDIAN);
    offset += 4;

    const params = new ArrayBuffer(paramsSize);
    const paramsView = new DataView(params);
    for (let i = 0; i < paramsSize; i++) {
      paramsView.setUint8(i, view.getUint8(i + offset));
    }

    offset += paramsSize;

    let bin = null;
    if (buffer.byteLength > offset) {
      bin = new ArrayBuffer(buffer.byteLength - offset);

      const binView = new DataView(bin);
      for (let i = 0; i < bin.byteLength; i++) {
        binView.setUint8(i, view.getUint8(i + offset));
      }
      offset += bin.byteLength;
    }

    return [{ ...packet, last, params, buffer: bin }, offset];
  }
}

class StartResponse extends SendResponse {
  static TYPE = 2;

  constructor({ requestId, params, last, buffer }) {
    super({ requestId, params, last, buffer });
    this.type = StartResponse.TYPE;
  }
}

class ContinueResponse extends Packet {
  static TYPE = 3;

  constructor({ requestId, buffer }) {
    super({ requestId, buffer });
    this.type = ContinueResponse.TYPE;
    this.buffer = buffer;
  }

  static parse(buffer) {
    let [packet, offset] = super.parse(buffer);

    let bin = null;
    if (buffer.byteLength > offset) {
      bin = new ArrayBuffer(buffer.byteLength - offset);

      const arr = new Uint8Array(bin);
      const bufferArray = new Uint8Array(buffer);
      for (let i = 0; i < bin.byteLength; i++) {
        arr[i] = bufferArray[i + offset];
      }
      offset += bin.byteLength;
    }

    return [{ ...packet, buffer: bin }, offset];
  }
}

class EndResponse extends ContinueResponse {
  static TYPE = 4;

  constructor({ requestId, buffer }) {
    super({ requestId, buffer });
    this.type = EndResponse.TYPE;
  }
}

class Done extends Packet {
  static TYPE = 5;

  constructor({ requestId }) {
    super({ requestId });
    this.type = Done.TYPE;
  }
}

const LITTLE_ENDIAN = true;
