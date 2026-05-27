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
import logging
from typing import Optional

# third party modules
from pydantic import Field
from siglip2_triton_client import (
    AsyncTritonEnsembleImageClient,
    AsyncTritonEnsembleTextClient,
    AsyncTritonPreprocessedImageClient,
    AsyncTritonPreprocessedTextClient,
    TritonClientSettings,
    TritonEnsembleImageClient,
    TritonEnsembleTextClient,
    TritonPreprocessedImageClient,
    TritonPreprocessedTextClient,
)

# local / proprietary modules
from .base_clip import BaseCLIP, CLIPConfig, CLIPService

logger = logging.getLogger(__name__)


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
    """SigLIP2 CLIP client with preprocessed (client-side) and ensemble (server-side) paths.

    By default, image and text embedding use client-side preprocessing (tokenization / image
    transforms happen locally before sending to the encoder model on Triton). Pass
    ``use_ensemble_model=True`` to any embed call to use the server-side ensemble instead.

    Examples::

        from vision_endpoint.clip_triton_client import SigLIP2, SigLIP2Config

        client = SigLIP2(SigLIP2Config(triton_server_url="localhost:8001"))

        # --- preprocessed (default) ------------------------------------------------
        image_emb = client.embed_images(images)                               # client-side preprocessing
        text_emb  = client.embed_texts(["a photo of a cat"])                  # client-side tokenization

        # --- ensemble (server-side) ------------------------------------------------
        image_emb = client.embed_images(images, use_ensemble_model=True)      # server-side preprocessing
        text_emb  = client.embed_texts(["a cat"], use_ensemble_model=True)    # server-side tokenization
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
