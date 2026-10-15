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

"""Opaque pagination cursors.

A cursor is ``base64url(orjson(payload)) + "." + crc32``. Pure functions, no I/O:
everything needed to resume a search is in the token or recomputable from it.

**Deliberately not signed.** ``limit`` and ``rrf_config.window_size`` are already
caller-supplied and ``offset`` is a plain request field, so a forged cursor
confers nothing a normal request body does not. The boundary is
``validate_bounds()``, which re-checks every decoded field against live limits —
needed anyway, since a cursor can outlive a config change. Signing would add a
mandatory shared secret and a new failure mode (replicas rejecting each other's
cursors). The CRC is for corruption, not authenticity: a mangled cursor gets a
clean 400 instead of a traceback.

**Invariant that keeps this safe:** the cursor must never carry anything the
server would not accept as a plain request parameter. Caching an authorization
decision (say a resolved ``url_whitelist``) would break it and bring signing
back. Check any new payload field against this.
"""

import base64
import binascii
import hashlib
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import orjson
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import OPENSEARCH_MAX_RESULT_WINDOW

# Bump when the payload shape changes incompatibly. Cursors carrying an older
# version are rejected rather than misread; clients simply re-issue the search.
CURSOR_VERSION = 1

# Stand-in for "no configured depth cap". Filter-only queries page to arbitrary
# depth via search_after over a unique keyword sort, so there is no natural
# ceiling — but PageSpec.max_offset still needs a number to compare against.
UNBOUNDED_MAX_OFFSET = 2**31 - 1

# Request fields that do not influence ranking or membership, and are therefore
# excluded from the query fingerprint. Toggling one of these mid-pagination
# must NOT invalidate an in-flight cursor.
#
# The return_* flags only select which fields come back per hit. They do not
# reach the similarity filter: _apply_similarity_threshold_filtering reads the
# embedding from the top-level _source, and whether that is fetched is driven by
# similarity_threshold itself, not by return_embeddings/return_predictions (see
# _vector_inner_hits_source).
#
# `limit` is excluded so a client may change page size mid-walk: the cursor
# carries an absolute position (offset, or search_after sort values), and the
# RRF window is pinned in the cursor rather than derived from limit.
NON_RANKING_FIELDS = frozenset(
    {
        # pagination itself
        "offset",
        "cursor",
        "limit",
        # response shaping only
        "return_images",
        "return_metadata",
        "return_embeddings",
        "return_predictions",
        "return_tags",
        "return_inner_hits",
        "return_usd_properties",
        "return_usd_dimensions",
        "return_root_prims",
        "return_default_prims",
        "return_in_scene_instances_prims",
        "return_vision_generated_metadata",
        # forces single-page (see the plan, §9.5), so it can never coexist with
        # a cursor; excluding it keeps the fingerprint stable either way
        "validate_results",
    }
)


class PaginationMode(str, Enum):
    """Which retrieval strategy the cursor resumes.

    Chosen by the server from the leg count, never by the caller — it flips
    based on how many legs a query happens to produce, which is an
    implementation detail.
    """

    #: Single leg: paginated natively by OpenSearch (from/size, or search_after
    #: once depth exceeds max_result_window).
    LEG = "leg"
    #: Multiple legs: paginated inside the client-side RRF fusion window.
    RRF = "rrf"


class PaginationError(Exception):
    """A cursor could not be decoded, or decoded to something out of bounds.

    Routers map this to HTTP 400 — every case is caller-correctable.
    """


class CursorPayload(BaseModel):
    """Decoded cursor contents.

    Readable names in Python, one- or two-letter keys on the wire — cursors ride
    in a URL, and these are the same eight fields on every page of every walk.
    """

    model_config = ConfigDict(populate_by_name=True)

    version: int = Field(alias="v", description="Cursor schema version")
    mode: PaginationMode = Field(alias="m", description="Pagination mode this cursor resumes")
    query_fingerprint: str = Field(alias="qf", description="Fingerprint of the ranking-relevant request fields")
    offset: int = Field(default=0, ge=0, alias="off", description="Logical offset into the ranked result list")
    raw_offset: int = Field(
        default=0,
        ge=0,
        alias="raw",
        description=(
            "Offset in the pre-access-filter result space. Diverges from `offset` once access filtering "
            "drops hits, and is what the next page resumes from upstream."
        ),
    )
    window: Optional[int] = Field(default=None, alias="win", description="Pinned RRF fusion window (rrf mode)")
    search_after: Optional[List[Any]] = Field(
        default=None,
        alias="sa",
        description="OpenSearch sort values from the last hit of the previous page (leg mode)",
    )
    ranking_id: Optional[str] = Field(
        default=None, alias="rid", description="Redis key suffix for the cached fused order"
    )
    expires_at: Optional[int] = Field(default=None, alias="exp", description="Unix expiry; decoding after this fails")


