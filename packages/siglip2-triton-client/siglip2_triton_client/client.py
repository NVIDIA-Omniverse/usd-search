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
import functools
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Union

# third party modules
import numpy as np
import tritonclient.grpc as grpcclient
from grpc import RpcError, StatusCode, ssl_channel_credentials
from numpy.typing import NDArray
from tritonclient.utils import InferenceServerException

# local / proprietary modules
from .config import TritonClientSettings
from .interface import IClient, TritonClientException
from .text_tokenizer import TextTokenizer
from .utils import set_infer_input_data

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


def grpc_error_wrapper(coroutine):
    @functools.wraps(coroutine)
    def wrapped(*args, **kwargs):
        self = args[0] if args else None
        max_retries = getattr(getattr(self, "settings", None), "max_retries", 0)
        base_delay = getattr(getattr(self, "settings", None), "retry_base_delay", 0.1)

        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return coroutine(*args, **kwargs)
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
                    time.sleep(delay)
                else:
                    break
        raise TritonClientException(
            f"RPC call to {coroutine.__name__} failed after {max_retries + 1} attempt(s): {last_exc}"
        ) from last_exc

    return wrapped


class TritonClient(IClient, ABC):
    def __init__(
        self,
        settings: TritonClientSettings,
        print_response: bool = False,
    ):
        if settings.triton_server_ssl:
            creds = ssl_channel_credentials()

            self.inference_server_client = grpcclient.InferenceServerClient(
                url=settings.triton_server_url, ssl=True, creds=creds
            )
        else:
            self.inference_server_client = grpcclient.InferenceServerClient(url=settings.triton_server_url)
        self.settings = settings
        self.model_name = settings.model_name
        self.model_version = settings.model_version
        self.request_input = settings.request_input
        self.request_output = grpcclient.InferRequestedOutput(name=settings.request_output)
        self.infer_datatype = settings.infer_datatype
        self.print_response = print_response

    @property
    def headers(self):
        _headers = {}
        if self.settings.triton_server_headers is not None:
            _headers = {**self.settings.triton_server_headers}
        if self.settings.triton_server_auth_token is not None:
            _headers["authorization"] = f"Bearer {self.settings.triton_server_auth_token}"
        return _headers

    @abstractmethod
    def set_infer_input(self, inputs: NDArray[np.float32]) -> grpcclient.InferInput: ...

    @grpc_error_wrapper
    def infer(self, inputs: grpcclient.InferInput) -> grpcclient.InferResult:
        return self.inference_server_client.infer(
            model_name=self.model_name,
            model_version=self.model_version,
            inputs=[inputs],
            outputs=[self.request_output],
            headers=self.headers,
        )

    def _print_response(self, response: grpcclient.InferResult) -> None:
        response_d = response.get_response(as_json=True)
        response_d.pop("raw_output_contents")
        print(response_d)

    def _request(self, inputs: NDArray[np.float32]) -> grpcclient.InferResult:
        inputs = self.set_infer_input(inputs)
        response = self.infer(inputs)
        if self.print_response:
            self._print_response(response)
        return response

    @grpc_error_wrapper
    def ping(self) -> bool:
        return self.inference_server_client.is_model_ready(model_name=self.model_name, headers=self.headers)

    @grpc_error_wrapper
    def get_model(self, model_name: Optional[str] = None, model_version: Optional[str] = None):
        if model_name is None:
            model_name = self.model_name
        if model_version is None:
            model_version = self.model_version
        return self.inference_server_client.get_model_metadata(model_name=model_name, model_version=model_version)


class TritonImageClient(TritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        img_size: int = 384,
        print_response: bool = False,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="siglip2_vision_encoder_onnx",
                request_input="pixel_values",
                request_output="image_embeds",
                infer_datatype="FP32",
            )
        super().__init__(settings, print_response)
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

    def predict(self, images: NDArray[np.float32]) -> NDArray[np.float32]:
        response = self._request(inputs=images)
        return response.as_numpy(self.request_output.name())


