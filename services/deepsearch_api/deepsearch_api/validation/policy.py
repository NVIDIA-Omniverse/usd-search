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

"""Post-validation result policies for hybrid search responses."""

from typing import List

from ..routers_v2.models import QueryRelevanceValidationResult
from ..search_backend.models import SearchResult

__all__ = ["apply_validation_mode", "rerank_sort_value"]


def rerank_sort_value(relevance: QueryRelevanceValidationResult) -> float:
    """Value ``rerank`` sorts on (descending): the verdict's float ``similarity_score`` (0-100)."""
    return float(relevance.similarity_score)


def apply_validation_mode(hits: List[SearchResult], mode: str) -> List[SearchResult]:
    """Apply VLM verdicts to the result list.

    - ``filter`` (default): drop hits the VLM explicitly rejected
      (``is_match=False``).
    - ``rerank``: keep every hit, reorder by the VLM's float ``similarity_score``;
      ties keep retrieval order.
    - ``annotate``: attach verdicts only — order, membership, and ranks are
      untouched (the behavior before modes existed).

    Example — retrieval order A(80) B(20) C(no verdict) D(95)::

        filter   -> A C D     (only the explicit non-match B is dropped)
        rerank   -> D A C B   (C keeps its slot)
        annotate -> A B C D   (unchanged)

    In every mode a hit WITHOUT a verdict (VLM timeout/parse failure) is never
    demoted or dropped — fail-open. Filtering does not backfill, so fewer than
    ``limit`` hits may return. ``filter`` and ``rerank`` renumber
    ``metadata.rrf_rank`` to match the returned order; ``annotate`` leaves it
    untouched. ``rrf_score`` always keeps the original retrieval score.
    See docs/vlm-validation.md ("Validation modes").
    """
    if mode == "annotate":
        return hits
    if mode == "filter":
        output = [hit for hit in hits if hit.query_relevance is None or hit.query_relevance.is_match]
    elif mode == "rerank":
        validated = [
            (position, hit, relevance)
            for position, hit in enumerate(hits)
            if (relevance := hit.query_relevance) is not None
        ]
        validated.sort(
            key=lambda item: (
                -rerank_sort_value(item[2]),
                item[0],
            )
        )
        reordered = iter(hit for _, hit, _ in validated)
        output = [hit if hit.query_relevance is None else next(reordered) for hit in hits]
    else:
        raise ValueError(f"Unknown validation mode: {mode}")

    for rank, hit in enumerate(output, 1):
        if hit.metadata is not None:
            hit.metadata.rrf_rank = rank

    return output