class DepthLimitReason(str, Enum):
    """Why paging stopped, so a client can tell "no more results" from "cannot
    page further in this mode".

    Without this a user who sets ``similarity_threshold`` silently loses depth
    with no way to see the cause.
    """

    #: The whole result set was returned.
    EXHAUSTED = "exhausted"
    #: Multi-leg fusion: only the RRF window is reachable.
    RRF_WINDOW = "rrf_window"
    #: Configured pagination_max_offset.
    MAX_OFFSET = "max_offset"
    #: OpenSearch index.max_result_window, and no cursor to continue with.
    RESULT_WINDOW = "result_window"
    #: deduplicate_by_hash forces from/size paging (collapse + search_after).
    COLLAPSE = "collapse"
    #: validate_results is single-page (see the plan, §9.5).
    VALIDATION = "validation"


class PageSpec(BaseModel):
    """Where a page starts and how deep it may go. Backend input."""

    offset: int = Field(default=0, ge=0, description="Logical offset into the ranked result list")
    raw_offset: int = Field(default=0, ge=0, description="Offset in the pre-access-filter space")
    window: Optional[int] = Field(default=None, description="Pinned RRF fusion window, when resuming a cursor")
    search_after: Optional[List[Any]] = Field(default=None, description="Sort values to resume a deep leg-mode page")
    ranking_id: Optional[str] = Field(
        default=None,
        description=(
            "Id of a previously materialised fused order (RRF mode). A hit skips re-running every leg; "
            "a miss recomputes, so this is never load-bearing."
        ),
    )
    mode: Optional[PaginationMode] = Field(
        default=None,
        description="Mode from the cursor. None means the backend picks it from the leg count.",
    )
    max_offset: int = Field(
        default=OPENSEARCH_MAX_RESULT_WINDOW,
        description="Deepest reachable offset. Filter-only queries pass a large value (arbitrary depth).",
    )

    @property
    def is_paginating(self) -> bool:
        return self.offset > 0 or self.search_after is not None


class PageInfo(BaseModel):
    """What the backend reports back about the page it produced."""

    mode: PaginationMode
    offset: int
    page_size: int
    depth_limit: int = Field(description="Deepest offset reachable for this query shape")
    depth_limit_reason: DepthLimitReason
    window: Optional[int] = Field(
        default=None,
        description=(
            "Pinned RRF fusion window for this page (rrf mode only). Reported so a client — or the "
            "access-filtering layer, which re-mints cursors — can see the pool the offsets are relative to."
        ),
    )


def fingerprint_request(request: Any) -> str:
    """Stable digest of everything about a request that can change the ranking.

    Two requests differing only in page size or response flags fingerprint
    identically, so a client may toggle those mid-pagination. Any change to the
    query, filters, or scoring invalidates the cursor with a clean 400 rather
    than silently re-ranking underneath the caller.
    """
    dumped = request.model_dump(mode="json", exclude_none=True)
    relevant = {k: v for k, v in dumped.items() if k not in NON_RANKING_FIELDS}
    # sort_keys so field ordering never perturbs the digest
    encoded = orjson.dumps(relevant, option=orjson.OPT_SORT_KEYS)
    # 16 hex chars (64 bits) — collisions here mean "cursor accepted for a
    # different query", and the cursor is short-lived and query-scoped, so the
    # full digest would only bloat the token.
    return hashlib.sha256(encoded).hexdigest()[:16]


def encode_cursor(payload: CursorPayload) -> str:
    """Serialise a payload to an opaque token."""
    raw = orjson.dumps(payload.model_dump(mode="json", by_alias=True, exclude_none=True))
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{body}.{binascii.crc32(raw):08x}"


