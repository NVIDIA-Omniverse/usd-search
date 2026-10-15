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

"""Declarative sidecar/package metadata ingestion.

Reads a YAML catalog of "sources" describing metadata files that ship next to
a USD file (or under a package root above it) and flattens them into the same
``prims[default_prim]["properties"]`` dict ``usd_deps.build_graph_document``
already merges ``SimReady_Metadata`` custom-layer data into. See
``docs/plans/sidecar-package-metadata.md`` for the design this implements.

Kept free of ``omni``/``pxr`` imports (same rule as ``prim_properties.py``) so
the extraction logic is unit-testable without a Kit runtime. All storage
access is injected via the ``read_fn``/``list_fn`` callables passed to
:func:`collect_sidecar_metadata`.
"""

import fnmatch
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Generic,
    Hashable,
    List,
    Optional,
    Tuple,
    TypeVar,
)

import yaml
from graph_builder.redaction import redact_url

logger = logging.getLogger(__name__)

#: Reads one file's raw bytes, or ``None`` if it does not exist / cannot be read.
ReadFn = Callable[[str], Optional[bytes]]
#: Lists filenames (not full paths) directly under a directory URL, or ``None``
#: if the file does not exist or the backend cannot list it.
ListFn = Callable[[str], Optional[List[str]]]

_SUPPORTED_LOCATIONS = {"sibling", "package_root"}
_SUPPORTED_KINDS = {"flatten", "list_membership", "array_match_flatten"}
# The only symbolic match target implemented today. Kept as an explicit catalog
# (not a free string) so a config typo fails at load time instead of silently
# matching nothing at build time.
_SUPPORTED_MATCH_SYMBOLS = {"asset_relative_path"}

_DEFAULT_PACKAGE_ROOT_MAX_DEPTH = 6

# Recursion guard for _flatten: a maliciously (or accidentally) deeply nested
# sidecar JSON must degrade to "stop flattening deeper", not a RecursionError
# — sidecar files are optional enrichment, and a stack overflow is a worse
# failure mode than a coarser property.
_MAX_FLATTEN_DEPTH = 64

_K = TypeVar("_K", bound=Hashable)
_V = TypeVar("_V")


class BoundedCache(OrderedDict, Generic[_K, _V]):
    """A dict capped at ``maxsize`` entries, evicting the oldest on overflow.

    Used for both the package-root-walk cache and the parsed-JSON cache below.
    A long-lived Kit worker process reuses one of these across many builds; an
    unbounded dict would grow for as long as the process sees new directories
    or sidecar files. Eviction order does not need to be true LRU (recency of
    *lookups* isn't tracked) — insertion-order FIFO is enough to keep memory
    bounded without extra bookkeeping on every cache hit.
    """

    def __init__(self, maxsize: int = 10_000) -> None:
        super().__init__()
        self._maxsize = maxsize

    def __setitem__(self, key: _K, value: _V) -> None:
        super().__setitem__(key, value)
        if len(self) > self._maxsize:
            self.popitem(last=False)


class SidecarConfigError(ValueError):
    """A malformed ``sidecar_metadata.yaml``. Fails config load, never a build."""


@dataclass(frozen=True)
class ExtractSpec:
    kind: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SidecarSource:
    name: str
    location: str  # "sibling" | "package_root"
    filename: str  # "{stem}.json"-style template, or a glob for package_root
    prefix: str  # "sidecar_"-style template, may reference extract-provided vars
    extract: ExtractSpec
    anchor: Optional[str] = None  # required when location == "package_root"


@dataclass(frozen=True)
class SidecarMetadataConfig:
    sources: Tuple[SidecarSource, ...] = ()
    package_root_max_depth: int = _DEFAULT_PACKAGE_ROOT_MAX_DEPTH


