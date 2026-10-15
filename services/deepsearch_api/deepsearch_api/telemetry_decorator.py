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
import json
import logging
import os
import time
from importlib.metadata import version
from typing import Any, Callable, Dict, Optional

import deepsearch_api
from deepsearch_api.telemetry_otel import business_telemetry
from fastapi import Request, Response
from fastapi.security import HTTPBasicCredentials
from opentelemetry.context import create_key, get_value
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Context key for storing username across spans
USERNAME_CONTEXT_KEY = create_key("username")
USE_SEARCH_TELEMETRY = os.getenv("USE_SEARCH_TELEMETRY", "False").lower() == "true"

NGSEARCH_VERSION = None


def get_ngsearch_version() -> str:
    """Get the current package version dynamically"""
    global NGSEARCH_VERSION
    if NGSEARCH_VERSION:
        return NGSEARCH_VERSION
    try:
        NGSEARCH_VERSION = version(deepsearch_api.__package__)
        return NGSEARCH_VERSION
    except Exception:
        return "unknown"


def get_jwt_payload(token: str) -> Dict[str, Any]:
    """Extract JWT payload without verification (for telemetry purposes only)"""
    try:
        # Split token into parts
        parts = token.split(".")
        if len(parts) != 3:
            raise IndexError("Invalid JWT format")

        # Get payload part (second part)
        payload_part = parts[1]

        # Add padding if needed for base64 decoding
        missing_padding = len(payload_part) % 4
        if missing_padding:
            payload_part += "=" * (4 - missing_padding)

        # Decode base64 payload
        payload_bytes = base64.urlsafe_b64decode(payload_part)
        payload = json.loads(payload_bytes)

        return payload
    except Exception:
        raise


def extract_telemetry_user_id_from_jwt(token: Optional[str]) -> str:
    """Extract user ID from JWT token for telemetry purposes"""
    if token is None:
        return "unknown"

    try:
        payload = get_jwt_payload(token)
    except IndexError:
        return "unknown"
    except Exception:
        return "unknown"

    # Omniverse / Nucleus token shape.
    try:
        email = payload["profile"]["email"]
        if len(email) > 0:
            return email
        return f'{payload["profile"]["first_name"]}_{payload["profile"]["last_name"]}'
    except KeyError:
        pass

    # Generic OIDC token shape — a Storage API / S3 deployment issues these, and
    # they carry the identity as a top-level claim rather than under `profile`.
    for claim in ("email", "preferred_username", "sub"):
        value = payload.get(claim)
        if isinstance(value, str) and value:
            return value

    return "unknown"


def _extract_query_text(args, kwargs) -> str:
    """Universal query text extractor for all search endpoint patterns"""
    query_text = ""

    # Method 1: Direct from kwargs (GET endpoints - description parameter)
    query_text = kwargs.get("description", "") or ""

    # Method 2: From request object (POST endpoints)
    if not query_text:
        # Find request object in kwargs first
        req = kwargs.get("req")

        # If not in kwargs, search through args for request objects
        if not req:
            for arg in args:
                if hasattr(arg, "description") or hasattr(arg, "hybrid_text_query"):
                    req = arg
                    break

        # Extract query from request object
        if req:
            # Primary field: description
            query_text = getattr(req, "description", "") or ""

            # Secondary field: hybrid_text_query (V2)
            if not query_text:
                query_text = getattr(req, "hybrid_text_query", "") or ""

    return query_text[:256] if query_text else ""  # Truncate long queries


def _get_username_from_context() -> str:
    """Get username from OpenTelemetry context or span attributes"""
    try:
        from opentelemetry import trace
        from opentelemetry.context import get_current

        # First try to get username from context
        current_context = get_current()
        username = get_value(USERNAME_CONTEXT_KEY, context=current_context)
        if username:
            return username

        # Fallback: check current span attributes
        current_span = trace.get_current_span()
        if current_span:
            username = current_span.get_attribute("user.name")
            if username:
                return username

    except Exception:
        pass

    return None


