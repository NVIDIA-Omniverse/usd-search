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

"""Merge OpenAPI specs from multiple FastAPI services into a single unified spec.

Replaces the legacy `_old/api-gateway/merge.sh` shell+npm pipeline. Reads a
declarative merge config (`openapi-merge.json`), pulls each input spec from a
URL or local path, applies path/operationId rewrites and tag-based filtering,
validates the result, and writes a merged spec.

Sources are bound to logical names declared in the config (e.g. ``ags``,
``info``, ``search``). Each source URL is provided via ``--source name=url`` on
the CLI, or via env vars (``${name}_url``) for back-compat with the legacy
shell script.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import yaml
from openapi_spec_validator import validate as validate_spec
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

logger = logging.getLogger("openapi_merge")

DEFAULT_CONFIG = "openapi-merge.json"
DEFAULT_RETRIES = 60
DEFAULT_RETRY_DELAY = 2.0


def fetch_spec(url_or_path: str, retries: int, delay: float) -> dict[str, Any]:
    """Fetch an OpenAPI spec from an HTTP(S) URL or read it from disk.

    Local paths bypass retry/backoff; HTTP fetches retry on network/HTTP errors.
    """
    if url_or_path.startswith(("http://", "https://")):
        last_err: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                logger.info("Downloading %s (attempt %d/%d)", url_or_path, attempt, retries)
                resp = httpx.get(url_or_path, timeout=30.0)
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last_err = exc
                logger.warning("Failed: %s — retrying in %.1fs", exc, delay)
                time.sleep(delay)
        raise RuntimeError(f"Failed to download {url_or_path} after {retries} attempts: {last_err}")

    path = Path(url_or_path)
    logger.info("Reading %s", path)
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(text)
    return json.loads(text)


def apply_pre_merge_rewrites(spec: dict[str, Any], rewrites: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply per-spec path/operationId/summary rewrites before merging.

    Mirrors the sed/jq stage of the legacy ``merge.sh``:
      - ``renamePath`` — rename one exact path (and optionally its operation summary)
      - ``renamePathPrefix`` — rename every path that starts with a prefix
      - ``operationIdRewrites`` — replace operation IDs anywhere in the spec
    """
    spec = deepcopy(spec)
    paths = spec.get("paths", {})
    new_paths: dict[str, Any] = {}

    rename_map: dict[str, str] = {}
    prefix_map: list[tuple[str, str]] = []
    op_id_map: dict[str, str] = {}
    summary_overrides: list[tuple[str, dict[str, str]]] = []

    for rw in rewrites:
        kind = rw.get("type")
        if kind == "renamePath":
            rename_map[rw["from"]] = rw["to"]
            if "summaryRewrites" in rw:
                summary_overrides.append((rw["to"], rw["summaryRewrites"]))
        elif kind == "renamePathPrefix":
            prefix_map.append((rw["from"], rw["to"]))
        else:
            raise ValueError(f"Unknown pre-merge rewrite type: {kind!r}")
        for old, new in (rw.get("operationIdRewrites") or {}).items():
            op_id_map[old] = new

    for path, item in paths.items():
        new_path = rename_map.get(path, path)
        if new_path == path:
            for prefix_from, prefix_to in prefix_map:
                if path.startswith(prefix_from):
                    new_path = prefix_to + path[len(prefix_from) :]
                    break
        for method, op in list(item.items()) if isinstance(item, dict) else []:
            if isinstance(op, dict) and "operationId" in op and op["operationId"] in op_id_map:
                op["operationId"] = op_id_map[op["operationId"]]
        new_paths[new_path] = item

    for path_to_match, summary_per_method in summary_overrides:
        item = new_paths.get(path_to_match, {})
        for method, summary in summary_per_method.items():
            if method in item:
                item[method]["summary"] = summary

    spec["paths"] = new_paths
    return spec


def filter_excluded_tags(spec: dict[str, Any], excluded_tags: list[str]) -> dict[str, Any]:
    """Drop operations whose tags intersect ``excluded_tags``.

    A path with no remaining operations is removed entirely.
    """
    if not excluded_tags:
        return spec
    spec = deepcopy(spec)
    excluded = set(excluded_tags)
    kept_paths: dict[str, Any] = {}
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            kept_paths[path] = item
            continue
        kept_methods = {}
        for method, op in item.items():
            if not isinstance(op, dict):
                kept_methods[method] = op
                continue
            tags = set(op.get("tags") or [])
            if tags & excluded:
                continue
            kept_methods[method] = op
        verbs = ("get", "post", "put", "patch", "delete", "head", "options", "trace")
        if any(m in kept_methods for m in verbs):
            kept_paths[path] = kept_methods
    spec["paths"] = kept_paths
    return spec


def strip_path_prefix(spec: dict[str, Any], prefix: str) -> dict[str, Any]:
    if not prefix:
        return spec
    spec = deepcopy(spec)
    new_paths: dict[str, Any] = {}
    for path, item in spec.get("paths", {}).items():
        if path.startswith(prefix):
            stripped = path[len(prefix) :] or "/"
            new_paths[stripped] = item
        else:
            new_paths[path] = item
    spec["paths"] = new_paths
    return spec