def load_sidecar_config(path: Optional[str]) -> Optional[SidecarMetadataConfig]:
    """Load a sidecar-metadata catalog from ``path``, or a no-op config.

    Returns ``None`` (the whole mechanism becomes a no-op) when ``path`` is
    unset, or when the file cannot be read/parsed — mirrors how an unset
    ``USDSEARCH_LLM_PARSING_FIELDS_FILEPATH`` falls back to "no extra
    catalog" rather than failing the service. A malformed config is a
    deployment mistake, but it must never turn into a build failure for
    every asset the builder processes.
    """
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as config_file:
            raw = yaml.safe_load(config_file) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not load sidecar metadata config %r (%s); sidecar metadata disabled", path, exc)
        return None
    try:
        return parse_sidecar_config(raw)
    except SidecarConfigError as exc:
        logger.warning("Invalid sidecar metadata config %r (%s); sidecar metadata disabled", path, exc)
        return None
    except Exception:  # noqa: BLE001 — belt-and-suspenders: parse_sidecar_config validates every
        # shape it indexes into, but a config mistake must degrade to "sidecar metadata off" no
        # matter what, never abort this module's import and take every asset build down with it.
        logger.warning(
            "Unexpected error parsing sidecar metadata config %r; sidecar metadata disabled", path, exc_info=True
        )
        return None


def parse_sidecar_config(raw: Any) -> SidecarMetadataConfig:
    """Parse+validate an already-loaded config dict. Raises :class:`SidecarConfigError`.

    Validates the raw YAML/JSON shape (root a mapping, ``sources`` a list of
    mappings) before indexing into it — a scalar or list document, or a
    non-mapping source entry, must fail with :class:`SidecarConfigError` like
    every other config mistake, not with a raw ``AttributeError``/``TypeError``
    that would escape ``load_sidecar_config``'s narrower ``except`` clause and
    abort the whole builder's module import.
    """
    if not isinstance(raw, dict):
        raise SidecarConfigError(f"sidecar metadata config root must be a mapping, got {type(raw).__name__}")

    max_depth = raw.get("package_root_max_depth", _DEFAULT_PACKAGE_ROOT_MAX_DEPTH)
    if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0:
        raise SidecarConfigError(f"package_root_max_depth must be a non-negative int, got {max_depth!r}")

    sources_raw = raw.get("sources") or []
    if not isinstance(sources_raw, list):
        raise SidecarConfigError(f"'sources' must be a list, got {type(sources_raw).__name__}")

    sources: List[SidecarSource] = []
    seen_names: set = set()
    seen_prefixes: set = set()
    for entry in sources_raw:
        if not isinstance(entry, dict):
            raise SidecarConfigError(f"each sidecar source must be a mapping, got {type(entry).__name__}")
        source = _parse_source(entry)
        if source.name in seen_names:
            raise SidecarConfigError(f"duplicate sidecar source name {source.name!r}")
        if source.prefix in seen_prefixes:
            raise SidecarConfigError(
                f"sidecar source {source.name!r} reuses prefix {source.prefix!r} — every "
                "source must have a distinct prefix so their properties cannot collide"
            )
        seen_names.add(source.name)
        seen_prefixes.add(source.prefix)
        sources.append(source)

    return SidecarMetadataConfig(sources=tuple(sources), package_root_max_depth=max_depth)


def _parse_source(entry: Dict[str, Any]) -> SidecarSource:
    try:
        name = entry["name"]
        location = entry["location"]
        filename = entry["filename"]
        prefix = entry["prefix"]
    except KeyError as exc:
        raise SidecarConfigError(f"sidecar source missing required field {exc}") from exc

    if location not in _SUPPORTED_LOCATIONS:
        raise SidecarConfigError(f"source {name!r}: unsupported location {location!r}")

    anchor = entry.get("anchor")
    if location == "package_root" and not anchor:
        raise SidecarConfigError(f"source {name!r}: location 'package_root' requires 'anchor'")

    extract_entry = entry.get("extract") or {"kind": "flatten"}
    if not isinstance(extract_entry, dict):
        raise SidecarConfigError(f"source {name!r}: 'extract' must be a mapping, got {type(extract_entry).__name__}")
    extract_raw = dict(extract_entry)
    kind = extract_raw.pop("kind", "flatten")
    if kind not in _SUPPORTED_KINDS:
        raise SidecarConfigError(f"source {name!r}: unsupported extract.kind {kind!r}")

    match_against = extract_raw.get("match_against")
    if match_against is not None and match_against not in _SUPPORTED_MATCH_SYMBOLS:
        raise SidecarConfigError(f"source {name!r}: unsupported extract.match_against {match_against!r}")
    if kind in ("list_membership", "array_match_flatten") and match_against is None:
        raise SidecarConfigError(f"source {name!r}: extract.kind {kind!r} requires 'match_against'")

    return SidecarSource(
        name=name,
        location=location,
        filename=filename,
        prefix=prefix,
        extract=ExtractSpec(kind=kind, params=extract_raw),
        anchor=anchor,
    )


