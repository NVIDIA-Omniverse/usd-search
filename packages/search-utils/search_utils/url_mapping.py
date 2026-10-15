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

"""Public/internal asset-URL translation at the HTTP boundary.

An asset's *internal* URL is whatever the crawler indexed it as — the exact string
stored in OpenSearch's ``base_key`` and in the Neo4j asset graph, and the one every
storage client speaks (``s3://bucket/key``, ``omniverse://server/path``). It is a
primary key: every lookup matches it exactly, so a URL that differs by a single
character fails as an empty result rather than as an error.

Some deployments want the API to *speak* a different form to the outside world —
most commonly ``https://`` instead of ``s3://``. This module translates between the
two at the edge, and only at the edge: requests are normalized to the internal form
before anything else sees them, responses are rewritten to the public form on the
way out. Nothing below the routers changes.

"The edge" is every boundary, not just the user-facing one. Several services here
publish the public form *to each other* — the asset-graph service is reachable
through the gateway in its own right, so it answers deepsearch-api exactly as it
answers a browser. A response read from such a service is an inbound edge and gets
:func:`normalize_upstream_document` for the same reason a request field gets
:data:`AssetUrl`.

Rules are ordered ``internal prefix -> public prefix`` pairs, resolved
longest-prefix-first. Translation is deliberately lenient inbound (both forms are
accepted, always) and canonical outbound (the public form is emitted), which is
what makes the feature safe to enable on a live deployment: clients holding old
``s3://`` URLs keep working forever.

Disabled by default (``USDSEARCH_URL_MAPPING_MODE=off``), in which case every entry
point here is an identity function.

Configuration and operational caveats: ``docs/configuration-map.md``
("Public asset URLs").
"""

import logging
import os
import re
from enum import Enum
from typing import Annotated, Any, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .asset_uri import decode_uri_path, encode_uri_path
from .local_fs_middleware import local_fs_prefixes

logger = logging.getLogger(__name__)


#: Response field names whose *value* is an asset URL. Used by
#: :meth:`UrlMapper.rewrite_document` to find URLs in an arbitrary response
#: payload without having to know its schema.
URL_VALUE_FIELDS: frozenset = frozenset(
    {
        "url",
        "base_key",
        "scene_url",
        "source_asset_url",
        "node_1_url",
        "node_2_url",
        "root_url",
        "root_node_url",
        "asset_url",
    }
)

#: Response fields that are dicts *keyed* by an asset URL: the AGS scene summary's
#: ``referenced_assets`` and the download manifest's per-file ``errors`` map.
URL_KEYED_MAPS: frozenset = frozenset({"referenced_assets", "errors"})

#: Characters Lucene's ``regexp`` syntax treats as operators. An internal prefix
#: substituted into a pattern must have these escaped so it matches literally.
LUCENE_RESERVED_CHARS: frozenset = frozenset('.?+*|{}[]()"\\#@&<>~')

#: A whole-pattern complement, ``~(inner)``. Spelled exactly as the search backend
#: spells it when it rewrites the same shape into ``bool.must_not`` — the two must
#: agree on what counts as a top-level complement or the translation and the query
#: it feeds would disagree about the pattern's inner text.
_TOP_LEVEL_COMPLEMENT = re.compile(r"~\((.+)\)")


class UrlMappingMode(str, Enum):
    """How the mapper obtains its rules."""

    #: No translation anywhere. Every public entry point is the identity function.
    off = "off"
    #: Use the explicitly configured ``rules`` list.
    rules = "rules"
    #: Derive one rule from the S3 storage-client config (``s3://bucket/`` ->
    #: the bucket's https endpoint), plus the configured ``rules``.
    s3_https = "s3_https"