def _extract_username(args, kwargs) -> str:
    """Extract username from auth credentials"""

    if kwargs.get("api_key_auth"):
        return "admin_access"

    # First, check if username is already set in context or span attributes
    username = _get_username_from_context()
    if username:
        return username

    basic_auth = None

    # Find basic_auth in function arguments
    for arg in args:
        if isinstance(arg, HTTPBasicCredentials):
            basic_auth = arg
            break

    # Extract from kwargs if not found in args
    if not basic_auth:
        basic_auth = kwargs.get("basic_auth")

    # Return username if available
    if basic_auth and basic_auth.username:
        return basic_auth.username

    return "anonymous"


def _extract_query_attributes(args, kwargs) -> dict:
    """Extract full query request as a dictionary for telemetry"""
    query_attributes = {}

    # Method 1: From kwargs (GET endpoints - collect all query parameters)
    if kwargs:
        # Filter out authentication and internal parameters
        filtered_kwargs = {
            k: v
            for k, v in kwargs.items()
            if not k.endswith("_auth")
            and not k.endswith("_client")
            and not k.endswith("_loader")
            and not k.endswith("_backend")
            and not k.endswith("_backend_v2")
            and not k.endswith("_validator")
            # ASGI plumbing, not query input: endpoints declare these to read
            # headers or to set response headers (the v2 pagination X-* headers).
            # Neither is JSON-serializable, and the whole dict is json.dumps'd
            # below, so one of them anywhere in the signature would fail the
            # request outright.
            and not isinstance(v, (Request, Response))
        }

        # Handle Pydantic models in kwargs
        for k, v in filtered_kwargs.items():
            if isinstance(v, BaseModel):
                try:
                    query_attributes[k] = v.model_dump()
                except Exception:
                    # Fallback to dict conversion if model_dump fails
                    try:
                        query_attributes[k] = v.__dict__
                    except Exception:
                        query_attributes[k] = str(v)
            else:
                query_attributes[k] = v

    # Method 2: From args (handle Pydantic models in positional arguments)
    for i, arg in enumerate(args):
        if isinstance(arg, BaseModel):
            try:
                arg_dict = arg.model_dump()
                query_attributes.update(arg_dict)
            except Exception:
                # Fallback to dict conversion if model_dump fails
                try:
                    query_attributes.update(arg.__dict__)
                except Exception:
                    query_attributes[f"arg_{i}"] = str(arg)

    # Method 3: From request object (POST endpoints - specific req parameter)
    req = kwargs.get("req")
    if req and isinstance(req, BaseModel):
        try:
            req_dict = req.model_dump()
            query_attributes.update(req_dict)
        except Exception:
            # Fallback to dict conversion if model_dump fails
            try:
                query_attributes.update(req.__dict__)
            except Exception:
                pass

    return query_attributes


def _extract_user_agent(kwargs) -> str:
    """Extract User-Agent header from the FastAPI Request object in kwargs."""
    try:
        request = kwargs.get("request")
        if request is not None and isinstance(request, Request):
            return request.headers.get("user-agent", "unknown")
    except Exception:
        pass
    return "unknown"


def _extract_result_count(result) -> int:
    """Universal result count extractor for different response types"""
    # Handle V3 SearchResponse with total field
    if hasattr(result, "total") and result.total is not None:
        return result.total

    # Handle V3 SearchResponse with hits field
    if hasattr(result, "hits") and result.hits is not None:
        return len(result.hits)

    # Handle V2 List[SearchResult]
    if isinstance(result, list):
        return len(result)

    # Handle other response types with results attribute
    if hasattr(result, "results") and result.results:
        return len(result.results)

    return 0


def _extract_storage_backend_host(kwargs) -> Optional[str]:
    """Storage backend host for the request, from the endpoint's storage client.

    The search decorator reads the same value off ``search_backend_v2``
    (``FilteredSearchClient.storage_backend_host`` is this client's ``telemetry_host``);
    the download endpoint holds the storage client directly.
    """
    host = getattr(kwargs.get("storage_client"), "telemetry_host", None)
    return host if isinstance(host, str) else None