# --------------------------------------------------------------------------
# Pure dict helpers: JSON-path lookup, flattening, per-kind extraction.
# --------------------------------------------------------------------------


def _json_path(obj: Any, path: Optional[str]) -> Any:
    """Look up a dotted path (``"a.b.c"``) of dict keys. No list-index support."""
    if not path:
        return obj
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _flatten(obj: Any, parent_key: str = "", sep: str = "__", *, depth: int = 0) -> Dict[str, Any]:
    """Flatten nested dicts/lists into ``parent__child__0``-style keys.

    Lists get an index suffix (rather than being joined to a string or
    dropped) so numeric list entries — e.g. a 3-element bounding box — stay
    individually filterable, matching how axis-suffixed dimension fields
    work elsewhere in this pipeline.

    ``depth`` guards against a pathologically (or maliciously) nested sidecar
    file exhausting the call stack: past ``_MAX_FLATTEN_DEPTH`` the remaining
    substructure is kept as-is under its key instead of recursing further —
    a coarser property beats a RecursionError killing this asset's build.
    """
    items: Dict[str, Any] = {}
    if depth >= _MAX_FLATTEN_DEPTH:
        if parent_key:
            items[parent_key] = obj
        return items
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else str(key)
            items.update(_flatten(value, new_key, sep, depth=depth + 1))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            new_key = f"{parent_key}{sep}{index}" if parent_key else str(index)
            items.update(_flatten(value, new_key, sep, depth=depth + 1))
    elif parent_key:
        items[parent_key] = obj
    return items


def _exclude_top_level(obj: Any, keys: List[str]) -> Any:
    if not keys or not isinstance(obj, dict):
        return obj
    return {k: v for k, v in obj.items() if k not in keys}