def decode_cursor(token: str) -> CursorPayload:
    """Parse a token back into a payload.

    Raises:
        PaginationError: malformed, corrupted, expired, or from another cursor
            schema version. Never raises anything else — callers map this
            directly to 400.
    """
    if not token or "." not in token:
        raise PaginationError("Malformed pagination cursor.")

    body, _, checksum = token.rpartition(".")
    try:
        # restore the base64 padding stripped by encode_cursor
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError) as exc:
        raise PaginationError("Malformed pagination cursor.") from exc

    if f"{binascii.crc32(raw):08x}" != checksum:
        raise PaginationError("Corrupted pagination cursor — checksum mismatch.")

    try:
        payload = CursorPayload.model_validate(orjson.loads(raw))
    except (orjson.JSONDecodeError, ValidationError) as exc:
        raise PaginationError("Malformed pagination cursor.") from exc

    if payload.version != CURSOR_VERSION:
        raise PaginationError(
            f"Unsupported pagination cursor version {payload.version} (expected {CURSOR_VERSION}); re-issue the search."
        )

    if payload.expires_at is not None and payload.expires_at < int(time.time()):
        raise PaginationError("Pagination cursor has expired; re-issue the search.")

    return payload


def validate_bounds(payload: CursorPayload, max_offset: int, query_fingerprint: Optional[str] = None) -> None:
    """Re-check a decoded cursor against live limits.

    The security boundary, not the token format (see the module docstring), and
    it must run on every decoded cursor: limits are configuration, so an offset
    that was legal when the cursor was issued may not be now.

    Args:
        max_offset: current ``pagination_max_offset``. Filter-only queries page
            to arbitrary depth, so callers pass a large value for those.
        query_fingerprint: when given, the cursor must belong to this query.

    Raises:
        PaginationError: any bound violated.
    """
    if query_fingerprint is not None and payload.query_fingerprint != query_fingerprint:
        raise PaginationError(
            "Pagination cursor was issued for a different query. "
            "Start a new search, or keep the query identical while paging."
        )

    if payload.offset > max_offset:
        raise PaginationError(f"Pagination offset {payload.offset} exceeds the maximum supported depth ({max_offset}).")

    if payload.raw_offset < payload.offset:
        # raw counts hits consumed upstream of access filtering, which only ever
        # removes; it cannot be behind the post-filter offset.
        raise PaginationError("Malformed pagination cursor.")

    if payload.window is not None and not (1 <= payload.window <= OPENSEARCH_MAX_RESULT_WINDOW):
        raise PaginationError(f"Pagination window must be between 1 and {OPENSEARCH_MAX_RESULT_WINDOW}.")

    if payload.mode == PaginationMode.RRF:
        if payload.window is None:
            raise PaginationError("Malformed pagination cursor — RRF mode requires a pinned window.")
        if payload.offset >= payload.window:
            raise PaginationError(
                f"Pagination offset {payload.offset} is outside the RRF fusion window ({payload.window}). "
                "Multi-leg queries can only be paged within the window; narrow the query or raise "
                "scoring_config.rrf_config.window_size."
            )


