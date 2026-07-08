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
import hashlib
import logging
from collections import OrderedDict
from typing import Awaitable, Callable, List, Optional, Tuple

from llm_client import Validation
from llm_client.exceptions import LLMException, ParsingException
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from .config import ValidationSettings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class VLMServiceUnavailable(RuntimeError):
    """Raised when the underlying VLM provider is unreachable (network error,
    DNS failure, connection refused, TLS error, etc.). Distinguished from
    per-call failures (timeouts, parse errors) so the endpoint layer can
    map it to HTTP 503 — which the Explorer's reactive 503 handler treats
    as a batch-level signal to surface the "VLM unavailable" banner.
    """


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
    """Wrapper around llm_client.Validation for validating search results."""

    def __init__(self, settings: ValidationSettings) -> None:
        self.settings = settings
        self._validation = Validation(config=settings.to_validation_config())
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)
        # Verdict memoization: a deterministic judge re-asked the same question
        # (same model, query, and asset images) returns the same verdict, so
        # duplicate hits (deduplicate_by_hash=false), pagination overlaps, and
        # re-runs of the same query skip the VLM round-trip entirely.
        self._verdict_cache: "OrderedDict[Tuple, QueryRelevanceValidationResult]" = OrderedDict()
        # In-flight coalescing: concurrent validations of the same key (e.g. the
        # same asset listed twice in one result page) share a single task.
        self._inflight: dict = {}

    def make_cache_key(
        self,
        query_text: Optional[str],
        query_image: Optional[str],
        image_ids: List[str],
    ) -> Tuple:
        """Verdict identity: model + query + the asset's image identity.

        ``query_image`` can be a large base64 payload — hash it instead of
        keying on the raw string. The model id is part of the key so swapping
        ``USDSEARCH_VISION_VALIDATION_MODEL`` naturally invalidates old verdicts.
        """
        # Not a security hash — just a compact, collision-unlikely cache-key
        # digest of the (possibly large base64) image. usedforsecurity=False
        # documents that intent and keeps it FIPS-friendly / off SAST radar.
        image_digest = hashlib.sha1(query_image.encode(), usedforsecurity=False).hexdigest() if query_image else ""
        # Normalize so blank/whitespace/None queries share one cache identity.
        normalized_query = (query_text or "").strip()
        return (self.settings.model, normalized_query, image_digest, tuple(image_ids))

    def _cache_get(self, key: Tuple) -> Optional[QueryRelevanceValidationResult]:
        if key in self._verdict_cache:
            self._verdict_cache.move_to_end(key)
            return self._verdict_cache[key]
        return None

    def _cache_put(self, key: Tuple, value: QueryRelevanceValidationResult) -> None:
        if self.settings.cache_size <= 0:
            return
        self._verdict_cache[key] = value
        self._verdict_cache.move_to_end(key)
        while len(self._verdict_cache) > self.settings.cache_size:
            self._verdict_cache.popitem(last=False)

    async def validate_once(
        self,
        key: Tuple,
        supplier: Callable[[], Awaitable[Optional[QueryRelevanceValidationResult]]],
    ) -> Optional[QueryRelevanceValidationResult]:
        """Memoized, request-coalesced validation.

        ``supplier`` (typically image loading + the VLM call) runs at most once
        per key across concurrent callers; successful verdicts are LRU-cached.
        ``None`` results (timeouts, parse failures, missing images) are NOT
        cached so transient failures retry on the next request.
        """
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(supplier())
            self._inflight[key] = task
            task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        result = await asyncio.shield(task)
        if result is not None:
            self._cache_put(key, result)
        return result

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

        # Defensive: callers normalize blank text to None in validate_results,
        # but never send an empty query to the VLM if it slips through here.
        if not query_text and not query_image:
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
                # Per-call timeout — let the endpoint surface 504; client retries.
                logger.warning("Validation timed out for %d image(s)", len(images))
                return None
            except ParsingException as e:
                # Per-call parse failure (VLM produced unparseable output). Not
                # a service-down condition — return None so this hit errors out
                # but the batch continues.
                logger.error(f"VLM response parse error: {e}")
                return None
            except LLMException as e:
                # Underlying provider call failed (connection refused, DNS,
                # TLS, HTTP 5xx from the provider). This typically indicates
                # the VLM service itself is unreachable — propagate so the
                # endpoint can return 503 and the client tears down the
                # batch instead of hammering through dozens of failing hits.
                logger.error(f"VLM service error: {e}")
                raise VLMServiceUnavailable(str(e)) from e

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
        # Normalize a whitespace-only text query to None: a blank query carries
        # no signal, and passing raw whitespace to the VLM yields arbitrary
        # verdicts ("noise"). With nothing left to validate against, skip.
        if query_text is not None:
            query_text = query_text.strip() or None
        if query_text is None and query_image is None:
            logger.warning(
                "Skipping VLM validation for %d asset(s): blank query " "(no text after stripping and no query image)",
                len(image_sets),
            )
            return [None] * len(image_sets)

        with tracer.start_as_current_span(
            "validation.validate_results", kind=SpanKind.INTERNAL
        ) as validate_results_span:
            validate_results_span.set_attribute("assets_count", len(image_sets))
            validate_results_span.set_attribute("total_images", sum(len(imgs) for imgs in image_sets))

            tasks = [self._validate_single(query_text, query_image, images) for images in image_sets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Service-unavailable signal: if ANY sibling task hit a
            # service-down condition, the provider is effectively down for
            # the whole batch. Propagate so the endpoint can 503-map.
            for result in results:
                if isinstance(result, VLMServiceUnavailable):
                    raise result
            # Remaining exceptions are per-call failures — surface as None.
            validated_results: List[Optional[QueryRelevanceValidationResult]] = []
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Validation task failed: {result}")
                    validated_results.append(None)
                else:
                    validated_results.append(result)

            return validated_results
