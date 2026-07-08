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

"""Turn a ``/search/stats/usd_properties`` dump into local catalog artifacts.

Pure, network-free transform (so it is trivially testable): read the stats JSON
on stdin or ``--stats FILE`` and write, under ``--out-dir``:

* ``usd_property_catalog.yaml`` — the faithful, ranked inventory: every property
  key with its inferred value type, distinct-value cardinality, total
  ``asset_count``, and a sample of its most common values. This is the portable
  client/CLI artifact AND the grounding source consumed by the deepsearch_api
  LLM parser (``USDSEARCH_LLM_PARSING_PROPERTY_CATALOG_FILEPATH``).
* ``search_fields.generated.yaml`` — derived ``search_fields.yaml``-compatible
  field stanzas for the high-signal properties, ready to point
  ``USDSEARCH_LLM_PARSING_FIELDS_FILEPATH`` at (or merge into the shipped
  catalog).

With ``--audit TARGETS.yaml`` it also writes ``p0_gap_report.md``: a present /
absent table for a set of target metadata concepts (default file: the five P0
SimReady fields), each concept matched against the corpus's keys by
namespace-aware substring/regex — because real keys hide under deep nested names
like ``simready_metadata_validation__profile``. Optional ``--samples FILE`` folds
pre-fetched sample asset URLs (keyed by matched property) into the report; the
SKILL.md fetches those over HTTP and leaves this module network-free.

Run via uv so PyYAML is available without touching the workspace env:

    uv run --with pyyaml python build_catalog.py --stats stats.json --out-dir ./out
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zlib
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Field names shipped in the default + SimReady catalogs. A generated field that
# slugged to one of these would shadow a curated one, so we suffix to avoid the
# collision. Override/extend with --reserved.
DEFAULT_RESERVED = {
    "file_type",
    "name",
    "path_prefix",
    "created_at",
    "modified_at",
    "size",
    "created_by",
    "tag",
    "usd_property",
    "polygon_count",
    "dimension",
    "physics_rigid_body",
    "has_collider",
    "object_class",
    "physics_mass",
    "physics_density",
}

_BOOL_TOKENS = {"true", "false", "0", "1", "yes", "no", "on", "off", "t", "f"}

# Heuristic knobs (overridable via CLI).
DEFAULTS = dict(max_values=12, top_n_fields=40, max_categorical_card=25, min_numeric_frac=0.95)


# --- stats access ----------------------------------------------------------


def load_stats(path: Optional[str]) -> Dict[str, Any]:
    raw = sys.stdin.read() if not path or path == "-" else open(path, "r").read()
    d = json.loads(raw)
    for k in ("unique_keys", "unique_values", "kv_pairs"):
        d.setdefault(k, [])
    return d


def values_by_key(stats: Dict[str, Any]) -> Dict[str, List[Tuple[str, int]]]:
    """{property key: [(value, asset_count), ...] sorted by count desc}."""
    out: Dict[str, List[Tuple[str, int]]] = {}
    for p in stats["kv_pairs"]:
        out.setdefault(p["key"], []).append((p.get("value", ""), int(p.get("asset_count", 0))))
    for k in out:
        out[k].sort(key=lambda vc: -vc[1])
    return out


# --- inference -------------------------------------------------------------


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def infer_type(values: List[Tuple[str, int]], min_numeric_frac: float) -> str:
    """Classify a property as number / boolean / string from its values."""
    vals = [v for v, _ in values if v != "" and v is not None]
    if not vals:
        return "string"
    distinct = {str(v).strip().lower() for v in vals}
    if distinct <= _BOOL_TOKENS:
        return "boolean"
    if sum(_is_float(v) for v in vals) / len(vals) >= min_numeric_frac:
        return "number"
    return "string"


def slug(key: str) -> str:
    """USD property key -> safe IR field name (camelCase split, ns-flattened)."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)  # camelCase -> camel_Case
    s = re.sub(r"[^0-9a-zA-Z]+", "_", s).lower()
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "property"


# --- catalog ---------------------------------------------------------------


def build_catalog_doc(stats: Dict[str, Any], source: str, max_values: int, min_numeric_frac: float) -> Dict[str, Any]:
    vbk = values_by_key(stats)
    props = []
    for r in sorted(stats["unique_keys"], key=lambda x: -int(x.get("asset_count", 0))):
        key = r["key"]
        vals = vbk.get(key, [])
        props.append(
            {
                "key": key,
                "asset_count": int(r.get("asset_count", 0)),
                "type": infer_type(vals, min_numeric_frac),
                "cardinality": len(vals),
                "top_values": [{"value": v, "asset_count": c} for v, c in vals[:max_values]],
            }
        )
    return {
        "generated_by": "usd-property-catalog",
        "source": source,
        "totals": {
            "unique_keys": len(stats["unique_keys"]),
            "unique_values": len(stats["unique_values"]),
            "kv_pairs": len(stats["kv_pairs"]),
        },
        "properties": props,
    }


# --- generated search_fields stanzas --------------------------------------


