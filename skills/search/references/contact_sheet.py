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

"""Make the fetched thumbnails visible — `/search`.

The agent must never read a result JPEG into its own context (a thumbnail read
early is re-read on every later turn, and is the largest avoidable cost of a
search), but the *user* has to see the pictures to judge the hits. This closes
that gap without either cost: it reads the ``manifest.json`` written by the
skill, checks which thumbnails actually landed on disk, and emits two
renderings of the same set:

* ``contact-sheet.html`` in ``--dir`` — a grid of every kept thumbnail with its
  asset URL and scores, for a browser.
* on stdout, one Markdown image line per kept hit, paths relative to the
  current directory, ready to paste into the answer for harnesses that render
  Markdown images inline.

Network-free, and no image bytes ever cross stdout.

Manifest shape (only ``rank`` and ``thumbnail`` are required)::

    {"query": "blue forklift",
     "hits": [{"rank": 1, "name": "forklift_a", "url": "s3://…/a.usd",
               "rrf_score": 0.0163, "thumbnail": "01_forklift_a.jpg",
               "note": "Round 2"}]}

Usage::

    python3 contact_sheet.py --dir DIR [--keep 1,2,5] [--title "blue forklift"]
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys

#: Grid card width, in px. Thumbnails come back ~512 px square; 240 shows a
#: readable 4-up on a laptop without scaling artifacts.
CARD_PX = 240

#: Manifest fields rendered under the asset link, in order: (key, label).
DISPLAY_FIELDS = [
    ("rrf_score", "rrf"),
    ("similarity_score", "similarity"),
    ("confidence", "confidence"),
    ("note", "found via"),
]

_STYLE = f"""
  body {{ font: 14px/1.45 system-ui, sans-serif; margin: 24px; background: #111; color: #eee; }}
  h1 {{ font-size: 18px; margin: 0 0 20px; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 16px; }}
  .card {{ width: {CARD_PX}px; background: #1c1c1c; border-radius: 8px; padding: 10px; }}
  .card img {{ width: 100%; border-radius: 4px; background: #000; display: block; }}
  .rank {{ color: #76b900; font-weight: 600; }}
  .name {{ word-break: break-all; margin: 6px 0 4px; }}
  .prop {{ color: #aaa; font-size: 12px; word-break: break-all; }}
  a {{ color: #8ab4f8; }}
"""


def parse_keep(raw: str | None) -> set[int] | None:
    """Turn ``"1,3,4"`` into ``{1, 3, 4}``; ``None``/empty means keep all."""
    if not raw:
        return None
    return {int(part) for part in raw.replace(" ", "").split(",") if part}


def selected(entries: list[dict], directory: str, keep: set[int] | None) -> tuple[list[dict], list[dict]]:
    """Split entries into (has a thumbnail on disk, kept but missing one).

    A hit is skipped entirely when ``--keep`` excludes it — validation already
    dropped it, and it must not reappear in a picture. A *kept* hit whose JPEG
    never landed (``thumbnail_exists: false``, or a 404 from ``/images``) is
    reported rather than silently omitted, so the agent can say "no thumbnail"
    instead of quietly showing a shorter list than it validated.
    """
    shown, missing = [], []
    for entry in entries:
        if keep is not None and entry.get("rank") not in keep:
            continue
        thumb = entry.get("thumbnail")
        if thumb and os.path.isfile(os.path.join(directory, thumb)):
            shown.append(entry)
        else:
            missing.append(entry)
    return shown, missing


def _label(entry: dict) -> str:
    return entry.get("name") or entry.get("url") or entry.get("base_key") or f"hit-{entry.get('rank')}"


def _asset_url(entry: dict) -> str | None:
    return entry.get("url") or entry.get("base_key")


def render_html(entries: list[dict], title: str) -> str:
    """Render the grid: thumbnail, asset URL, scores."""
    cards = []
    for entry in entries:
        bits = [
            f'<div class="rank">#{entry.get("rank")}</div>',
            f'<img src="{html.escape(entry["thumbnail"], quote=True)}" alt="rank {entry.get("rank")}">',
            f'<div class="name">{html.escape(_label(entry))}</div>',
        ]
        url = _asset_url(entry)
        if url:
            bits.append(f'<div class="prop">{html.escape(url)}</div>')
        for key, label in DISPLAY_FIELDS:
            value = entry.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bits.append(f'<div class="prop">{label}: {value:.5f}</div>')
            elif value:
                bits.append(f'<div class="prop">{label}: {html.escape(str(value))}</div>')
        cards.append('<div class="card">' + "".join(bits) + "</div>")

    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)} — USD Search</title><style>{_STYLE}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<div class='grid'>{''.join(cards)}</div>"
        "</body></html>\n"
    )


def render_markdown(entries: list[dict], directory: str) -> list[str]:
    """One Markdown image line per hit.

    Paths are relative to the cwd — the normal case, since results land under
    ``./search-results/<slug>/`` — but a result dir outside it falls back to
    the absolute path rather than a ``../../..`` chain no renderer resolves.
    """
    lines = []
    for entry in entries:
        absolute = os.path.abspath(os.path.join(directory, entry["thumbnail"]))
        relative = os.path.relpath(absolute)
        path = absolute if relative.startswith("..") else relative
        lines.append(f'![#{entry.get("rank")} {_label(entry)}]({path})')
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="result dir holding manifest.json + the fetched thumbnails")
    ap.add_argument("--keep", default=None, help="comma-separated ranks that survived validation (default: all)")
    ap.add_argument("--title", default=None, help="heading for the sheet (default: the manifest's query)")
    ap.add_argument("--out", default="contact-sheet.html", help="file name written inside --dir")
    args = ap.parse_args(argv)

    with open(os.path.join(args.dir, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    hits = manifest.get("hits") if isinstance(manifest, dict) else manifest
    shown, missing = selected(hits or [], args.dir, parse_keep(args.keep))
    title = (manifest.get("query") if isinstance(manifest, dict) else None) or "USD Search results"
    title = args.title or title

    sheet = os.path.join(args.dir, args.out)
    with open(sheet, "w", encoding="utf-8") as fh:
        fh.write(render_html(shown, title))

    print(f"contact sheet: {os.path.abspath(sheet)}  ({len(shown)} thumbnail(s))")
    for line in render_markdown(shown, args.dir):
        print(line)
    for entry in missing:
        print(f"no thumbnail on disk: rank {entry.get('rank')} {_label(entry)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
