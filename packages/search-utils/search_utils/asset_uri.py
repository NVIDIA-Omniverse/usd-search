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

"""How an asset URI is *spelled*: percent-encoding of the path, and non-storage schemes.

Distinct from :mod:`search_utils.url_mapping`, which translates between the
internal and public forms of the same object.

The rule: an internal URI holds the raw storage key (which may contain a literal
space); an http(s) URI holds the escaped path. USD authors asset paths either way
— ``./Material%20Library/x.usd`` and ``../Material Library/y.mdl`` occur in one
asset tree — and a key whose text really contains ``%20`` is indistinguishable
from an escaped space, so callers that can check whether an object exists should
check rather than assume.
"""

from typing import Optional
from urllib.parse import quote, unquote, urlsplit, urlunsplit

#: Schemes that do not name a storage object: resolved by the consuming runtime
#: from a search path, so never ACL-checked, downloaded, or reported as missing.
#: ``mdl:`` is written by the graph builder for a bare module name (``OmniPBR.mdl``).
#: Keep in sync with ``graph_builder/usd_deps.py`` (``MDL_SCHEME``) — that script
#: runs in its own subprocess interpreter and cannot import this package.
SEARCH_PATH_SCHEMES: frozenset = frozenset({"mdl"})

#: Left unescaped in an encoded path: ``/`` separates segments, and the sub-delims
#: and ``:@`` are legal in a segment per RFC 3986.
_PATH_SAFE = "/:@!$&'()*+,;=~"


def is_search_path_uri(uri: object) -> bool:
    """Whether ``uri`` names something resolved from a search path, not from storage."""
    if not isinstance(uri, str):
        return False
    scheme, _, rest = uri.partition(":")
    # Bare `scheme:name`, never `scheme://host/...`: a search-path module has no
    # authority, and treating one as a URL sends it back to a storage client.
    return bool(rest) and not rest.startswith("//") and scheme.lower() in SEARCH_PATH_SCHEMES


def _split_path(uri: str) -> Optional[tuple]:
    """``(prefix, path, suffix)`` for ``uri``, or None if it has no path to touch.

    Only ``http(s)`` gets full URL parsing: elsewhere the remainder is an object
    key, which may legitimately contain ``?`` and ``#``.
    """
    scheme, sep, rest = uri.partition("://")
    if not sep:
        return None
    if scheme.lower() in ("http", "https"):
        _s, netloc, path, query, fragment = urlsplit(uri)
        if not path:
            return None
        return f"{scheme}://{netloc}", path, urlunsplit(("", "", "", query, fragment))
    netloc, slash, key = rest.partition("/")
    if not slash:
        return None
    return f"{scheme}://{netloc}/", key, ""


def decode_uri_path(uri: Optional[str]) -> Optional[str]:
    """Percent-decode a URI's path, leaving scheme, host, query and fragment alone.

    ``https://h/a/Material%20Library/x.usd`` -> ``https://h/a/Material Library/x.usd``.
    Applied once.
    """
    if not isinstance(uri, str) or "%" not in uri:
        return uri
    parts = _split_path(uri)
    if parts is None:
        return uri
    prefix, path, suffix = parts
    return f"{prefix}{unquote(path)}{suffix}"


def encode_uri_path(uri: Optional[str]) -> Optional[str]:
    """Percent-encode a URI's path, leaving scheme, host, query and fragment alone.

    The path is a raw storage key, so a literal ``%`` in it is escaped to ``%25``
    rather than read as an escape that is already there: a key really named
    ``a%20b.usd`` must not publish as the URL for ``a b.usd``, which would resolve
    back to a different object.
    """
    if not isinstance(uri, str) or not uri:
        return uri
    parts = _split_path(uri)
    if parts is None:
        return uri
    prefix, path, suffix = parts
    return f"{prefix}{quote(path, safe=_PATH_SAFE)}{suffix}"


def uri_path_spellings(uri: Optional[str]) -> list:
    """``uri`` plus its percent-decoded spelling, deduplicated, original first.

    For lookups that can try both rather than guess which one the backend stored.
    """
    if not isinstance(uri, str) or not uri:
        return [uri] if uri else []
    decoded = decode_uri_path(uri)
    return [uri] if decoded == uri else [uri, decoded]


__all__ = [
    "SEARCH_PATH_SCHEMES",
    "decode_uri_path",
    "encode_uri_path",
    "is_search_path_uri",
    "uri_path_spellings",
]
