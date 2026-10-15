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

"""Log-safe rendering of user-supplied asset URLs."""

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Log-safe form of a user-supplied URL: drop credentials, query, fragment; escape control chars.

    Query strings routinely carry secrets (S3 presigned ``X-Amz-Signature``), userinfo can hold
    ``user:pass``, and a decoded CR/LF would let a caller forge log lines.
    """
    url = str(url)
    try:
        parts = urlsplit(url)
        netloc = parts.hostname or ""
        if ":" in netloc:  # IPv6 literal
            netloc = f"[{netloc}]"
        if parts.port:
            netloc = f"{netloc}:{parts.port}"
        url = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        url = url.split("?", 1)[0].split("#", 1)[0]
        if "://" in url:  # still drop userinfo from the unparseable authority
            scheme, rest = url.split("://", 1)
            authority, sep, path = rest.partition("/")
            url = f"{scheme}://{authority.rsplit('@', 1)[-1]}{sep}{path}"
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in url)
