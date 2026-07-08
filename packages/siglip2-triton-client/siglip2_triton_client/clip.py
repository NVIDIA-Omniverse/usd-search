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

"""High-level SigLIP2 embedding client.

A convenience wrapper over the low-level Triton clients in this package: batched
sync/async ``embed_images`` / ``embed_texts`` with client-side preprocessing by
default (pass ``use_ensemble_model=True`` for server-side preprocessing), plus
``ping``. Requires the ``preprocessing`` extra (pillow + transformers).

Previously lived in ``vision_endpoint.clip_triton_client``; moved here so the
embedding stack has no dependency on the LLM/VLM client.
"""

# standard modules
import asyncio
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

# third party modules
import numpy as np
from numpy.typing import NDArray
from PIL import Image
from pydantic import Field
from pydantic_settings import BaseSettings

# local / proprietary modules
from .async_client import (
    AsyncTritonEnsembleImageClient,
    AsyncTritonEnsembleTextClient,
    AsyncTritonPreprocessedImageClient,
    AsyncTritonPreprocessedTextClient,
)
from .client import (
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
    TritonPreprocessedImageClient,
    TritonPreprocessedTextClient,
)
from .config import TritonClientSettings

logger = logging.getLogger(__name__)


class CLIPException(Exception):
    pass


class CLIPService(str, Enum):
    siglip2 = "siglip2"


class CLIPConfig(BaseSettings):
    triton_server_url: str = Field(default="0.0.0.0:8001", description="GRPC Triton server endpoint")
    triton_server_auth_token: Optional[str] = Field(default=None, description="Authentication token for Triton server")
    triton_server_ssl: Optional[bool] = Field(default=False, description="SSL for Triton server")
    triton_server_headers: Optional[dict] = Field(default=None, description="Metadata headers for Triton server")
    max_workers: int = Field(default=8, description="Max concurrent workers for async image embedding")
    batch_size: int = Field(default=4, description="Max images per inference request batch")

    class Config:
        env_prefix = "clip_"