def _stanza(name: str, key: str, vtype: str, asset_count: int, top_values: List[Tuple[str, int]]) -> Dict[str, Any]:
    if vtype == "number":
        kind, ops = "property_numeric", ["gt", "gte", "lt", "lte", "eq"]
        ex = [f'"{name} over 10" -> {name} gt 10']
    elif vtype == "boolean":
        kind, ops = "property_exists", ["eq", "exists"]
        ex = [f'"with {name}" -> {name} eq true']
    else:
        kind, ops = "property_match", ["eq", "contains"]
        sample = top_values[0][0] if top_values else "value"
        ex = [f'"{name} is {sample}" -> {name} eq "{sample}"']
    enum_hint = ""
    if vtype == "string" and top_values:
        enum_hint = " Common values: " + ", ".join(repr(v) for v, _ in top_values[:8]) + "."
    return {
        "name": name,
        "type": vtype,
        "operators": ops,
        "description": f"Auto-generated from USD property '{key}' ({asset_count} assets).{enum_hint}",
        "examples": ex,
        "map": {"kind": kind, "property": key},
    }


def build_generated_fields(
    stats: Dict[str, Any], top_n: int, max_categorical_card: int, min_numeric_frac: float, reserved: set
) -> List[Dict[str, Any]]:
    vbk = values_by_key(stats)
    used = set(reserved)
    fields: List[Dict[str, Any]] = []
    for r in sorted(stats["unique_keys"], key=lambda x: -int(x.get("asset_count", 0))):
        if len(fields) >= top_n:
            break
        key = r["key"]
        vals = vbk.get(key, [])
        vtype = infer_type(vals, min_numeric_frac)
        # High-cardinality free-text strings make poor dedicated filters — leave
        # them to the generic usd_property field + prompt grounding.
        if vtype == "string" and len(vals) > max_categorical_card:
            continue
        name = slug(key)
        if name in used:  # disambiguate against built-ins / earlier generated fields
            # zlib.crc32 (not builtin hash()) so the suffix is stable across runs.
            name = f"{name}_{zlib.crc32(key.encode()) % 1000:03d}"
        used.add(name)
        fields.append(_stanza(name, key, vtype, int(r.get("asset_count", 0)), vals))
    return fields


# --- P0 / target audit -----------------------------------------------------


def load_targets(path: str) -> List[Dict[str, Any]]:
    return yaml.safe_load(open(path, "r"))["targets"]


def run_audit(
    stats: Dict[str, Any], targets: List[Dict[str, Any]], samples: Dict[str, List[str]]
) -> Tuple[str, List[Dict[str, Any]]]:
    """Return (markdown_report, per-target result records)."""
    keys = sorted(stats["unique_keys"], key=lambda x: -int(x.get("asset_count", 0)))
    results = []
    for t in targets:
        rx = re.compile("|".join(t["patterns"]), re.I)
        matched = [(r["key"], int(r.get("asset_count", 0))) for r in keys if rx.search(r["key"])]
        results.append(
            {
                "concept": t["concept"],
                "field_name": t.get("field_name", ""),
                "patterns": t["patterns"],
                "recommended_key": t.get("recommended_key", ""),
                "note": t.get("note", ""),
                "present": bool(matched),
                "matched": matched,
            }
        )

    lines = ["# USD property P0 gap report", ""]
    lines.append(
        f"Corpus: {len(stats['unique_keys'])} unique property keys, " f"{len(stats['kv_pairs'])} key=value pairs."
    )
    lines.append("")
    lines.append("| Concept | Present? | Top matched key(s) (asset_count) | Recommended key |")
    lines.append("|---|---|---|---|")
    for r in results:
        mark = "✅ yes" if r["present"] else "❌ no"
        mk = "; ".join(f"`{k}` ({c})" for k, c in r["matched"][:3]) or "—"
        lines.append(f"| {r['concept']} | {mark} | {mk} | `{r['recommended_key'] or '—'}` |")
    lines.append("")

    present = [r for r in results if r["present"]]
    absent = [r for r in results if not r["present"]]

    if present:
        lines += ["## Present — validate parsing against these", ""]
        for r in present:
            top_key = r["matched"][0][0]
            lines.append(f"### {r['concept']} — `{top_key}`")
            if r["note"]:
                lines.append(f"_{r['note']}_")
            urls = samples.get(top_key, [])
            if urls:
                lines.append("Sample assets:")
                lines += [f"- `{u}`" for u in urls[:5]]
            else:
                lines.append(f'Fetch samples: `filter_by_properties: "{top_key}="` on /search_hybrid.')
            lines.append("")

    lines += ["## Raise with the data/SimReady team — not in the index", ""]
    if absent:
        for r in absent:
            lines.append(
                f"- **{r['concept']}** — no matching property key. "
                f"Suggested key: `{r['recommended_key'] or 'TBD (no standard)'}`. {r['note']}".rstrip()
            )
    else:
        lines.append("- (none — all target concepts are present)")
    lines.append("")
    return "\n".join(lines), results


