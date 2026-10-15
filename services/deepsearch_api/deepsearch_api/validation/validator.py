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
from typing import Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import orjson
from llm_client import Validation
from llm_client.exceptions import LLMBadRequestException, LLMException, ParsingException
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from prometheus_client import Counter

from ..cache import RedisValidationCache
from .config import ValidationSettings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

# Cache-outcome counter, labelled by tier: "l1_hit" (in-process), "l2_hit"
# (Redis), or "miss" (fell through to the VLM call). Lazily created once per
# process so the module can be imported repeatedly (tests) without a duplicate
# prometheus registration.
_CACHE_EVENTS: Optional[Counter] = None


def _cache_events() -> Counter:
    global _CACHE_EVENTS
    if _CACHE_EVENTS is None:
        _CACHE_EVENTS = Counter(
            "vlm_validation_cache_events_total",
            "VLM validation verdict cache lookups by outcome (l1_hit/l2_hit/miss).",
            ["outcome"],
        )
    return _CACHE_EVENTS


class VLMValidationError(RuntimeError):
    """Base for batch-level VLM validation failures the endpoint layer maps to HTTP.

    Carries a machine-readable ``error_type`` and whether a retry could ever
    succeed (``retryable``) so the endpoints can return a structured error body
    the Explorer can branch on (show the reason; keep transient outages "in
    progress" but resolve permanent ones to a terminal state).
    """

    error_type: str = "vlm_error"
    retryable: bool = True


class VLMServiceUnavailable(VLMValidationError):
    """Raised when the underlying VLM provider is unreachable (network error,
    DNS failure, connection refused, TLS error, HTTP 5xx, etc.). Transient —
    the endpoint layer maps it to HTTP 503, which the Explorer's reactive 503
    handler treats as a batch-level signal to surface the "VLM unavailable"
    banner and keep unfinished hits in progress (they may recover).
    """

    error_type = "unreachable"
    retryable = True


class VLMConfigurationError(VLMValidationError):
    """Raised when the provider rejects the request as unsupported/malformed
    (HTTP 4xx) — e.g. the configured model does not support ``logprobs``.

    Permanent for the current deployment config: retrying cannot succeed, so the
    endpoint layer surfaces it as a non-retryable configuration error (with the
    provider's message) rather than a transient outage. The Explorer resolves
    still-pending hits to a terminal "unavailable" state instead of leaving them
    spinning "In progress".
    """

    error_type = "configuration"
    retryable = False