class UrlRewriteRule(BaseModel):
    """One ``internal prefix -> public prefix`` mapping.

    ``aliases`` are additional public prefixes accepted on the way *in* but never
    emitted on the way out — used for the several legal spellings of an AWS S3
    https endpoint (dash-separated region, region-less), so a caller who built a
    URL by hand still resolves.
    """

    internal: str = Field(description="Internal URL prefix, e.g. 's3://my-bucket/'")
    public: str = Field(description="Public URL prefix, e.g. 'https://assets.example.com/'")
    aliases: List[str] = Field(default_factory=list, description="Extra public prefixes accepted inbound only")

    @field_validator("internal", "public")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("URL rewrite prefixes must be non-empty")
        if v != v.strip():
            raise ValueError(f"URL rewrite prefix has surrounding whitespace: {v!r}")
        return v

    @property
    def inbound_prefixes(self) -> List[str]:
        """Every public spelling this rule accepts, longest first."""
        return sorted({self.public, *self.aliases}, key=len, reverse=True)


class UrlMappingConfigError(ValueError):
    """Raised at construction time for a config whose inverse map is ambiguous."""


class UrlMappingSettings(BaseSettings):
    """``USDSEARCH_URL_MAPPING_*`` environment configuration.

    ``rules`` accepts a JSON list; ``filepath`` points at a YAML file with the same
    shape and takes precedence when both are set.
    """

    model_config = SettingsConfigDict(env_prefix="usdsearch_url_mapping_")

    mode: UrlMappingMode = UrlMappingMode.off
    rules: List[UrlRewriteRule] = Field(default_factory=list)
    filepath: Optional[str] = None
    # Bucket identity for mode=s3_https, for services that have no storage client
    # of their own (the asset-graph service talks to Neo4j, not to storage, but
    # still answers with asset URLs and so must translate them identically).
    # When unset, the bucket is read from the storage backend config instead.
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    s3_endpoint: Optional[str] = None
    #: Accept public URLs inbound but keep emitting internal ones. The Phase-1
    #: shipping state, and the escape hatch if outbound rewriting has to be rolled
    #: back without breaking clients that already learned the public form.
    inbound_only: bool = False
    #: Percent-encode the path when emitting an ``http(s)`` public URL, so what we
    #: publish is a valid URL rather than a prefix-swapped identifier. Off by
    #: default for one release: it changes ``base_key``, dependency graphs and
    #: download manifests for every key holding a reserved character. Inbound
    #: decoding needs no flag — it only widens what is accepted.
    encode_public_paths: bool = False

    @property
    def enabled(self) -> bool:
        return self.mode is not UrlMappingMode.off


