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

import asyncio
import logging
from typing import List, Optional

from opentelemetry import trace
from opentelemetry.trace import SpanKind
from vision_endpoint.validation import Validation

from .config import ValidationSettings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class QueryRelevanceValidationResult:
    """Result of VLM validation for a single search result."""

    def __init__(
        self,
        is_match: bool,
        confidence: float,
        similarity_score: int,
        reasoning: str,
    ) -> None:
        self.is_match = is_match
        self.confidence = confidence
        self.similarity_score = similarity_score
        self.reasoning = reasoning


class SearchResultValidator:
    """Wrapper around vision_endpoint.validation.Validation for validating search results."""

    def __init__(self, settings: ValidationSettings) -> None:
        self.settings = settings
        self._validation = Validation(config=settings.to_validation_config())
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)

    async def _validate_single(
        self,
        query_text: Optional[str],
        query_image: Optional[str],
        images: List[str],
    ) -> Optional[QueryRelevanceValidationResult]:
        """Validate one or more reference images of an asset against the query.

        Args:
            query_text: Text search query (combined from all text inputs)
            query_image: Base64 encoded query image (from image similarity search)
            images: List of base64 encoded reference images (multiple views of the same asset)

        Returns:
            QueryRelevanceValidationResult if successful, None on error or if images is empty
        """
        if not images:
            return None

        # Determine query and asset_caption based on available inputs
        if query_image and query_text:
            query = query_image
            asset_caption = query_text
        elif query_image:
            query = query_image
            asset_caption = None
        else:
            query = query_text
            asset_caption = None

        async with self._semaphore:
            try:
                result = await asyncio.wait_for(
                    self._validation.avalidate(
                        query=query,
                        reference_images=images,
                        return_detailed=True,
                        asset_caption=asset_caption,
                    ),
                    timeout=self.settings.timeout_seconds,
                )

                return QueryRelevanceValidationResult(
                    is_match=result.is_match,
                    confidence=result.confidence,
                    similarity_score=result.similarity_score,
                    reasoning=result.reasoning,
                )
            except asyncio.TimeoutError:
                logger.warning("Validation timed out for %d image(s)", len(images))
                return None
            except Exception as e:
                logger.error(f"Validation error: {e}")
                return None

    async def validate_results(
        self,
        query_text: Optional[str],
        query_image: Optional[str],
        image_sets: List[List[str]],
    ) -> List[Optional[QueryRelevanceValidationResult]]:
        """Validate multiple assets against the query in parallel.

        Args:
            query_text: Text search query (combined from all text inputs)
            query_image: Base64 encoded query image (from image similarity search)
            image_sets: List of image sets, where each set contains one or more base64 images
                        representing different views of the same asset.

        Returns:
            List of QueryRelevanceValidationResult objects (None for failed validations or missing images)
        """
        with tracer.start_as_current_span(
            "validation.validate_results", kind=SpanKind.INTERNAL
        ) as validate_results_span:
            validate_results_span.set_attribute("assets_count", len(image_sets))
            validate_results_span.set_attribute("total_images", sum(len(imgs) for imgs in image_sets))

            tasks = [self._validate_single(query_text, query_image, images) for images in image_sets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Convert exceptions to None
            validated_results: List[Optional[QueryRelevanceValidationResult]] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Validation task failed: {result}")
                    validated_results.append(None)
                else:
                    validated_results.append(result)

            return validated_results