def build_cursor(
    mode: PaginationMode,
    query_fingerprint: str,
    offset: int,
    raw_offset: int,
    window: Optional[int] = None,
    search_after: Optional[List[Any]] = None,
    ranking_id: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Convenience constructor for the next-page cursor."""
    return encode_cursor(
        CursorPayload(
            version=CURSOR_VERSION,
            mode=mode,
            query_fingerprint=query_fingerprint,
            offset=offset,
            raw_offset=raw_offset,
            window=window,
            search_after=search_after,
            ranking_id=ranking_id,
            expires_at=int(time.time()) + ttl_seconds if ttl_seconds else None,
        )
    )


def resolve_page_start(
    cursor: Optional[str],
    offset: int,
    max_offset: int,
    query_fingerprint: str,
) -> Dict[str, Any]:
    """Turn the caller's ``cursor`` / ``offset`` into a starting position.

    ``cursor`` wins when both are supplied and they disagree, since it carries
    strictly more state (pinned window, search_after values, ranking id).

    Returns a dict with ``offset``, ``raw_offset``, ``window``, ``search_after``,
    ``ranking_id`` and ``mode`` (``mode`` is None when there is no cursor — the
    backend picks it from the leg count).

    Raises:
        PaginationError: bad cursor, or a plain offset past the depth cap.
    """
    if cursor:
        payload = decode_cursor(cursor)
        validate_bounds(payload, max_offset=max_offset, query_fingerprint=query_fingerprint)
        return {
            "offset": payload.offset,
            "raw_offset": payload.raw_offset,
            "window": payload.window,
            "search_after": payload.search_after,
            "ranking_id": payload.ranking_id,
            "mode": payload.mode,
        }

    if offset < 0:
        raise PaginationError("offset must be >= 0.")
    if offset > max_offset:
        raise PaginationError(f"Pagination offset {offset} exceeds the maximum supported depth ({max_offset}).")

    return {
        "offset": offset,
        "raw_offset": offset,
        "window": None,
        "search_after": None,
        "ranking_id": None,
        "mode": None,
    }


def is_filter_only_request(request: Any) -> bool:
    """Whether a request produces a single ``match_all`` + filters leg.

    Mirrors the branch in ``SearchBackendClientV2.search``. This shape is the one
    that pages to arbitrary depth (§9.3 of the plan): ``_score`` carries no
    information under ``match_all``, so the sort reduces to a unique keyword key
    and ``search_after`` can walk it indefinitely — no scoring, and OpenSearch can
    skip whole segments instead of scanning ``from + size`` per shard.
    """
    return not any(
        [
            getattr(request, "description", None),
            getattr(request, "hybrid_text_query", None),
            getattr(request, "image_similarity_search", None),
            getattr(request, "vector_queries", None),
        ]
    )


def max_offset_for_request(request: Any, pagination_max_offset: int) -> int:
    """Depth cap for this query shape.

    Filter-only queries are exempt from ``pagination_max_offset`` entirely; every
    other shape is capped by it (RRF mode is additionally capped by the fusion
    window, which the backend applies on top).
    """
    return UNBOUNDED_MAX_OFFSET if is_filter_only_request(request) else pagination_max_offset


def page_spec_for_request(request: Any, pagination_max_offset: int) -> PageSpec:
    """Turn a request's ``offset`` / ``cursor`` into a :class:`PageSpec`.

    The single entry point every endpoint shares, so the depth cap, the
    cursor-bounds check and the ``validate_results`` rule are applied uniformly
    rather than re-derived per router.

    Raises:
        PaginationError: bad/expired cursor, an out-of-bounds offset, or paging
            combined with ``validate_results``. Routers map this to 400.
    """
    offset = getattr(request, "offset", 0) or 0
    cursor = getattr(request, "cursor", None)

    if getattr(request, "validate_results", False) and (offset or cursor):
        # VLM validation drops non-matching hits after the page is already cut and
        # never backfills, so paged validation would return a different (and
        # unpredictable) number of hits per page. `rerank` mode is worse still: it
        # sorts within a page, so a page-2 hit can outrank a page-1 hit. The mode
        # is a deployment setting rather than a request field, so keying the rule
        # on `validate_results` is what keeps identical client code behaving the
        # same against every deployment. See the plan, §9.5.
        raise PaginationError(
            "validate_results=true cannot be combined with pagination: validated pages would be ragged, "
            "because non-matching hits are dropped after the page is cut and are not backfilled. "
            "Request a larger limit instead, or paginate with validate_results=false."
        )

    max_offset = max_offset_for_request(request, pagination_max_offset)
    return PageSpec(
        max_offset=max_offset,
        **resolve_page_start(
            cursor=cursor,
            offset=offset,
            max_offset=max_offset,
            query_fingerprint=fingerprint_request(request),
        ),
    )


def rebase_cursor(
    token: str,
    offset: int,
    raw_offset: int,
    search_after: Optional[List[Any]] = None,
    drop_search_after: bool = False,
) -> str:
    """Re-issue a cursor at different offsets, keeping everything else intact.

    The backend mints cursors in the raw (pre-access-filter) space, where the two
    offsets coincide; once hits are dropped for permissions they diverge, so the
    access-filtering layer restamps the token rather than rebuilding it (which
    would lose the pinned window, ranking id and fingerprint).

    A page cut mid-batch also invalidates the backend's resume values — they
    belong to the batch's last hit, not the cut point. Pass ``search_after`` (the
    cut hit's own sort values) to stay on ``search_after``, the only mechanism
    that reaches past ``index.max_result_window``, or ``drop_search_after`` to
    fall back to raw-offset positioning, which is exact but capped there. The
    fallback is for pages with no sort values: RRF mode and cached rankings.
    """
    payload = decode_cursor(token)
    payload.offset = offset
    payload.raw_offset = raw_offset
    if search_after:
        payload.search_after = search_after
    elif drop_search_after:
        payload.search_after = None
    return encode_cursor(payload)