class BaseCLIP(ABC):
    def __init__(self, clip_service: CLIPService):
        self._clip_service = clip_service

    @property
    def clip_service(self) -> CLIPService:
        return self._clip_service

    @property
    @abstractmethod
    def config(self) -> CLIPConfig:
        raise NotImplementedError

    @property
    @abstractmethod
    def image_client(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def text_client(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def async_image_client(self):
        raise NotImplementedError

    @property
    @abstractmethod
    def async_text_client(self):
        raise NotImplementedError

    def embed_images(
        self,
        images: list[Image.Image],
        use_ensemble_model: bool = False,
        batch_size: Optional[int] = None,
    ) -> NDArray[np.float32]:
        try:
            _batch_size = batch_size or self.config.batch_size

            if use_ensemble_model:
                ensemble_embeddings = []
                for image in images:
                    image = np.expand_dims(image, axis=0)
                    result = self.ensemble_image_client.predict(image)
                    ensemble_embeddings.append(result[0])
                return np.array(ensemble_embeddings)

            chunks = [images[i : i + _batch_size] for i in range(0, len(images), _batch_size)]
            results = [self.image_client.predict(chunk) for chunk in chunks]
            return np.concatenate(results)
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CLIPException(f"{self._clip_service} image embedding failed: {str(e)}") from e

    def embed_texts(self, texts: list[str], use_ensemble_model: bool = False) -> NDArray[np.float32]:
        try:
            if use_ensemble_model:
                return self.ensemble_text_client.predict(texts)

            return self.text_client.predict(texts)
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CLIPException(f"{self._clip_service} text embedding failed: {str(e)}") from e

    async def aembed_images(
        self,
        images: list[Image.Image],
        use_ensemble_model: bool = False,
        max_workers: Optional[int] = None,
        batch_size: Optional[int] = None,
    ) -> NDArray[np.float32]:
        try:
            _max_workers = max_workers or self.config.max_workers
            _batch_size = batch_size or self.config.batch_size
            semaphore = asyncio.Semaphore(_max_workers)

            if use_ensemble_model:
                await self.async_ensemble_image_client.connect()

                async def embed_ensemble_chunk(
                    chunk: list[NDArray[np.uint8]],
                ) -> NDArray[np.float32]:
                    async with semaphore:
                        embeddings = []
                        for image in chunk:
                            batched_image = np.expand_dims(image, axis=0)
                            result = await self.async_ensemble_image_client.predict(batched_image)
                            embeddings.append(result[0])
                        return np.array(embeddings)

                chunks = [images[i : i + _batch_size] for i in range(0, len(images), _batch_size)]
                results = await asyncio.gather(*[embed_ensemble_chunk(c) for c in chunks])
                return np.concatenate(results)

            await self.async_image_client.connect()
            chunks = [images[i : i + _batch_size] for i in range(0, len(images), _batch_size)]

            async def embed_chunk(chunk: list[Image.Image]) -> NDArray[np.float32]:
                async with semaphore:
                    return await self.async_image_client.predict(chunk)

            results = await asyncio.gather(*[embed_chunk(c) for c in chunks])
            return np.concatenate(results)
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CLIPException(f"{self._clip_service} async image embedding failed: {str(e)}") from e

    async def aembed_texts(self, texts: list[str], use_ensemble_model: bool = False) -> NDArray[np.float32]:
        try:
            if use_ensemble_model:
                await self.async_ensemble_text_client.connect()
                return await self.async_ensemble_text_client.predict(texts)

            await self.async_text_client.connect()
            return await self.async_text_client.predict(texts)
        except Exception as e:
            logger.error(e, exc_info=True)
            raise CLIPException(f"{self._clip_service} async text embedding failed: {str(e)}") from e

    def ping(self) -> bool:
        try:
            return self.image_client.ping() and self.text_client.ping()
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def aping(self) -> bool:
        try:
            await self.async_image_client.connect()
            await self.async_text_client.connect()
            image_ready = await self.async_image_client.ping()
            text_ready = await self.async_text_client.ping()
            return image_ready and text_ready
        except Exception as e:
            logger.error(e, exc_info=True)
            return False

    async def aclose(self) -> None:
        """Close async gRPC channels to release resources."""
        clients = [self.async_image_client, self.async_text_client]
        if hasattr(self, "_async_ensemble_image_client"):
            clients.append(self._async_ensemble_image_client)
        if hasattr(self, "_async_ensemble_text_client"):
            clients.append(self._async_ensemble_text_client)
        for client in clients:
            try:
                await client.close()
            except Exception as e:
                logger.warning("Error closing async client: %s", e)


class SigLIP2Config(CLIPConfig):
    ensemble_image_model_name: str = Field(
        default="ensemble_image_model", description="Name of the image ensemble model"
    )
    image_model_name: str = Field(default="siglip2_vision_encoder_onnx", description="Name of the image model")
    text_model_name: str = Field(default="ensemble_text_model", description="Name of the text ensemble model")
    text_encoder_model_name: str = Field(
        default="siglip2_text_encoder_onnx",
        description="Name of the direct text encoder model",
    )

    class Config:
        env_prefix = "siglip2_"


class SigLIP2(BaseCLIP):
    """SigLIP2 client with preprocessed (client-side) and ensemble (server-side) paths.

    By default image/text embedding use client-side preprocessing; pass
    ``use_ensemble_model=True`` to any embed call for the server-side ensemble.
    """

    def __init__(self, clip_config: Optional[SigLIP2Config] = None):
        if clip_config is None:
            clip_config = SigLIP2Config()

        super().__init__(clip_service=CLIPService.siglip2)

        self._config = clip_config

        # Settings for ensemble clients (server-side preprocessing)
        ensemble_image_settings = TritonClientSettings(
            triton_server_url=clip_config.triton_server_url,
            triton_server_auth_token=clip_config.triton_server_auth_token,
            triton_server_ssl=clip_config.triton_server_ssl,
            triton_server_headers=clip_config.triton_server_headers,
            model_name=clip_config.ensemble_image_model_name,
            request_input="raw_image",
            request_output="image_embeds",
            infer_datatype="UINT8",
        )

        ensemble_text_settings = TritonClientSettings(
            triton_server_url=clip_config.triton_server_url,
            triton_server_auth_token=clip_config.triton_server_auth_token,
            triton_server_ssl=clip_config.triton_server_ssl,
            triton_server_headers=clip_config.triton_server_headers,
            model_name=clip_config.text_model_name,
            request_input="text",
            request_output="embeddings",
            infer_datatype="BYTES",
        )

        # Settings for preprocessed clients (client-side preprocessing)
        preprocessed_image_settings = TritonClientSettings(
            triton_server_url=clip_config.triton_server_url,
            triton_server_auth_token=clip_config.triton_server_auth_token,
            triton_server_ssl=clip_config.triton_server_ssl,
            triton_server_headers=clip_config.triton_server_headers,
            model_name=clip_config.image_model_name,
            request_input="pixel_values",
            request_output="image_embeds",
            infer_datatype="FP32",
        )

        preprocessed_text_settings = TritonClientSettings(
            triton_server_url=clip_config.triton_server_url,
            triton_server_auth_token=clip_config.triton_server_auth_token,
            triton_server_ssl=clip_config.triton_server_ssl,
            triton_server_headers=clip_config.triton_server_headers,
            model_name=clip_config.text_encoder_model_name,
            request_input="input_ids",
            request_output="embeddings",
            infer_datatype="INT64",
        )

        # Ensemble clients (server-side preprocessing)
        self._ensemble_image_client = TritonEnsembleImageClient(settings=ensemble_image_settings)
        self._async_ensemble_image_client = AsyncTritonEnsembleImageClient(settings=ensemble_image_settings)
        self._ensemble_text_client = TritonEnsembleTextClient(settings=ensemble_text_settings)
        self._async_ensemble_text_client = AsyncTritonEnsembleTextClient(settings=ensemble_text_settings)

        # Preprocessed clients (client-side preprocessing — default path)
        self._image_client = TritonPreprocessedImageClient(settings=preprocessed_image_settings)
        self._async_image_client = AsyncTritonPreprocessedImageClient(settings=preprocessed_image_settings)
        self._text_client = TritonPreprocessedTextClient(settings=preprocessed_text_settings)
        self._async_text_client = AsyncTritonPreprocessedTextClient(settings=preprocessed_text_settings)

    @property
    def config(self) -> SigLIP2Config:
        return self._config

    @property
    def image_client(self):
        return self._image_client

    @property
    def ensemble_image_client(self):
        return self._ensemble_image_client

    @property
    def ensemble_text_client(self):
        return self._ensemble_text_client

    @property
    def text_client(self):
        return self._text_client

    @property
    def async_image_client(self):
        return self._async_image_client

    @property
    def async_ensemble_image_client(self):
        return self._async_ensemble_image_client

    @property
    def async_ensemble_text_client(self):
        return self._async_ensemble_text_client

    @property
    def async_text_client(self):
        return self._async_text_client