def build_target_fields(stats: Dict[str, Any], results: List[Dict[str, Any]], reserved: set, min_numeric_frac: float):
    """First-class ``search_fields`` stanzas for the PRESENT audit targets, named
    by concept (e.g. ``collision_type``). Unlike ``build_generated_fields`` these
    are NOT capped by coverage and never skipped for cardinality — a
    low-coverage-but-wanted property (e.g. ``physics:approximation``, ~73 assets,
    which falls below the top-N coverage cut) still gets a dedicated filter."""
    vbk = values_by_key(stats)
    used = set(reserved)
    out: List[Dict[str, Any]] = []
    for r in results:
        if not r.get("present"):
            continue
        matched = dict(r["matched"])
        # Prefer the canonical recommended_key when it's actually one of the
        # matched keys (e.g. physics:approximation over a bare 'approximation');
        # otherwise take the highest-coverage match.
        rec = r.get("recommended_key")
        key = rec if rec in matched else r["matched"][0][0]
        count = matched[key]
        vals = vbk.get(key, [])
        name = r.get("field_name") or slug(r["concept"])
        if name in used:
            name = f"{name}_{zlib.crc32(key.encode()) % 1000:03d}"
        used.add(name)
        out.append(_stanza(name, key, infer_type(vals, min_numeric_frac), count, vals))
    return out


# --- output helpers --------------------------------------------------------

_SPDX_YAML = (
    "# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.\n"
    "# SPDX-License-Identifier: Apache-2.0\n"
)


def _dump_yaml(doc: Any, header: str) -> str:
    return _SPDX_YAML + header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build USD property catalog artifacts from stats JSON.")
    ap.add_argument("--stats", default="-", help="stats JSON file ('-' = stdin)")
    ap.add_argument("--out-dir", default=".", help="output directory")
    ap.add_argument("--source", default="", help="provenance string (e.g. API URL) recorded in the catalog")
    ap.add_argument("--audit", help="targets YAML for the present/absent gap report")
    ap.add_argument("--samples", help="JSON {property_key: [urls]} of pre-fetched sample assets")
    ap.add_argument("--top-n-fields", type=int, default=DEFAULTS["top_n_fields"])
    ap.add_argument("--max-values", type=int, default=DEFAULTS["max_values"])
    ap.add_argument("--max-categorical-card", type=int, default=DEFAULTS["max_categorical_card"])
    ap.add_argument("--min-numeric-frac", type=float, default=DEFAULTS["min_numeric_frac"])
    ap.add_argument("--reserved", default="", help="extra reserved field names, comma-separated")
    args = ap.parse_args(argv)

    stats = load_stats(args.stats)
    os.makedirs(args.out_dir, exist_ok=True)
    reserved = set(DEFAULT_RESERVED) | {x.strip() for x in args.reserved.split(",") if x.strip()}

    catalog = build_catalog_doc(stats, args.source or args.stats, args.max_values, args.min_numeric_frac)
    with open(os.path.join(args.out_dir, "usd_property_catalog.yaml"), "w") as f:
        f.write(_dump_yaml(catalog, "# Faithful, ranked inventory of USD properties in the indexed corpus.\n"))

    fields = build_generated_fields(
        stats, args.top_n_fields, args.max_categorical_card, args.min_numeric_frac, reserved
    )
    with open(os.path.join(args.out_dir, "search_fields.generated.yaml"), "w") as f:
        f.write(
            _dump_yaml(
                {"fields": fields},
                "# Derived search_fields.yaml stanzas. Review before pointing\n"
                "# USDSEARCH_LLM_PARSING_FIELDS_FILEPATH at this file.\n",
            )
        )

    summary = {
        "unique_keys": catalog["totals"]["unique_keys"],
        "generated_fields": len(fields),
    }
    if args.audit:
        samples = json.load(open(args.samples)) if args.samples else {}
        report, results = run_audit(stats, load_targets(args.audit), samples)
        with open(os.path.join(args.out_dir, "p0_gap_report.md"), "w") as f:
            f.write(report)
        # Machine-readable matches so the SKILL.md can fetch sample asset URLs for
        # the present concepts (then re-run with --samples to fold them in) without
        # scraping the markdown.
        matched = {
            "present": [
                {"concept": r["concept"], "top_key": r["matched"][0][0], "token": f"{r['matched'][0][0]}="}
                for r in results
                if r["present"]
            ],
            "absent": [r["concept"] for r in results if not r["present"]],
        }
        with open(os.path.join(args.out_dir, "audit_matched.json"), "w") as f:
            json.dump(matched, f, indent=2)
        # Ready-to-merge filter stanzas for the present targets (coverage-independent,
        # so e.g. collision type makes it in even though it's a thin slice).
        target_fields = build_target_fields(stats, results, reserved, args.min_numeric_frac)
        with open(os.path.join(args.out_dir, "search_fields.p0.yaml"), "w") as f:
            f.write(
                _dump_yaml(
                    {"fields": target_fields},
                    "# First-class filter stanzas for the PRESENT audit targets (named by\n"
                    "# concept). Merge the ones you want into your search_fields.yaml.\n",
                )
            )
        summary["audit_present"] = sorted(r["concept"] for r in results if r["present"])
        summary["audit_absent"] = sorted(r["concept"] for r in results if not r["present"])
        summary["target_fields"] = [f["name"] for f in target_fields]

    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
