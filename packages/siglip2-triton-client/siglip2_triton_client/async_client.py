# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# standard modules
import asyncio
import functools
import logging
from typing import Optional, Union

# third party modules
import numpy as np
import tritonclient.grpc as grpcclient
from grpc import RpcError, StatusCode, aio, ssl_channel_credentials
from numpy.typing import NDArray
from tritonclient.grpc import service_pb2, service_pb2_grpc
from tritonclient.utils import InferenceServerException

# local / proprietary modules
from .config import TritonClientSettings
from .interface import IClient, TritonClientException
from .text_tokenizer import TextTokenizer
from .utils import get_inference_request, set_infer_input_data

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {
    StatusCode.UNAVAILABLE,
    StatusCode.DEADLINE_EXCEEDED,
    StatusCode.RESOURCE_EXHAUSTED,
}


def _is_retryable(exc: Exception) -> bool:
    """Check if a gRPC error is transient and retryable."""
    if isinstance(exc, RpcError) and hasattr(exc, "code"):
        return exc.code() in _RETRYABLE_STATUS_CODES
    return False


def async_grpc_error_wrapper(coroutine):
    @functools.wraps(coroutine)
    async def wrapped(*args, **kwargs):
        self = args[0] if args else None
        max_retries = getattr(getattr(self, "settings", None), "max_retries", 0)
        base_delay = getattr(getattr(self, "settings", None), "retry_base_delay", 0.1)

        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return await coroutine(*args, **kwargs)
            except (RpcError, InferenceServerException) as exc:
                last_exc = exc
                if attempt < max_retries and _is_retryable(exc):
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "Retryable error on %s (attempt %d/%d), retrying in %.2fs: %s",
                        coroutine.__name__,
                        attempt + 1,
                        max_retries + 1,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
                else:
                    break
        raise TritonClientException(
            f"RPC call to {coroutine.__name__} failed after {max_retries + 1} attempt(s): {last_exc}"
        ) from last_exc

    return wrapped


