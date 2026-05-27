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

"""Bidirectional ASGI middleware that translates between local filesystem paths and S3 URIs.

When ``LOCAL_FS_MODE=true`` is set in the environment, this middleware:

- **Requests**: rewrites local filesystem paths in query strings and JSON bodies
  to their corresponding ``s3://{bucket}/...`` URIs before they reach the application.
- **Responses**: rewrites ``s3://{bucket}/...`` URIs in JSON response bodies back
  to local filesystem paths before they reach the client.

When ``LOCAL_FS_MODE`` is unset or not ``true``, the middleware is a complete no-op
with zero per-request overhead (early return in ``__call__``).

Required environment variables (when enabled):
    LOCAL_FS_MODE       -- "true" / "1" / "yes" to activate
    LOCAL_FS_HOST_PATH  -- absolute path on the host (e.g., /home/user/my-assets)
    S3_STORAGE_BUCKET_NAME -- S3 bucket name used internally (e.g., usdsearch-local)
"""

from __future__ import annotations

import logging
import os
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Endpoints that should never be intercepted (performance + correctness).
_SKIP_PATH_FRAGMENTS = ("/health", "/readyz", "/livez", "/metrics")


class LocalFSPathMiddleware:
    """Pure ASGI middleware for bidirectional local-path <-> S3 URI rewriting."""

    def __init__(self, app):
        self.app = app
        mode = os.environ.get("LOCAL_FS_MODE", "").lower()
        self.enabled = mode in ("true", "1", "yes")
        if self.enabled:
            host_path = os.environ.get("LOCAL_FS_HOST_PATH", "")
            bucket = os.environ.get("S3_STORAGE_BUCKET_NAME", "")
            if not host_path or not bucket:
                logger.warning(
                    "LOCAL_FS_MODE is set but LOCAL_FS_HOST_PATH or "
                    "S3_STORAGE_BUCKET_NAME is missing — disabling middleware."
                )
                self.enabled = False
                return
            self.local_prefix = host_path.rstrip("/") + "/"
            self.s3_prefix = f"s3://{bucket}/"
            self._local_bytes = self.local_prefix.encode()
            self._s3_bytes = self.s3_prefix.encode()
            logger.info(
                "LocalFSPathMiddleware enabled: %s <-> %s",
                self.local_prefix,
                self.s3_prefix,
            )

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if any(frag in path for frag in _SKIP_PATH_FRAGMENTS):
            return await self.app(scope, receive, send)

        # --- Rewrite request query string (local path -> s3 URI) ---
        raw_qs = scope.get("query_string", b"")
        if raw_qs:
            # Check both raw bytes and URL-decoded form for the local prefix.
            decoded_qs = unquote(raw_qs.decode(errors="replace"))
            if self.local_prefix in decoded_qs:
                new_qs = decoded_qs.replace(self.local_prefix, self.s3_prefix)
                scope = dict(scope, query_string=new_qs.encode())

        # --- Rewrite request body (local path -> s3 URI) ---
        async def rewriting_receive():
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                if body and self._local_bytes in body:
                    body = body.replace(self._local_bytes, self._s3_bytes)
                    message = dict(message, body=body)
            return message

        # --- Rewrite response body (s3 URI -> local path) ---
        # Buffer the response start message to inspect content-type before
        # deciding whether to rewrite. Also buffer body chunks for streamed
        # responses (rare for JSON, but correct).
        start_message = None
        is_json = False
        response_body_parts: list[bytes] = []

        async def rewriting_send(message):
            nonlocal start_message, is_json, response_body_parts

            if message["type"] == "http.response.start":
                start_message = message
                # Determine content-type.
                for key, value in message.get("headers", []):
                    if key.lower() == b"content-type":
                        is_json = b"application/json" in value.lower()
                        break
                return

            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                more_body = message.get("more_body", False)

                if not is_json:
                    # Not JSON — pass through immediately without buffering.
                    if start_message:
                        await send(start_message)
                        start_message = None
                    await send(message)
                    return

                # Buffer body chunks for JSON responses.
                response_body_parts.append(body)

                if not more_body:
                    # Final chunk — assemble full body and rewrite.
                    full_body = b"".join(response_body_parts)
                    if self._s3_bytes in full_body:
                        full_body = full_body.replace(self._s3_bytes, self._local_bytes)
                    # Update content-length header if present.
                    if start_message:
                        new_headers = []
                        for key, value in start_message.get("headers", []):
                            if key.lower() == b"content-length":
                                new_headers.append((key, str(len(full_body)).encode()))
                            else:
                                new_headers.append((key, value))
                        await send(dict(start_message, headers=new_headers))
                        start_message = None
                    await send(dict(message, body=full_body, more_body=False))
                return

            # Pass through any other message types (e.g. http.disconnect).
            if start_message:
                await send(start_message)
                start_message = None
            await send(message)

        await self.app(scope, rewriting_receive, rewriting_send)