def s3_https_prefixes(
    bucket_name: str,
    region_name: Optional[str] = None,
    aws_endpoint_url: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Return ``(canonical_https_prefix, alias_prefixes)`` for an S3 bucket.

    A custom endpoint means path-style addressing (``https://<endpoint>/<bucket>/``);
    otherwise AWS virtual-hosted style. AWS accepts several spellings of the latter
    — the region segment may be dot- or dash-separated, or absent — so the
    non-canonical ones come back as aliases: recognized inbound, never emitted.
    """
    if aws_endpoint_url:
        endpoint = aws_endpoint_url.rstrip("/")
        # A configured endpoint may or may not already carry a scheme.
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}"
        return f"{endpoint}/{bucket_name}/", []

    aliases = [f"https://{bucket_name}.s3.amazonaws.com/"]
    if region_name:
        aliases.append(f"https://{bucket_name}.s3-{region_name}.amazonaws.com/")
        return f"https://{bucket_name}.s3.{region_name}.amazonaws.com/", aliases
    return aliases[0], aliases[1:]


def _escape_for_lucene_regexp(literal: str) -> str:
    """Escape ``literal`` so a Lucene ``regexp`` query matches it verbatim."""
    return "".join(f"\\{c}" if c in LUCENE_RESERVED_CHARS else c for c in literal)


def _strip_regexp_escapes(pattern_head: str) -> str:
    """Drop ``\\`` escapes so an escaped literal compares equal to a bare one.

    A caller may write ``https://assets.example.com/`` or the properly escaped
    ``https://assets\\.example\\.com/``; both name the same prefix.
    """
    out: List[str] = []
    i = 0
    while i < len(pattern_head):
        if pattern_head[i] == "\\" and i + 1 < len(pattern_head):
            out.append(pattern_head[i + 1])
            i += 2
        else:
            out.append(pattern_head[i])
            i += 1
    return "".join(out)


class UrlMapper:
    """Bidirectional prefix translation between internal and public asset URLs.

    Construct via :func:`build_url_mapper` (env-driven) rather than directly,
    except in tests. A mapper built with no rules is a no-op: every method returns
    its argument unchanged, which is the default state of every deployment.
    """

    def __init__(
        self,
        rules: Optional[Sequence[UrlRewriteRule]] = None,
        inbound_only: bool = False,
        encode_public_paths: bool = False,
    ) -> None:
        self.rules: List[UrlRewriteRule] = list(rules or [])
        self.inbound_only = inbound_only
        self.encode_public_paths = encode_public_paths
        _validate_rules(self.rules)
        # Longest prefix first, so a rule for a subtree beats the bucket-wide rule.
        self._outbound: List[Tuple[str, str]] = sorted(
            ((r.internal, r.public) for r in self.rules),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        self._inbound: List[Tuple[str, str]] = sorted(
            ((prefix, r.internal) for r in self.rules for prefix in r.inbound_prefixes),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )
        self._internal_prefixes: List[str] = sorted((r.internal for r in self.rules), key=len, reverse=True)

    @property
    def enabled(self) -> bool:
        """Whether any translation happens at all."""
        return bool(self.rules)

    @property
    def emits_public(self) -> bool:
        """Whether responses carry the public form (Phase-2 state)."""
        return self.enabled and not self.inbound_only

    # -- single URLs ------------------------------------------------------

    def to_public(self, url: Optional[str]) -> Optional[str]:
        """Internal URL -> public URL. Identity when unmapped or disabled."""
        if not self.emits_public or not isinstance(url, str) or not url:
            return url
        for internal, public in self._outbound:
            if url.startswith(internal):
                return self._respell_public(public + url[len(internal) :], public)
        _record_unmapped("outbound")
        return url

    def _respell_public(self, url: str, public_prefix: str) -> str:
        """Escape the path of an emitted ``http(s)`` URL, when configured to.

        The internal path is a raw storage key and may hold characters (a space,
        most often) that prefix substitution alone would leave illegal in a URL.
        """
        if not self.encode_public_paths or not _is_http(public_prefix):
            return url
        return encode_uri_path(url)

    def to_public_list(self, urls: Optional[Iterable[str]]) -> Optional[List[str]]:
        """:meth:`to_public` over a list, preserving order and non-string items."""
        if urls is None or not self.emits_public:
            return urls
        return [self.to_public(u) if isinstance(u, str) else u for u in urls]

    def to_internal(self, url: Optional[str]) -> Optional[str]:
        """Public URL -> internal URL, accepting the internal form unchanged.

        Lenient by design: a URL that is already internal, or that matches no rule
        at all, is returned as-is. Callers must never see this raise — an unknown
        URL is the lookup's problem to report (as a 404), not this layer's.
        """
        if not self.enabled or not isinstance(url, str) or not url:
            return url
        for public, internal in self._inbound:
            if url.startswith(public):
                return internal + self._respell_internal(url[len(public) :], public)
        if not any(url.startswith(prefix) for prefix in self._internal_prefixes):
            _record_unmapped("inbound")
        return url

    def _respell_internal(self, remainder: str, public_prefix: str) -> str:
        """Unescape the path of an incoming ``http(s)`` URL.

        Unconditional, unlike its outbound counterpart: it only widens what
        resolves. Skipped for internal-to-internal rules — raw keys on both sides.
        """
        if "%" not in remainder or not _is_http(public_prefix):
            return remainder
        # A bare path fragment: give it a scheme and authority the splitter can
        # recognise, then take the path back.
        return decode_uri_path(f"x://x/{remainder}")[len("x://x/") :]

    def to_internal_list(self, urls: Optional[Iterable[str]]) -> Optional[List[str]]:
        """:meth:`to_internal` over a list, preserving order and non-string items."""
        if urls is None or not self.enabled:
            return urls
        return [self.to_internal(u) if isinstance(u, str) else u for u in urls]

    def looks_public(self, value: str) -> bool:
        """Whether ``value`` starts with a configured public prefix.

        Lets callers that multiplex URLs with other content (base64 images, say)
        widen their "is this a URL?" test to cover the public form.
        """
        if not self.enabled or not isinstance(value, str):
            return False
        return any(value.startswith(public) for public, _ in self._inbound)

    # -- free text --------------------------------------------------------

    def rewrite_text(self, text: Optional[str]) -> Optional[str]:
        """Replace internal prefixes with public ones inside a message.

        For error ``detail`` strings, so a 404 quotes the URL the caller actually
        sent rather than its internal translation. Substring replacement is fine
        here: the text is human-facing and the prefixes are distinctive.
        """
        if not self.emits_public or not isinstance(text, str) or not text:
            return text
        for internal, public in self._outbound:
            if internal in text:
                text = text.replace(internal, public)
        return text

    # -- Lucene regexp ----------------------------------------------------

    def to_internal_lucene_regexp(self, pattern: Optional[str]) -> Optional[str]:
        """Translate a ``filter_url_regexp`` written against the public form.

        Only a pattern *literally starting with* a public prefix (bare or
        backslash-escaped), optionally wrapped in a ``~()`` complement, is
        translated; anything else is returned untouched and evaluated against the
        internal URL. See ``docs/search-filters.md``.
        """
        if not self.enabled or not isinstance(pattern, str) or not pattern:
            return pattern
        # Unwrapped so the prefix scan can see past it — and because leaving a
        # complement untranslated does not merely fail to match, it inverts: the
        # search backend turns `~(inner)` into `bool.must_not` over `inner`, so an
        # `inner` matching no internal URL excludes nothing and the filter returns
        # every asset it was written to remove.
        complement = _TOP_LEVEL_COMPLEMENT.fullmatch(pattern)
        inner = complement.group(1) if complement else pattern
        translated = self._to_internal_lucene_prefix(inner)
        if translated is None:
            _record_unmapped("regexp_unmapped")
            return pattern
        return f"~({translated})" if complement else translated

    def _to_internal_lucene_prefix(self, pattern: str) -> Optional[str]:
        """``pattern`` with its leading literal public prefix swapped, or ``None``."""
        for public, internal in self._inbound:
            consumed = _match_literal_prefix(pattern, public)
            if consumed is not None:
                return _escape_for_lucene_regexp(internal) + pattern[consumed:]
        return None

    # -- whole payloads ---------------------------------------------------

    def rewrite_document(self, obj: Any, _key: Optional[str] = None) -> Any:
        """Rewrite every asset URL inside a response payload to the public form.

        Walks dicts, lists and pydantic models, rewriting values of the fields in
        :data:`URL_VALUE_FIELDS` and the keys of the maps in
        :data:`URL_KEYED_MAPS`. Containers are mutated in place where possible and
        returned, so callers can use it inline.
        """
        if not self.emits_public:
            return obj
        return self._walk(obj, _key, self.to_public, self._to_public_quiet)

    def normalize_document(self, obj: Any, _key: Optional[str] = None) -> Any:
        """The inbound mirror of :meth:`rewrite_document`: same walk, public -> internal.

        Gated on :attr:`enabled`, not :attr:`emits_public` — an ``inbound_only``
        deployment still accepts the public form.
        """
        if not self.enabled:
            return obj
        return self._walk(obj, _key, self.to_internal, self._to_internal_quiet)

    def _walk(self, obj: Any, key: Optional[str], translate: Any, translate_quiet: Any) -> Any:
        if isinstance(obj, str):
            return translate(obj) if key in URL_VALUE_FIELDS else obj
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if k in URL_KEYED_MAPS and isinstance(v, dict):
                    obj[k] = self._translate_url_keys(v, translate_quiet)
                else:
                    obj[k] = self._walk(v, k, translate, translate_quiet)
            return obj
        if isinstance(obj, list):
            return [self._walk(item, key, translate, translate_quiet) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self._walk(item, key, translate, translate_quiet) for item in obj)
        if isinstance(obj, BaseModel):
            # Declared fields (including those set by model_construct) live in
            # __dict__; on an extra="allow" model the undeclared ones live in
            # __pydantic_extra__ instead, and the index puts real URLs there.
            for field_name, value in list(obj.__dict__.items()):
                if field_name in URL_KEYED_MAPS and isinstance(value, dict):
                    setattr(obj, field_name, self._translate_url_keys(value, translate_quiet))
                else:
                    rewritten = self._walk(value, field_name, translate, translate_quiet)
                    if rewritten is not value:
                        setattr(obj, field_name, rewritten)
            extra = getattr(obj, "__pydantic_extra__", None)
            if isinstance(extra, dict):
                self._walk(extra, None, translate, translate_quiet)
            return obj
        return obj

    def _translate_url_keys(self, mapping: dict, translate_quiet: Any) -> dict:
        """Translate the keys of a URL-keyed map."""
        # Quietly: `errors` is a generic field name, so a map that turns out not to
        # be keyed by asset URL would inflate the unmapped metric and hide a real
        # misconfiguration.
        return {translate_quiet(k) if isinstance(k, str) else k: v for k, v in mapping.items()}

    def _to_public_quiet(self, url: str) -> str:
        for internal, public in self._outbound:
            if url.startswith(internal):
                return self._respell_public(public + url[len(internal) :], public)
        return url

    def _to_internal_quiet(self, url: str) -> str:
        for public, internal in self._inbound:
            if url.startswith(public):
                return internal + self._respell_internal(url[len(public) :], public)
        return url


def _is_http(prefix: str) -> bool:
    """Whether a rewrite prefix addresses over HTTP, so its path must be escaped."""
    return prefix.lower().startswith(("http://", "https://"))


def _match_literal_prefix(pattern: str, prefix: str) -> Optional[int]:
    """How many chars of ``pattern`` spell ``prefix`` literally, or ``None``.

    Walks the pattern one source character at a time (a backslash escape counting
    as one) so an escaped spelling of the prefix matches an unescaped one.
    """
    consumed = 0
    matched: List[str] = []
    while len("".join(matched)) < len(prefix):
        if consumed >= len(pattern):
            return None
        if pattern[consumed] == "\\":
            if consumed + 1 >= len(pattern):
                return None
            matched.append(_strip_regexp_escapes(pattern[consumed : consumed + 2]))
            consumed += 2
        else:
            matched.append(pattern[consumed])
            consumed += 1
    return consumed if "".join(matched) == prefix else None


def _validate_rules(rules: Sequence[UrlRewriteRule]) -> None:
    """Reject configs whose inverse map would be ambiguous or non-idempotent.

    Failing at startup is the point: a half-valid mapping produces silent 404s and
    empty result sets rather than errors, which is far more expensive to diagnose
    than a pod that refuses to start.
    """
    internals = [r.internal for r in rules]
    if len(set(internals)) != len(internals):
        raise UrlMappingConfigError(f"Duplicate internal prefixes in URL mapping rules: {sorted(internals)}")

    publics: List[str] = [p for r in rules for p in r.inbound_prefixes]
    if len(set(publics)) != len(publics):
        raise UrlMappingConfigError(f"Duplicate public prefixes in URL mapping rules: {sorted(publics)}")

    for a in publics:
        for b in publics:
            if a != b and b.startswith(a):
                raise UrlMappingConfigError(
                    f"Ambiguous URL mapping: public prefix {a!r} is a prefix of {b!r}; "
                    "the reverse mapping would not be well defined"
                )
    # A public prefix that overlaps an internal one makes it impossible to tell
    # which direction a URL is already in, breaking idempotence.
    for public in publics:
        for internal in internals:
            if public.startswith(internal) or internal.startswith(public):
                raise UrlMappingConfigError(
                    f"Ambiguous URL mapping: public prefix {public!r} overlaps internal prefix {internal!r}"
                )


def _load_rules_from_file(path: str) -> List[UrlRewriteRule]:
    import yaml

    with open(path, "r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or []
    if isinstance(payload, dict):  # tolerate a {"rules": [...]} wrapper
        payload = payload.get("rules", [])
    if not isinstance(payload, list):
        raise UrlMappingConfigError(f"URL mapping file {path} must contain a list of rules")
    return [UrlRewriteRule(**item) for item in payload]


def _storage_config_from_env() -> Any:
    """Load the configured storage backend's client config from the environment.

    Imported lazily: ``storage_client.s3`` imports this module for its https
    prefixes, so a module-level import here would be circular.
    """
    from search_utils.storage_client.config import (
        StorageConfig,
        get_backend_config_class,
    )

    backend_type = StorageConfig().storage_backend_type
    try:
        return get_backend_config_class(backend_type)()
    except Exception as exc:  # noqa: BLE001 — turned into a clear config error below
        raise UrlMappingConfigError(
            f"URL mapping could not read the {backend_type.value} storage backend config "
            f"needed to derive public URLs: {exc}"
        ) from exc


def build_url_mapper(
    settings: Optional[UrlMappingSettings] = None,
    storage_config: Any = None,
) -> UrlMapper:
    """Build a mapper from ``USDSEARCH_URL_MAPPING_*`` settings.

    ``storage_config`` is the service's S3 client config (anything exposing
    ``bucket_name`` / ``region_name`` / ``aws_endpoint_url``); it is only consulted
    for ``mode=s3_https``, where it saves the operator from spelling the bucket
    endpoint out by hand.
    """
    settings = settings or UrlMappingSettings()
    if not settings.enabled:
        return UrlMapper()

    rules: List[UrlRewriteRule] = list(settings.rules)
    if settings.filepath:
        rules = _load_rules_from_file(settings.filepath)

    if settings.mode is UrlMappingMode.s3_https:
        # Explicit bucket identity wins; otherwise read it off the storage backend
        # config. Both paths end in the same s3_https_prefixes() call, so every
        # service derives byte-identical prefixes however it was configured.
        if settings.s3_bucket:
            bucket, region, endpoint = settings.s3_bucket, settings.s3_region, settings.s3_endpoint
        else:
            if storage_config is None:
                storage_config = _storage_config_from_env()
            bucket = getattr(storage_config, "bucket_name", None)
            region = getattr(storage_config, "region_name", None)
            endpoint = getattr(storage_config, "aws_endpoint_url", None)
        if not bucket:
            raise UrlMappingConfigError(
                "USDSEARCH_URL_MAPPING_MODE=s3_https requires an S3 bucket: set "
                "USDSEARCH_URL_MAPPING_S3_BUCKET, or run this service with an S3 storage backend"
            )
        public, aliases = s3_https_prefixes(bucket_name=bucket, region_name=region, aws_endpoint_url=endpoint)
        rules.append(UrlRewriteRule(internal=f"s3://{bucket}/", public=public, aliases=aliases))

    mapper = UrlMapper(
        rules=rules,
        inbound_only=settings.inbound_only,
        encode_public_paths=settings.encode_public_paths,
    )
    logger.info(
        "URL mapping enabled (mode=%s, inbound_only=%s, encode_public_paths=%s): %s",
        settings.mode.value,
        settings.inbound_only,
        settings.encode_public_paths,
        ", ".join(f"{r.internal} -> {r.public}" for r in mapper.rules) or "no rules",
    )
    return mapper


# -- process-wide instance ------------------------------------------------
#
# Pydantic validators (the inbound half) have no access to app state, so the
# mapper lives in a module-level slot. It is configuration, not per-request state:
# built once from the environment, or installed explicitly by a service's lifespan
# when it needs to pass its storage config in for the s3_https preset.

_MAPPER: Optional[UrlMapper] = None
#: Undoes LocalFSPathMiddleware's response rewrite; ``False`` = not built yet.
_LOCAL_FS_MAPPER: Any = False


def get_url_mapper() -> UrlMapper:
    """The process-wide mapper, built lazily from the environment on first use."""
    global _MAPPER
    if _MAPPER is None:
        try:
            _MAPPER = build_url_mapper()
        except UrlMappingConfigError:
            raise
        except Exception as exc:  # noqa: BLE001 — never let config parsing break a request path
            logger.error("Failed to build URL mapper from the environment; disabling translation: %s", exc)
            _MAPPER = UrlMapper()
    return _MAPPER


def set_url_mapper(mapper: UrlMapper) -> None:
    """Install the process-wide mapper (service lifespan, and tests)."""
    global _MAPPER
    _MAPPER = mapper


def reset_url_mapper() -> None:
    """Drop the cached mapper so the next call rebuilds it from the environment."""
    global _MAPPER, _LOCAL_FS_MAPPER
    _MAPPER = None
    _LOCAL_FS_MAPPER = False


def _get_local_fs_mapper() -> Optional[UrlMapper]:
    """A mapper whose public form is the local-filesystem path, or ``None`` outside local-fs mode."""
    global _LOCAL_FS_MAPPER
    if _LOCAL_FS_MAPPER is False:
        prefixes = local_fs_prefixes()
        _LOCAL_FS_MAPPER = (
            UrlMapper(rules=[UrlRewriteRule(internal=prefixes[1], public=prefixes[0])]) if prefixes else None
        )
    return _LOCAL_FS_MAPPER


def configure_url_mapper(storage_config: Any = None) -> UrlMapper:
    """Build the mapper from the environment + storage config and install it."""
    mapper = build_url_mapper(storage_config=storage_config)
    set_url_mapper(mapper)
    return mapper


# -- convenience wrappers used as pydantic BeforeValidators ---------------


def to_internal_url(value: Any) -> Any:
    """``BeforeValidator`` entry point for a single URL-valued request field."""
    return get_url_mapper().to_internal(value) if isinstance(value, str) else value


def to_internal_url_list(value: Any) -> Any:
    """``BeforeValidator`` entry point for a list of URL-valued request fields."""
    if isinstance(value, list):
        return get_url_mapper().to_internal_list(value)
    return to_internal_url(value)


def to_internal_url_or_passthrough(value: Any) -> Any:
    """Normalize only entries that look like an asset URL.

    For fields that multiplex URLs with other content — ``image_similarity_search``
    carries base64 image data as well as asset references.
    """
    mapper = get_url_mapper()
    if isinstance(value, list):
        return [to_internal_url_or_passthrough(item) for item in value]
    if isinstance(value, str) and mapper.looks_public(value):
        return mapper.to_internal(value)
    return value


def to_internal_lucene_regexp(value: Any) -> Any:
    """``BeforeValidator`` entry point for ``filter_url_regexp``."""
    return get_url_mapper().to_internal_lucene_regexp(value) if isinstance(value, str) else value


def to_public_url(value: Any) -> Any:
    """Outbound translation for a single URL."""
    return get_url_mapper().to_public(value) if isinstance(value, str) else value


def to_public_url_list(value: Any) -> Any:
    """Outbound translation for a response whose body is a bare list of URLs."""
    if isinstance(value, list):
        return get_url_mapper().to_public_list(value)
    return to_public_url(value)


#: Annotate a request field naming an asset with this to accept either URL form.
#: Normalization happens during request parsing, so everything downstream — index
#: lookups, ACL checks, cache keys, cursors — only ever sees the internal form.
AssetUrl = Annotated[str, BeforeValidator(to_internal_url)]
AssetUrlList = Annotated[List[str], BeforeValidator(to_internal_url_list)]
#: For a field that multiplexes asset URLs with inline base64 image data.
AssetUrlOrImage = Annotated[List[str], BeforeValidator(to_internal_url_or_passthrough)]
#: For a Lucene regexp over asset URLs (literal-prefix translation only).
LuceneUrlRegexp = Annotated[str, BeforeValidator(to_internal_lucene_regexp)]


def rewrite_response_document(obj: Any) -> Any:
    """Outbound translation for a whole response payload."""
    return get_url_mapper().rewrite_document(obj)


def normalize_upstream_document(obj: Any) -> Any:
    """Inbound translation for a whole payload received from another service.

    Apply where the response is read, before its URLs are used for anything.
    Also undoes the local-filesystem path rewrite ``LocalFSPathMiddleware`` applies
    to the upstream service's JSON responses.
    """
    local_fs = _get_local_fs_mapper()
    if local_fs is not None:
        # Quietly: dependencies outside the bucket (MDL search paths, other
        # backends) are expected here, not an unmapped-URL misconfiguration.
        obj = local_fs._walk(obj, None, local_fs._to_internal_quiet, local_fs._to_internal_quiet)
    return get_url_mapper().normalize_document(obj)


def rewrite_response_text(text: Any) -> Any:
    """Outbound translation for a human-facing message (error ``detail``)."""
    return get_url_mapper().rewrite_text(text) if isinstance(text, str) else text


# -- metrics --------------------------------------------------------------

_UNMAPPED_COUNTER = None


def _record_unmapped(direction: str) -> None:
    """Count URLs no rule matched, so a partial config is visible in metrics.

    A gap here is silent by design (the URL passes through unchanged), which is the
    right behaviour but a poor diagnostic — hence the counter.
    """
    global _UNMAPPED_COUNTER
    if os.getenv("USDSEARCH_URL_MAPPING_METRICS", "true").lower() in ("0", "false", "no"):
        return
    if _UNMAPPED_COUNTER is None:
        try:
            from prometheus_client import Counter

            _UNMAPPED_COUNTER = Counter(
                "usdsearch_url_mapping_unmapped_total",
                "Asset URLs that matched no configured URL-mapping rule",
                labelnames=["direction"],
            )
        except Exception:  # noqa: BLE001 — metrics must never break a request
            _UNMAPPED_COUNTER = False
    if _UNMAPPED_COUNTER:
        _UNMAPPED_COUNTER.labels(direction=direction).inc()


__all__ = [
    "URL_KEYED_MAPS",
    "URL_VALUE_FIELDS",
    "AssetUrl",
    "AssetUrlList",
    "AssetUrlOrImage",
    "LuceneUrlRegexp",
    "UrlMapper",
    "UrlMappingConfigError",
    "UrlMappingMode",
    "UrlMappingSettings",
    "UrlRewriteRule",
    "build_url_mapper",
    "configure_url_mapper",
    "get_url_mapper",
    "normalize_upstream_document",
    "reset_url_mapper",
    "rewrite_response_document",
    "rewrite_response_text",
    "s3_https_prefixes",
    "set_url_mapper",
    "to_internal_lucene_regexp",
    "to_internal_url",
    "to_internal_url_list",
    "to_internal_url_or_passthrough",
    "to_public_url",
    "to_public_url_list",
]