class AsyncGRPCTritonClient(IClient):
    def __init__(self, settings: TritonClientSettings, print_response: bool = False):
        self.settings = settings
        self.model_name = settings.model_name
        self.model_version = settings.model_version
        self.request_input = settings.request_input
        self.request_output = grpcclient.InferRequestedOutput(name=settings.request_output)
        self.infer_datatype = settings.infer_datatype
        self.print_response = print_response
        self._channel: Optional[aio.Channel] = None
        self._stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None

    async def connect(self) -> None:
        """Create a persistent gRPC channel and stub."""
        if self._channel is not None:
            return
        if self.settings.triton_server_ssl:
            creds = ssl_channel_credentials()
            self._channel = aio.secure_channel(self.settings.triton_server_url, creds)
        else:
            self._channel = aio.insecure_channel(self.settings.triton_server_url)
        self._stub = service_pb2_grpc.GRPCInferenceServiceStub(self._channel)

    async def close(self) -> None:
        """Close the persistent gRPC channel."""
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _get_stub(
        self, stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None
    ) -> service_pb2_grpc.GRPCInferenceServiceStub:
        """Get the stub to use, preferring an explicitly passed one, then the persistent one."""
        if stub is not None:
            return stub
        if self._stub is not None:
            return self._stub
        raise TritonClientException(
            "No gRPC connection available. Call connect() or use 'async with' context manager first."
        )

    @property
    def metadata(self) -> Optional[list[tuple[str, str]]]:
        metadata = []
        if self.settings.triton_server_headers is not None:
            metadata = [(k, v) for k, v in self.settings.triton_server_headers.items()]
        if self.settings.triton_server_auth_token is not None:
            metadata.append(("authorization", f"Bearer {self.settings.triton_server_auth_token}"))

        if len(metadata) == 0:
            return None
        return metadata

    @async_grpc_error_wrapper
    async def infer(
        self,
        inputs: grpcclient.InferInput,
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
        timeout: Optional[float] = None,
    ) -> grpcclient.InferResult:
        active_stub = self._get_stub(stub)
        request = get_inference_request(
            model_name=self.model_name,
            model_version=self.model_version,
            inputs=[inputs],
            outputs=[self.request_output],
            timeout=timeout,
            request_id="",
            sequence_id=0,
            sequence_start=0,
            sequence_end=0,
            priority=0,
            parameters=None,
        )
        response = await active_stub.ModelInfer(request, metadata=self.metadata)
        return grpcclient.InferResult(response)

    async def _request(
        self,
        inputs: NDArray[np.float32],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> grpcclient.InferResult:
        inputs = self.set_infer_input(inputs)
        return await self.infer(inputs, stub=stub)

    @async_grpc_error_wrapper
    async def ping(self, stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None) -> bool:
        active_stub = self._get_stub(stub)
        request = service_pb2.ModelMetadataRequest(name=self.model_name)
        response = await active_stub.ModelReady(request, metadata=self.metadata)
        return response.ready

    @async_grpc_error_wrapper
    async def get_model(
        self,
        model_name: Optional[str] = None,
        model_version: Optional[str] = None,
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ):
        if model_name is None:
            model_name = self.model_name
        if model_version is None:
            model_version = self.model_version
        active_stub = self._get_stub(stub)
        request = service_pb2.ModelMetadataRequest(name=model_name, version=model_version)
        response = await active_stub.ModelMetadata(request, metadata=self.metadata)
        return response


class AsyncTritonImageClient(AsyncGRPCTritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        img_size: int = 384,
    ) -> None:
        if settings is None:
            settings = TritonClientSettings(
                model_name="siglip2_vision_encoder_onnx",
                request_input="pixel_values",
                request_output="image_embeds",
                infer_datatype="FP32",
            )
        super().__init__(settings)
        self.img_size = img_size

    def set_infer_input(self, images: NDArray[np.float32]) -> grpcclient.InferInput:
        N = images.shape[0]
        input_images = grpcclient.InferInput(
            name=self.request_input,
            shape=[N, 3, self.img_size, self.img_size],
            datatype=self.infer_datatype,
        )
        set_infer_input_data(input_images, images)
        return input_images

    async def predict(
        self,
        images: NDArray[np.float32],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        response = await self._request(inputs=images, stub=stub)
        return response.as_numpy(self.request_output.name())


class AsyncTritonTextClient(AsyncGRPCTritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        max_length: int = 64,
    ) -> None:
        if settings is None:
            settings = TritonClientSettings(
                model_name="siglip2_text_encoder_onnx",
                request_input="input_ids",
                request_output="embeddings",
                infer_datatype="INT64",
            )
        super().__init__(settings)
        self.max_length = max_length

    def set_infer_input(self, input_ids: NDArray[np.int64]) -> grpcclient.InferInput:
        N = input_ids.shape[0]
        infer_input = grpcclient.InferInput(
            name=self.request_input,
            shape=[N, self.max_length],
            datatype=self.infer_datatype,
        )
        set_infer_input_data(infer_input, input_ids)
        return infer_input

    async def predict(
        self,
        input_ids: NDArray[np.int64],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        response = await self._request(inputs=input_ids, stub=stub)
        return response.as_numpy(self.request_output.name())


class AsyncTritonEnsembleImageClient(AsyncGRPCTritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="ensemble_image_model",
                request_input="raw_image",
                request_output="image_embeds",
                infer_datatype="UINT8",
            )
        super().__init__(settings)

    def set_infer_input(self, images: NDArray[np.uint8]) -> grpcclient.InferInput:
        input_images = grpcclient.InferInput(
            name=self.request_input,
            shape=images.shape,
            datatype=self.infer_datatype,
        )
        set_infer_input_data(input_images, images)
        return input_images

    async def predict(
        self,
        images: NDArray[np.uint8],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        response = await self._request(inputs=images, stub=stub)
        return response.as_numpy(self.request_output.name())


class AsyncTritonEnsembleTextClient(AsyncGRPCTritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="ensemble_text_model",
                request_input="text",
                request_output="embeddings",
                infer_datatype="BYTES",
            )
        super().__init__(settings)

    def set_infer_input(self, texts: NDArray[np.bytes_]) -> grpcclient.InferInput:
        input_texts = grpcclient.InferInput(
            name=self.request_input,
            shape=texts.shape,
            datatype=self.infer_datatype,
        )
        set_infer_input_data(input_texts, texts)
        return input_texts

    async def predict(
        self,
        texts: list[str],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        texts = np.array([[str(text).encode("utf-8")] for text in texts])
        response = await self._request(inputs=texts, stub=stub)
        return response.as_numpy(self.request_output.name())


class AsyncTritonPreprocessedImageClient(AsyncTritonImageClient):
    """Async image client with built-in client-side preprocessing.

    Accepts raw PIL images or numpy arrays, preprocesses them locally,
    and sends the result directly to the vision encoder.

    Requires the ``preprocessing`` extra: ``pip install siglip2-triton-client[preprocessing]``

    Example::

        async with AsyncTritonPreprocessedImageClient() as client:
            embeddings = await client.predict(Image.open("photo.jpg"))
    """

    def __init__(
        self,
        settings: TritonClientSettings = None,
        img_size: int = 384,
    ) -> None:
        super().__init__(settings, img_size)
        # local / proprietary modules
        from .image_preprocessing import ImagePreprocessor

        self.preprocessor = ImagePreprocessor(size=(img_size, img_size))

    async def predict(
        self,
        images,
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        pixel_values = self.preprocessor(images)
        return await super().predict(pixel_values, stub=stub)


class AsyncTritonPreprocessedTextClient(AsyncTritonTextClient):
    """Async text client with built-in client-side tokenization.

    Accepts raw text strings, tokenizes them locally,
    and sends the result directly to the text encoder.

    Example::

        async with AsyncTritonPreprocessedTextClient() as client:
            embeddings = await client.predict(["a photo of a cat"])
    """

    def __init__(
        self,
        settings: TritonClientSettings = None,
        max_length: int = 64,
    ) -> None:
        super().__init__(settings, max_length)
        self.tokenizer = TextTokenizer(max_length=max_length)

    async def predict(
        self,
        texts: Union[str, list[str]],
        stub: Optional[service_pb2_grpc.GRPCInferenceServiceStub] = None,
    ) -> NDArray[np.float32]:
        input_ids = self.tokenizer(texts)
        return await super().predict(input_ids, stub=stub)