def _extract_flatten(obj: Any, params: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    pruned = _exclude_top_level(obj, params.get("exclude_paths") or [])
    return _flatten(pruned), {}


def _extract_list_membership(
    obj: Any, params: Dict[str, Any], *, match_value: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    items = _json_path(obj, params["list_path"]) or []
    output_key = params["output_key"]
    return {output_key: match_value in items}, {}


def _extract_array_match_flatten(
    obj: Any, params: Dict[str, Any], *, match_value: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Find the one array entry describing this asset; flatten only that entry.

    ``array_path`` points at a JSON array of per-asset records (e.g. a
    SimReady conformance file's ``assets``); ``match_field`` is compared
    against ``match_value`` (this asset's package-relative path) to find the
    single matching record. Everything else in the file — every other
    asset's record — is discarded, which is the whole point of this kind
    (see docs/plans/sidecar-package-metadata.md §0/§5: naive flattening would
    silently attribute another asset's data to this one).

    ``profile_path`` (optional) is looked up against the *whole file*, not
    the matched entry — e.g. a conformance file's top-level ``profile``
    field — and returned as a template variable for the source's ``prefix``.
    """
    array = _json_path(obj, params["array_path"]) or []
    match_field = params["match_field"]
    value_path = params.get("value_path")
    profile_path = params.get("profile_path")

    template_vars: Dict[str, Any] = {}
    if profile_path:
        profile_value = _json_path(obj, profile_path)
        if profile_value is not None:
            template_vars["profile"] = profile_value

    entry = next(
        (item for item in array if isinstance(item, dict) and item.get(match_field) == match_value),
        None,
    )
    if entry is None:
        return {}, template_vars

    target = _json_path(entry, value_path) if value_path else entry
    return _flatten(target), template_vars


def _run_extract(
    extract: ExtractSpec, obj: Any, *, match_value: Optional[str]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if extract.kind == "flatten":
        return _extract_flatten(obj, extract.params)
    if match_value is None:
        # Config validation already requires match_against for these kinds, and
        # match_value is only None for a `sibling` source — which can only be
        # paired with `flatten` today. Defensive, not expected to be reachable.
        raise SidecarConfigError(f"extract.kind {extract.kind!r} requires a 'package_root' source")
    if extract.kind == "list_membership":
        return _extract_list_membership(obj, extract.params, match_value=match_value)
    return _extract_array_match_flatten(obj, extract.params, match_value=match_value)


# --------------------------------------------------------------------------
# Path/template helpers.
# --------------------------------------------------------------------------


def _dirname(url: str) -> str:
    idx = url.rfind("/")
    return url[:idx] if idx >= 0 else ""


def _basename(url: str) -> str:
    idx = url.rfind("/")
    return url[idx + 1 :] if idx >= 0 else url


def _stem(url: str) -> str:
    name = _basename(url)
    dot = name.rfind(".")
    return name[:dot] if dot > 0 else name


def _join(directory: str, relative: str) -> str:
    if not directory:
        return relative
    return f"{directory.rstrip('/')}/{relative.lstrip('/')}"


def _render_template(template: str, variables: Dict[str, Any]) -> str:
    try:
        return template.format(**variables)
    except KeyError as exc:
        raise SidecarConfigError(f"template {template!r} references unknown variable {exc}") from exc


_MISSING = object()  # cache sentinel distinguishing "not yet read" from "read and empty/None"


def _read_json(url: str, read_fn: ReadFn) -> Optional[Any]:
    raw = read_fn(url)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        logger.warning("Malformed JSON sidecar file %s: %s", redact_url(url), exc)
        return None


def _read_json_cached(url: str, read_fn: ReadFn, cache: Optional[Dict[str, Any]]) -> Optional[Any]:
    """``_read_json``, memoized by URL when a cache is provided.

    A package-level source (e.g. a conformance file) is read once per *asset*
    by default, even though its content is the same for every asset in that
    package. Caching by URL turns that into one read+parse per package per
    process — the fix mirrors ``find_package_root``'s own caching, applied to
    file *content* rather than the root-walk outcome.
    """
    if cache is None:
        return _read_json(url, read_fn)
    cached = cache.get(url, _MISSING)
    if cached is not _MISSING:
        return cached
    value = _read_json(url, read_fn)
    cache[url] = value
    return value


# --------------------------------------------------------------------------
# Discovery: sibling files and the package_root walk.
# --------------------------------------------------------------------------


def find_package_root(
    start_dir: str,
    *,
    anchor: str,
    max_depth: int,
    crawl_root: Optional[str],
    read_fn: ReadFn,
    cache: Dict[Tuple[str, str], Optional[str]],
) -> Optional[str]:
    """Walk up from ``start_dir`` looking for a directory containing ``anchor``.

    Not finding one (anchor absent within ``max_depth``, or the walk reaches
    ``crawl_root`` first) is the expected common case for an asset that is
    not part of a package — returns ``None``, not an error. See the
    walk-semantics section of docs/plans/sidecar-package-metadata.md §2.2.
    """
    key = (start_dir, anchor)
    if key in cache:
        return cache[key]

    current = start_dir
    root: Optional[str] = None
    for _ in range(max_depth + 1):
        if read_fn(_join(current, anchor)) is not None:
            root = current
            break
        if crawl_root and current.rstrip("/") == crawl_root.rstrip("/"):
            break
        parent = _dirname(current)
        if not parent or parent == current:
            break
        current = parent

    cache[key] = root
    return root


def _resolve_package_files(package_root: str, filename_template: str, *, list_fn: Optional[ListFn]) -> List[str]:
    """Resolve a (possibly glob) ``filename`` under a resolved package root.

    A plain filename resolves to exactly one URL. A glob (containing ``*``,
    e.g. ``.metadata/com.nvidia.simready.conformance.*.json`` for the
    Package/Package-Candidate/... profile files) needs a directory listing —
    with no ``list_fn`` configured, or an empty/failed listing, it resolves
    to zero files rather than erroring: the same best-effort posture as a
    missing file.
    """
    if "*" not in filename_template:
        return [_join(package_root, filename_template)]

    directory_part = _dirname(filename_template)
    pattern = _basename(filename_template)
    directory_url = _join(package_root, directory_part) if directory_part else package_root

    if list_fn is None:
        logger.debug(
            "Glob sidecar filename %r needs directory listing but none is configured; skipping", filename_template
        )
        return []

    names = list_fn(directory_url)
    if not names:
        return []

    return [_join(directory_url, name) for name in sorted(names) if fnmatch.fnmatch(name, pattern)]


# --------------------------------------------------------------------------
# Orchestration.
# --------------------------------------------------------------------------


def collect_sidecar_metadata(
    fname: str,
    *,
    config: Optional[SidecarMetadataConfig],
    read_fn: ReadFn,
    list_fn: Optional[ListFn] = None,
    crawl_root: Optional[str] = None,
    package_root_cache: Optional[Dict[Tuple[str, str], Optional[str]]] = None,
    content_cache: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect every configured source's metadata for the USD file at ``fname``.

    Returns one flat ``{prefixed_key: value}`` dict, ready to merge onto the
    default prim's properties. ``config=None`` (or an empty catalog) is a
    no-op — the whole mechanism is opt-in. Any single source's failure
    (unreadable file, malformed JSON, ...) is logged and skipped; it never
    raises out of this function, since sidecar metadata is optional
    enrichment, not a required build input.

    Sources are folded into the result dict in ``config.sources`` order via
    plain ``dict.update``, so if two sources' rendered keys ever coincide, the
    later source in the list wins. The caller (``usd_deps.build_graph_document``)
    merges this result onto the default prim's properties *last* — after
    native USD prim properties and after SimReady custom-layer metadata — via
    ``merge_prim_properties()`` (also a ``dict.update``), so a sidecar-derived
    key always wins over a same-named native or SimReady property. Per-source
    ``prefix`` (validated unique across sources, see :func:`parse_sidecar_config`)
    keeps this collision case rare in practice, but it is not checked against
    ``simready_metadata_`` or against native USD property names.

    ``package_root_cache`` and ``content_cache`` are optional — pass in a
    shared (ideally :class:`BoundedCache`) dict across many calls in the same
    process so a package's root-walk outcome and each package-level file's
    parsed content are computed once per package rather than once per asset.
    Without them, a fresh unbounded dict is used per call (correct, just not
    shared — the common case for a single ad hoc invocation, e.g. a test).
    """
    if config is None or not config.sources:
        return {}

    root_cache = package_root_cache if package_root_cache is not None else {}
    json_cache = content_cache if content_cache is not None else {}
    asset_dir = _dirname(fname)
    stem = _stem(fname)

    result: Dict[str, Any] = {}
    for source in config.sources:
        try:
            result.update(
                _collect_one_source(
                    fname,
                    asset_dir=asset_dir,
                    stem=stem,
                    source=source,
                    config=config,
                    read_fn=read_fn,
                    list_fn=list_fn,
                    crawl_root=crawl_root,
                    root_cache=root_cache,
                    json_cache=json_cache,
                )
            )
        except Exception:  # noqa: BLE001 — one bad source must not sink the others or the build
            logger.warning("Sidecar metadata source %r failed for %s", source.name, fname, exc_info=True)
    return result


def _collect_one_source(
    fname: str,
    *,
    asset_dir: str,
    stem: str,
    source: SidecarSource,
    config: SidecarMetadataConfig,
    read_fn: ReadFn,
    list_fn: Optional[ListFn],
    crawl_root: Optional[str],
    root_cache: Dict[Tuple[str, str], Optional[str]],
    json_cache: Dict[str, Any],
) -> Dict[str, Any]:
    if source.location == "sibling":
        url = _join(asset_dir, _render_template(source.filename, {"stem": stem}))
        obj = _read_json_cached(url, read_fn, json_cache)
        if obj is None:
            return {}
        flattened, _ = _run_extract(source.extract, obj, match_value=None)
        return {f"{source.prefix}{key}": value for key, value in flattened.items()}

    # source.location == "package_root"
    root = find_package_root(
        asset_dir,
        anchor=source.anchor,
        max_depth=config.package_root_max_depth,
        crawl_root=crawl_root,
        read_fn=read_fn,
        cache=root_cache,
    )
    if root is None:
        return {}

    asset_relative_path = fname[len(root) :].lstrip("/") if fname.startswith(root) else _basename(fname)

    merged: Dict[str, Any] = {}
    for url in _resolve_package_files(root, source.filename, list_fn=list_fn):
        # Cached: a package-level file (e.g. a conformance file listing every
        # asset) is read+parsed once per process, not once per asset that
        # happens to share the package — see _read_json_cached.
        obj = _read_json_cached(url, read_fn, json_cache)
        if obj is None:
            continue
        flattened, template_vars = _run_extract(source.extract, obj, match_value=asset_relative_path)
        if not flattened:
            continue
        prefix = _render_template(source.prefix, template_vars)
        for key, value in flattened.items():
            merged[f"{prefix}{key}"] = value
    return merged