def _extract_asset_load_stats(kwargs) -> Dict[str, Any]:
    """Per-phase timings and counts the handler accumulated on ``request.state``.

    The handler writes each phase as it completes rather than assembling the
    dict at return, so a request that fails part-way (403/404/413) still reports
    what the phases that did run cost.
    """
    request = kwargs.get("request")
    stats = getattr(getattr(request, "state", None), "asset_load_stats", None)
    return dict(stats) if isinstance(stats, dict) else {}


def telemetry_track_asset_load():
    """Decorator to track asset-load (download) endpoint calls as a business event.

    One event per request, emitted at completion — including on failure, where
    it carries ``status="error"`` plus the HTTP status. ``manifest_only`` is
    always present so size-preview calls, which transfer no asset data, can be
    told apart from real loads.

    Unlike :func:`telemetry_track_search`, the enablement check runs at call time
    rather than at import time, so a test can toggle ``USE_SEARCH_TELEMETRY``
    without re-importing the router module. The two decorators are gated
    differently on purpose — see ``docs/plans/asset-load-telemetry.md`` §9/D3.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if not USE_SEARCH_TELEMETRY:
                return await func(*args, **kwargs)

            start_time = time.time()
            status = "success"
            error_type = None
            http_status = None
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                status = "error"
                error_type = type(exc).__name__
                # HTTPException carries the response code; 403/404/413 are the
                # interesting operational signals here.
                code = getattr(exc, "status_code", None)
                http_status = code if isinstance(code, int) else None
                raise
            finally:
                try:
                    business_telemetry.record_asset_load(
                        asset_url=kwargs.get("asset_url") or "",
                        username=_extract_username(args, kwargs),
                        # Always sent, on every path: a record without it cannot
                        # be separated from one that actually loaded data.
                        manifest_only=bool(kwargs.get("manifest_only", False)),
                        event_type="asset_load",
                        status=status,
                        error_type=error_type,
                        http_status=http_status,
                        processing_time_ms=(time.time() - start_time) * 1000,
                        ngsearch_version=get_ngsearch_version(),
                        omni_host=_extract_storage_backend_host(kwargs),
                        user_agent=_extract_user_agent(kwargs),
                        **_extract_asset_load_stats(kwargs),
                    )
                except Exception:  # noqa: BLE001 — telemetry must never break a download
                    logger.warning("Failed to record asset-load telemetry", exc_info=True)

        return wrapper

    return decorator


def telemetry_track_search():
    """Decorator to automatically track search endpoint calls with both query and results events

    Note the enablement check below happens at *import* time: when telemetry is
    off the endpoint is left undecorated entirely. :func:`telemetry_track_asset_load`
    deliberately checks at call time instead — the difference is intentional and
    documented in ``docs/plans/asset-load-telemetry.md`` §9/D3; do not "fix" one
    to match the other.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract telemetry context
            username = _extract_username(args, kwargs)
            query_text = _extract_query_text(args, kwargs)
            query_attributes = _extract_query_attributes(args, kwargs)
            user_agent = _extract_user_agent(kwargs)

            # (Request/Response objects are dropped by _extract_query_attributes.)

            # Use context manager to wrap the entire function execution
            with business_telemetry.record_query_event(
                query=query_text,
                username=username,
                query_attributes=json.dumps({**query_attributes, "event_type": "query"}),
                ngsearch_version=get_ngsearch_version(),
                omni_host=kwargs["search_backend_v2"].storage_backend_host,
                user_agent=user_agent,
            ) as span:
                start_time = time.time()

                # Execute the wrapped function
                result = await func(*args, **kwargs)

                # Calculate processing time
                processing_time_ms = (time.time() - start_time) * 1000

                # Extract result count and add to span
                n_results = _extract_result_count(result)
                if span is not None:
                    span.set_attribute("n_results", n_results)

                # Emit results_presented event
                business_telemetry.record_results_presented(
                    query=query_text,
                    n_results=n_results,
                    time_ms=processing_time_ms,
                    username=username,
                    status="success",
                    omni_host=kwargs["search_backend_v2"].storage_backend_host,
                    user_agent=user_agent,
                )

                return result

        if USE_SEARCH_TELEMETRY:
            return wrapper
        else:
            return func

    return decorator