def merge_into(base: dict[str, Any], other: dict[str, Any], source_name: str) -> None:
    """Merge ``other`` into ``base`` in place.

    Combines paths, components (schemas, securitySchemes, etc.), and tags.
    Path collisions take the existing entry and warn — these usually indicate
    a misconfigured rewrite or overlapping route.
    """
    base.setdefault("paths", {})
    for path, item in other.get("paths", {}).items():
        if path in base["paths"]:
            logger.warning("Path collision on %s while merging %s — keeping existing entry", path, source_name)
            continue
        base["paths"][path] = item

    base_components = base.setdefault("components", {})
    for kind, entries in (other.get("components") or {}).items():
        if not isinstance(entries, dict):
            base_components.setdefault(kind, entries)
            continue
        target = base_components.setdefault(kind, {})
        for name, value in entries.items():
            if name in target and target[name] != value:
                logger.warning(
                    "components.%s.%s collision while merging %s — keeping existing entry",
                    kind,
                    name,
                    source_name,
                )
                continue
            target[name] = value

    if other.get("tags"):
        base.setdefault("tags", [])
        existing_tag_names = {t.get("name") for t in base["tags"] if isinstance(t, dict)}
        for tag in other["tags"]:
            if isinstance(tag, dict) and tag.get("name") in existing_tag_names:
                continue
            base["tags"].append(tag)
            if isinstance(tag, dict):
                existing_tag_names.add(tag.get("name"))


def prune_orphan_tags(spec: dict[str, Any]) -> None:
    """Drop tag definitions that no remaining operation references.

    Tag-based operation filtering can leave behind orphan tag entries (e.g.
    ``v2_asset_graph_search``) — strip them so the merged spec only declares
    tags that are actually in use.
    """
    used: set[str] = set()
    for item in spec.get("paths", {}).values():
        if not isinstance(item, dict):
            continue
        for op in item.values():
            if isinstance(op, dict):
                used.update(op.get("tags") or [])
    spec_tags = spec.get("tags")
    if not spec_tags:
        return
    spec["tags"] = [t for t in spec_tags if not isinstance(t, dict) or t.get("name") in used]


def compute_combined_version(versions: dict[str, str], override: str | None) -> str:
    """Pick a sensible version string for the merged spec.

    Mirrors legacy logic: explicit override wins; if all source versions match,
    use that; otherwise stitch a tag like ``SRCH1.2-AGS1.0-INFO0.9``.
    """
    if override:
        return override
    distinct = set(versions.values())
    if len(distinct) == 1:
        return next(iter(distinct))
    parts = []
    for name, ver in versions.items():
        prefix = {"search": "SRCH", "ags": "AGS", "info": "INFO"}.get(name, name.upper())
        parts.append(f"{prefix}{ver}")
    return "-".join(parts)


def parse_sources(source_args: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for arg in source_args:
        if "=" not in arg:
            raise SystemExit(f"--source must be name=value, got: {arg!r}")
        name, value = arg.split("=", 1)
        sources[name.strip()] = value.strip()
    return sources


def resolve_source_url(name: str, sources: dict[str, str]) -> str:
    if name in sources:
        return sources[name]
    env_key = f"{name}_url"
    if env_key in os.environ:
        return os.environ[env_key]
    raise SystemExit(f"No source URL/path for input {name!r}. Pass --source {name}=<url> or set ${env_key}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to merge config (default: %(default)s)")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="NAME=URL",
        help="Map a logical input name to a URL or path. Repeat per input. "
        "Falls back to env var ${NAME}_url for legacy compatibility.",
    )
    parser.add_argument("--output", help="Output file path (overrides config 'output')")
    parser.add_argument(
        "--api-version", default=os.environ.get("API_VERSION"), help="Force a version string for the merged spec"
    )
    parser.add_argument(
        "--retries", type=int, default=DEFAULT_RETRIES, help="HTTP fetch retries (default: %(default)d)"
    )
    parser.add_argument(
        "--retry-delay", type=float, default=DEFAULT_RETRY_DELAY, help="Delay between retries in seconds"
    )
    parser.add_argument("--no-validate", action="store_true", help="Skip OpenAPI validation of inputs and output")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_dir = config_path.parent

    sources = parse_sources(args.source)

    base_path = config_dir / config["base"]
    base_spec = fetch_spec(str(base_path), args.retries, args.retry_delay)

    merged: dict[str, Any] = deepcopy(base_spec)
    versions: dict[str, str] = {}

    for entry in config["inputs"]:
        name = entry["name"]
        url = resolve_source_url(name, sources)
        spec = fetch_spec(url, args.retries, args.retry_delay)
        version = spec.get("info", {}).get("version", "0.0.0")
        versions[name] = version
        logger.info("Fetched %s: version %s, %d paths", name, version, len(spec.get("paths", {})))

        if entry.get("preMergeRewrites"):
            spec = apply_pre_merge_rewrites(spec, entry["preMergeRewrites"])
        if entry.get("operationSelection", {}).get("excludeTags"):
            spec = filter_excluded_tags(spec, entry["operationSelection"]["excludeTags"])
        if entry.get("pathModification", {}).get("stripStart"):
            spec = strip_path_prefix(spec, entry["pathModification"]["stripStart"])

        if not args.no_validate:
            try:
                validate_spec(spec)
            except OpenAPIValidationError as exc:
                logger.warning("Validation failed for %s after rewrites: %s", name, exc)

        merge_into(merged, spec, source_name=name)

    prune_orphan_tags(merged)

    version = compute_combined_version(versions, args.api_version)
    logger.info("Merged API version: %s", version)
    merged.setdefault("info", {})["version"] = version

    if not args.no_validate:
        try:
            validate_spec(merged)
        except OpenAPIValidationError as exc:
            logger.warning("Validation failed for merged spec: %s", exc)

    output_path = Path(args.output or config.get("output", "./openapi.json"))
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    n_paths = len(merged.get("paths", {}))
    n_schemas = len(merged.get("components", {}).get("schemas", {}))
    logger.info("Wrote merged spec to %s (%d paths, %d schemas)", output_path, n_paths, n_schemas)


if __name__ == "__main__":
    main()
