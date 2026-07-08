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

import base64
import functools
import io
import logging
import os
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, List, Optional

from PIL import Image
from prometheus_client import Counter, Summary
from siglip2_triton_client import SigLIP2, SigLIP2Config

from ..models import Prediction

logger = logging.getLogger(__name__)

USE_METRICS = os.getenv("USE_METRICS", "True").lower() == "true"

_metric_instances: dict = {}


class BaseEmbeddingInterface(ABC):
    def __init__(self, service_name: str, use_metrics: bool = USE_METRICS):
        self.logger = logging.getLogger(self.__class__.__name__)

        # Prometheus metrics — cached by service_name to avoid duplicate registration
        # across multiple app instances (e.g. parametrized test sessions).
        self.use_metrics = use_metrics
        self.inference_time: Optional[Summary] = None
        self.request_counter: Optional[Counter] = None
        if self.use_metrics:
            if service_name not in _metric_instances:
                _metric_instances[service_name] = (
                    Summary(
                        "%s_inference_time_seconds" % service_name,
                        "Time spent processing %s embeddings" % service_name,
                    ),
                    Counter(
                        "%s_requests_total" % service_name,
                        "Total number of %s embedding requests" % service_name,
                        ["method", "status"],
                    ),
                )
            self.inference_time, self.request_counter = _metric_instances[service_name]

    def track_inference_metrics(method_name: str):
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(self, *args, **kwargs):
                start_time = time.time()

                # Log input
                self.logger.debug("%s input - args: %s, kwargs: %s", method_name, args, kwargs)

                try:
                    # Execute the method
                    result = await func(self, *args, **kwargs)

                    # Calculate execution time
                    execution_time = time.time() - start_time

                    # Update Prometheus metrics
                    if self.use_metrics and self.inference_time and self.request_counter:
                        self.inference_time.observe(execution_time)
                        self.request_counter.labels(method=method_name, status="success").inc()

                    # Log output and execution time
                    self.logger.debug("%s output: %s", method_name, result)
                    self.logger.debug("%s execution time: %.4fs", method_name, execution_time)

                    return result

                except Exception as e:
                    # Update error metrics
                    if self.use_metrics and self.request_counter:
                        self.request_counter.labels(method=method_name, status="error").inc()
                    self.logger.error("Error in %s: %s", method_name, str(e))
                    raise

            return wrapper

        return decorator

    @track_inference_metrics("get_text_embeddings")
    async def get_text_embeddings(self, text: str, field_config: Any = None) -> list[float]:
        return await self._get_text_embeddings_impl(text, field_config)

    @track_inference_metrics("get_image_embeddings")
    async def get_image_embeddings(self, images: list[str], field_config: Any = None) -> list[list[float]]:
        return await self._get_image_embeddings_impl(images, field_config)

    @track_inference_metrics("get_predictions")
    async def get_predictions(self, embeddings: List[List[float]]) -> Optional[List[List[Prediction]]]:
        return await self._get_predictions_impl(embeddings)

    @abstractmethod
    async def _get_text_embeddings_impl(self, text: str, field_config: Any = None) -> list[float]:
        pass

    @abstractmethod
    async def _get_image_embeddings_impl(self, images: list[str], field_config: Any = None) -> list[list[float]]:
        pass

    @abstractmethod
    async def _get_predictions_impl(self, embeddings: List[List[float]]) -> Optional[List[List[Prediction]]]:
        pass


class USDSearchEmbeddingClient(BaseEmbeddingInterface):
    def __init__(
        self,
        config: SigLIP2Config,
    ):
        super().__init__(service_name="usd_search_triton")
        self._siglip2_client = SigLIP2(clip_config=config)

    async def _get_predictions_impl(self, embeddings: List[List[float]]) -> Optional[List[List[Prediction]]]:
        logger.warning("Predictions functionality is deprecated")
        return None

    async def _get_text_embeddings_impl(self, text: str, field_config: Any = None) -> list[float]:
        result = await self._siglip2_client.aembed_texts([text])
        return result.tolist()[0]

    async def _get_image_embeddings_impl(
        self, images: list[str | bytes], field_config: Any = None
    ) -> list[list[float]]:
        pil_images = []
        for image in images:
            if isinstance(image, (bytes, bytearray)):
                pil_image = Image.open(io.BytesIO(image))
            elif image.startswith("data:image/"):
                st = image.find(";base64,")
                b64_data = image[st + 8 :]
                pil_image = Image.open(io.BytesIO(base64.b64decode(b64_data.encode())))
            else:
                pil_image = Image.open(io.BytesIO(base64.b64decode(image.encode())))
            if pil_image.mode != "RGB":
                pil_image = pil_image.convert("RGB")
            pil_images.append(pil_image)
        result = await self._siglip2_client.aembed_images(pil_images)
        return result.tolist()


class EmbeddingType(str, Enum):
    SIGLIP2_EMBEDDING = "siglip2_embedding"