class QueryRelevanceValidationResult:
    """Result of VLM validation for a single search result.

    ``similarity_score`` is the one relevance number (float 0-100); ``exact`` is
    False only for rows persisted by builds that rounded it to an integer.
    """

    # Persistent-row format marker written by :meth:`to_row`; rows without it come from earlier builds.
    ROW_VERSION = 2

    def __init__(
        self,
        is_match: bool,
        confidence: float,
        similarity_score: float,
        reasoning: str,
        exact: bool = True,
    ) -> None:
        self.is_match = is_match
        self.confidence = confidence
        self.similarity_score = float(similarity_score)
        self.reasoning = reasoning
        self.exact = exact

    def to_row(self) -> dict:
        """Plain JSON-able dict for the persistent (Redis) cache (current format, ``v: 2``)."""
        return {
            "is_match": self.is_match,
            "confidence": self.confidence,
            "similarity_score": self.similarity_score,
            "reasoning": self.reasoning,
            "v": self.ROW_VERSION,
        }

    @classmethod
    def from_row(cls, row: dict) -> Optional["QueryRelevanceValidationResult"]:
        """Rebuild from a cached row; None (a cache miss) if it is malformed or
        ``similarity_score`` is outside [0, 100] / NaN.

        Current rows (``v >= 2``) load exact; interim rows carrying a separate 0-1
        ``score`` load as ``score x 100``, exact; integer rows from before the float
        load NOT exact. See docs/vlm-validation.md, "Server-side verdict cache".
        """
        try:
            version = int(row.get("v") or 0)
            legacy_score = row.get("score")
            if version >= cls.ROW_VERSION:
                similarity_score, exact = float(row["similarity_score"]), True
            elif legacy_score is not None:
                similarity_score, exact = float(legacy_score) * 100.0, True
            else:
                similarity_score, exact = float(row["similarity_score"]), False
            if not 0.0 <= similarity_score <= 100.0:  # also rejects NaN
                return None
            return cls(
                is_match=bool(row["is_match"]),
                confidence=float(row["confidence"]),
                similarity_score=similarity_score,
                reasoning=str(row["reasoning"]),
                exact=exact,
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            return None


class SearchResultValidator:
    """Wrapper around llm_client.Validation for validating search results."""

    def __init__(
        self,
        settings: ValidationSettings,
        redis_cache: Optional[RedisValidationCache] = None,
    ) -> None:
        self.settings = settings
        self._validation = Validation(config=settings.to_validation_config())
        self._semaphore = asyncio.Semaphore(settings.max_concurrent)
        # Full config identity (model + params + prompts + schema + endpoint) as a
        # single digest. Part of every cache key so any config change — a new model,
        # a prompt edit, a temperature bump — naturally invalidates old verdicts,
        # and different configs never collide (in L1 or the shared Redis L2).
        self._config_fingerprint = self._validation.config_fingerprint()
        # L2: persistent, cross-replica verdict cache (None = L1-only).
        self._redis_cache = redis_cache
        # L1 verdict memoization: a deterministic judge re-asked the same question
        # (same config, query, and asset images) returns the same verdict, so
        # duplicate hits (deduplicate_by_hash=false), pagination overlaps, and
        # re-runs of the same query skip the VLM round-trip entirely.
        self._verdict_cache: "OrderedDict[Tuple, QueryRelevanceValidationResult]" = OrderedDict()
        # In-flight coalescing: concurrent validations of the same key (e.g. the
        # same asset listed twice in one result page) share a single task.
        self._inflight: dict = {}

    async def aprobe_logprob_capability(self, timeout: float = 10.0) -> None:
        """Best-effort startup check for ``method=logprob``: one tiny logprobs call.

        The call is sent with the method's own completion cap (``logprob_max_tokens``)
        so it exercises the same request envelope as real traffic: an operator who
        raises the cap so a lead-in token no longer hides the answer fixes the probe's
        reading along with the verdicts', instead of the probe still reporting that
        every verdict would abstain.

        Turns a per-request mystery (every validation 503s, or every verdict
        silently abstains) into a single clear boot log when the configured model
        does not support ``logprobs``, or when the log-probs it returns carry no
        readable answer (see :meth:`_report_probe_reading`). No-op for the
        generative method; never raises — a transient/unreachable provider at boot
        is left for the per-request path to surface.
        """
        if self.settings.method != "logprob":
            return
        try:
            content = await asyncio.wait_for(
                self._validation.client.ainvoke_logprobs(
                    prompt="Answer with exactly one word: Yes or No. Is the sky blue?",
                    top_logprobs=min(5, self.settings.logprob_top_logprobs),
                    max_tokens=self.settings.logprob_max_tokens,
                ),
                timeout=timeout,
            )
        except LLMBadRequestException as e:
            logger.error(
                "VLM validation is set to method=logprob, but the configured model %r does not "
                "accept logprobs (%s). Per-result validation will fail with a configuration error. "
                "Point USDSEARCH_LLM_BASE_URL / USDSEARCH_VISION_VALIDATION_MODEL at a capable "
                "endpoint, or set USDSEARCH_VISION_VALIDATION_METHOD=generative.",
                self.settings.model,
                e,
            )
            return
        except Exception as e:  # noqa: BLE001 - boot probe; any transient failure is retried per-request
            logger.warning("Log-prob capability probe did not complete at startup (will retry per-request): %s", e)
            return
        self._report_probe_reading(content)

    def _report_probe_reading(self, content: List[Dict[str, object]]) -> None:
        """Read the probe's answer the way a verdict is read, and log what a real request would do.

        Accepting the call is not enough: an endpoint that returns raw (unprocessed)
        log-probs, or a model that starts with a preamble, yields no readable answer
        mass, so every verdict would abstain and rerank/filter would silently become
        no-ops.
        """
        p_yes, _cover = self._validation._p_yes_from_logprobs(content)
        if p_yes is None:
            logger.error(
                "VLM validation method=logprob: model %r answered the capability probe, but none of the %d returned "
                "token position(s) carried Yes/No probability mass above logprob_cover_min=%.2f. Every verdict would "
                "abstain (no verdict, fail-open), so validate_results would leave results in retrieval order. "
                "Check that the endpoint returns processed (not raw) log-probs and that the model answers with "
                "Yes/No first; otherwise raise USDSEARCH_VISION_VALIDATION_LOGPROB_MAX_TOKENS or lower "
                "USDSEARCH_VISION_VALIDATION_LOGPROB_COVER_MIN.",
                self.settings.model,
                len(content or []),
                self.settings.logprob_cover_min,
            )
            return
        logger.info("logprob validation capability probe passed for model %s.", self.settings.model)

    def make_cache_key(
        self,
        query_text: Optional[str],
        query_image: Optional[str],
        image_ids: List[str],
        facts_text: str = "",
    ) -> Tuple:
        """Verdict identity: full config fingerprint + query + the asset's image identity
        (+ the asset facts its prompt carries, when there are any: see :meth:`asset_facts_text`).

        ``query_image`` can be a large base64 payload — hash it instead of
        keying on the raw string. The config fingerprint covers the model AND all
        of its parameters, prompts, and output schema, so any config change
        naturally invalidates old verdicts.
        """
        # Not a security hash — just a compact, collision-unlikely cache-key
        # digest of the (possibly large base64) image. usedforsecurity=False
        # documents that intent and keeps it FIPS-friendly / off SAST radar.
        image_digest = hashlib.sha1(query_image.encode(), usedforsecurity=False).hexdigest() if query_image else ""
        # Normalize so blank/whitespace/None queries share one cache identity.
        normalized_query = (query_text or "").strip()
        key = (self._config_fingerprint, normalized_query, image_digest, tuple(image_ids))
        # Only a prompt that carries facts gets the extra element: every other key is unchanged.
        return key + (facts_text,) if facts_text else key

    def asset_facts_text(
        self, query_text: Optional[str], query_image: Optional[str], asset_facts: Mapping[str, Optional[str]]
    ) -> str:
        """The facts text a verdict's prompt carries (a TEXT query alone), else "": it keys the cache exactly."""
        if query_image or not (query_text or "").strip():
            return ""
        return self._validation.asset_facts_text(asset_facts)

    def _redis_digest(self, key: Tuple) -> str:
        """Compact single-string Redis key digest for a cache-key tuple.

        Bounds the on-wire key length (independent of query length / image count)
        while preserving identity — the tuple already carries the full config
        fingerprint, query, and image identity.
        """
        blob = orjson.dumps(key)  # compact bytes; tuples serialize as arrays
        return hashlib.sha256(blob).hexdigest()

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

    def _needs_rejudge(self, cached: QueryRelevanceValidationResult) -> bool:
        """A logprob row persisted with a rounded integer ``similarity_score`` is a miss: one
        single-token re-judge backfills the float. The row's format marker decides, not the
        value's integrality: a saturated ``P(Yes) = 1.0`` legitimately yields ``100.0`` and must
        never be re-judged. Generative rows never are (the model generated an integer).
        """
        return not cached.exact and self.settings.method == "logprob"

    async def validate_once(
        self,
        key: Tuple,
        supplier: Callable[[], Awaitable[Optional[QueryRelevanceValidationResult]]],
    ) -> Optional[QueryRelevanceValidationResult]:
        """Memoized, request-coalesced validation across L1 (in-process) + L2 (Redis).

        Lookup order: L1 LRU -> L2 Redis -> ``supplier`` (image load + VLM call).
        ``supplier`` runs at most once per key across concurrent in-process callers;
        successful verdicts are written back to both tiers. ``None`` results
        (timeouts, parse failures, missing images) are NOT cached, so transient
        failures retry on the next request, unless L2 held a rounded legacy verdict
        for the key (see :meth:`_needs_rejudge`): then that verdict is served instead
        of none and memoized in L1. A Redis outage degrades to L1-only.
        """
        cached = self._cache_get(key)
        if cached is not None:
            _cache_events().labels(outcome="l1_hit").inc()
            return cached

        # L2: persistent, shared across replicas. Hydrate L1 on a hit.
        digest = self._redis_digest(key) if self._redis_cache is not None else None
        legacy: Optional[QueryRelevanceValidationResult] = None
        if self._redis_cache is not None:
            row = await self._redis_cache.get(digest)
            if row is not None:
                result = QueryRelevanceValidationResult.from_row(row)
                if result is not None:
                    if not self._needs_rejudge(result):
                        self._cache_put(key, result)
                        _cache_events().labels(outcome="l2_hit").inc()
                        return result
                    legacy = result  # valid, only rounded: re-judge, but keep it as the fallback

        _cache_events().labels(outcome="miss").inc()
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(supplier())
            self._inflight[key] = task
            task.add_done_callback(lambda _t: self._inflight.pop(key, None))
        result = await asyncio.shield(task)
        if result is not None:
            self._cache_put(key, result)
            if self._redis_cache is not None:
                await self._redis_cache.set(digest, result.to_row())
        elif legacy is not None:
            # The re-judge yielded no verdict (timeout, abstain, parse failure): a
            # rounded verdict beats none. Serve it from L1 for this process; the L2
            # row is left as is, so the backfill is retried by another replica/restart.
            self._cache_put(key, legacy)
            return legacy
        return result

    async def _validate_single(
        self,
        query_text: Optional[str],
        query_image: Optional[str],
        images: List[str],
        asset_facts: Optional[Mapping[str, Optional[str]]] = None,
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

        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                # The slot wait sits inside the deadline: under a backlog (many
                # validated searches at once) a hit that cannot start in time gets
                # no verdict and stays fail-open, instead of queueing past its timeout.
                async with self._semaphore:
                    result = await self._validation.avalidate(
                        query=query,
                        reference_images=images,
                        return_detailed=True,
                        asset_caption=asset_caption,
                        asset_facts=asset_facts,
                    )

            # The log-prob method returns None when it abstains (uncertain, and
            # abstain-as-no is off): no verdict, so the hit stays fail-open (never
            # dropped or reordered), same as a timeout/parse failure. Not cached.
            if result is None:
                return None

            return QueryRelevanceValidationResult(
                is_match=result.is_match,
                confidence=result.confidence,
                similarity_score=result.similarity_score,
                reasoning=result.reasoning,
            )
        except asyncio.TimeoutError:
            # Per-verdict deadline (queue wait included): no verdict for this hit;
            # the endpoint surfaces 504 on the single-result path, the batch continues.
            logger.warning("Validation timed out for %d image(s)", len(images))
            return None
        except ParsingException as e:
            # Per-call parse failure (VLM produced unparseable output). Not
            # a service-down condition — return None so this hit errors out
            # but the batch continues.
            logger.error(f"VLM response parse error: {e}")
            return None
        except LLMBadRequestException as e:
            # Provider rejected the request as unsupported/malformed (4xx) —
            # e.g. the configured model does not support logprobs. Permanent
            # for this config; surface as a non-retryable configuration error
            # so the endpoint returns a structured, actionable reason instead
            # of a transient "service unavailable".
            logger.error("VLM configuration error (provider rejected request): %s", e)
            raise VLMConfigurationError(str(e)) from e
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
        asset_facts: Optional[List[Optional[Mapping[str, Optional[str]]]]] = None,
    ) -> List[Optional[QueryRelevanceValidationResult]]:
        """Validate multiple assets against the query in parallel.

        Args:
            query_text: Text search query (combined from all text inputs)
            query_image: Base64 encoded query image (from image similarity search)
            image_sets: List of image sets, where each set contains one or more base64 images
                        representing different views of the same asset.
            asset_facts: Optional facts by name per image set (``path``, ``vlm_metadata_caption``), read
                        by a text query's logprob judge when logprob_asset_facts lists them.

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

            facts = list(asset_facts or [])
            facts += [None] * (len(image_sets) - len(facts))
            tasks = [
                self._validate_single(query_text, query_image, images, fact) for images, fact in zip(image_sets, facts)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            # Batch-level signal: if ANY sibling task hit a provider-down or
            # configuration error, it applies to the whole batch (same config +
            # endpoint). Propagate so the endpoint can map it — a permanent
            # VLMConfigurationError in preference to a transient
            # VLMServiceUnavailable if both occurred.
            for result in results:
                if isinstance(result, VLMConfigurationError):
                    raise result
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