class TritonTextClient(TritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        max_length: int = 64,
        print_response: bool = False,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="siglip2_text_encoder_onnx",
                request_input="input_ids",
                request_output="embeddings",
                infer_datatype="INT64",
            )
        super().__init__(settings, print_response)
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

    def predict(self, input_ids: NDArray[np.int64]) -> NDArray[np.float32]:
        response = self._request(inputs=input_ids)
        return response.as_numpy(self.request_output.name())


class TritonEnsembleImageClient(TritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        print_response: bool = False,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="ensemble_image_model",
                request_input="raw_image",
                request_output="image_embeds",
                infer_datatype="UINT8",
            )
        super().__init__(settings, print_response)

    def set_infer_input(self, images: NDArray[np.uint8]) -> grpcclient.InferInput:
        input_images = grpcclient.InferInput(
            name=self.request_input,
            shape=images.shape,
            datatype="UINT8",
        )
        set_infer_input_data(input_images, images)
        return input_images

    def predict(self, images: NDArray[np.uint8]) -> NDArray[np.float32]:
        response = self._request(inputs=images)
        return response.as_numpy(self.request_output.name())


class TritonEnsembleTextClient(TritonClient):
    def __init__(
        self,
        settings: TritonClientSettings = None,
        print_response: bool = False,
    ):
        if settings is None:
            settings = TritonClientSettings(
                model_name="ensemble_text_model",
                request_input="text",
                request_output="embeddings",
                infer_datatype="BYTES",
            )
        super().__init__(settings, print_response)

    def set_infer_input(self, texts: NDArray[np.bytes_]) -> grpcclient.InferInput:
        input_texts = grpcclient.InferInput(
            name=self.request_input,
            shape=texts.shape,
            datatype="BYTES",
        )
        set_infer_input_data(input_texts, texts)
        return input_texts

    def predict(self, texts: list[str]) -> NDArray[np.float32]:
        texts = np.array([[str(text).encode("utf-8")] for text in texts])
        response = self._request(inputs=texts)
        return response.as_numpy(self.request_output.name())


class TritonPreprocessedImageClient(TritonImageClient):
    """Image client with built-in client-side preprocessing.

    Accepts raw PIL images or numpy arrays, preprocesses them locally,
    and sends the result directly to the vision encoder.

    Requires the ``preprocessing`` extra: ``pip install siglip2-triton-client[preprocessing]``

    Example::

        client = TritonPreprocessedImageClient()
        embeddings = client.predict(Image.open("photo.jpg"))
        embeddings = client.predict([img1, img2, img3])
    """

    def __init__(
        self,
        settings: TritonClientSettings = None,
        img_size: int = 384,
        print_response: bool = False,
    ):
        super().__init__(settings, img_size, print_response)
        # local / proprietary modules
        from .image_preprocessing import ImagePreprocessor

        self.preprocessor = ImagePreprocessor(size=(img_size, img_size))

    def predict(self, images) -> NDArray[np.float32]:
        pixel_values = self.preprocessor(images)
        return super().predict(pixel_values)


class TritonPreprocessedTextClient(TritonTextClient):
    """Text client with built-in client-side tokenization.

    Accepts raw text strings, tokenizes them locally,
    and sends the result directly to the text encoder.

    Example::

        client = TritonPreprocessedTextClient()
        embeddings = client.predict(["a photo of a cat", "a red car"])
    """

    def __init__(
        self,
        settings: TritonClientSettings = None,
        max_length: int = 64,
        print_response: bool = False,
    ):
        super().__init__(settings, max_length, print_response)
        self.tokenizer = TextTokenizer(max_length=max_length)

    def predict(self, texts: Union[str, list[str]]) -> NDArray[np.float32]:
        input_ids = self.tokenizer(texts)
        return super().predict(input_ids)
