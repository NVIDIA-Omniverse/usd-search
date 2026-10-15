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

"""Repair percent-encoded ``Asset.url`` keys in the Neo4j asset graph.

The graph builder used to anchor authored asset paths verbatim, leaving nodes
keyed under a URL no storage client fetches and no index entry matches: downloads
drop the layer, "where is this asset used" comes back empty. ``graph_url`` fixed
the builder; this fixes the nodes already written.

For every ``:Asset`` whose ``url`` changes under percent-decoding: rename in
place, or — when a node already holds the decoded URL — merge the encoded node's
relationships into it and drop the duplicate.

Renaming repairs the key, not the rest of the representation: prims and edges
written under the old spelling are still there. ``--reindex`` submits every
migrated asset to the info endpoint so the asset-graph plugin rebuilds it.

Run it from the asset-graph-service pod — ``db_uri`` / ``db_username`` /
``db_password`` are in its environment and nowhere else::

    python -m usdsearch.admin.tools migrate_url_spellings
    python -m usdsearch.admin.tools migrate_url_spellings --apply --reindex
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

from neo4j import AsyncGraphDatabase
from neo4j.exceptions import ConstraintError

from search_utils.asset_uri import decode_uri_path

from .reindex import process_asset

logger = logging.getLogger(__name__)

#: The graph credentials. Present only where the asset-graph service runs, which
#: is what makes them a usable "are we on the right pod" test. Matched lowercase:
#: the chart sets them lowercase and docker-compose uppercase.
REQUIRED_DB_ENV = ("db_uri", "db_username", "db_password")

#: Read the same way, but optional — Neo4j's own default database.
DB_NAME_ENV = "db_name"
DEFAULT_DB_NAME = "neo4j"

#: Where the info endpoint lives. The chart publishes it to the pod; the CLI
#: argument overrides it, and the fallback matches the sibling ``reindex`` command.
INFO_ENDPOINT_ENV = "info_endpoint_url"
DEFAULT_ENDPOINT_URL = "http://localhost:8000"

#: The only plugin worth re-running: it is what writes the asset graph. Re-running
#: the rest would re-embed and re-thumbnail an asset whose *content* never changed.
REINDEX_PLUGIN = "asset_graph_generation"
REINDEX_CONCURRENCY = 8

#: How many submissions to schedule at a time. See :func:`reindex_migrated`.
REINDEX_BATCH = 500

#: Scan batch size; also the progress-logging interval.
PAGE_SIZE = 1000

#: How many candidates to list before summarising.
SAMPLE_SIZE = 10


def configure_logging() -> None:
    """Make this tool's own progress visible, without turning on everyone else's.

    Every line here is INFO and the root logger defaults to WARNING, so an
    unconfigured process — a bare checkout, or the CLI, which unlike the service
    never applies ``/logging.yml`` — swallows the lot and the run looks silent.

    Deliberately not ``basicConfig(level=INFO)``: that raises the *root* level, and
    the Neo4j driver then reports every notification it receives, which is what
    buried the real error in the first staging run. Only this logger is raised, and
    a handler is added just when nothing downstream would print it anyway.
    """
    logger.setLevel(logging.INFO)
    if not logging.getLogger().handlers and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        logger.addHandler(handler)


def db_env() -> Dict[str, str]:
    """The graph connection settings found in the environment, keyed lowercase."""
    wanted = set(REQUIRED_DB_ENV) | {DB_NAME_ENV}
    return {name.lower(): value for name, value in os.environ.items() if name.lower() in wanted and value}


def missing_db_env() -> List[str]:
    """Which graph credentials are absent from the environment."""
    present = db_env()
    return [name for name in REQUIRED_DB_ENV if name not in present]


def info_endpoint_url() -> Optional[str]:
    """The info endpoint published to this pod, or None. Matched case-insensitively."""
    for name, value in os.environ.items():
        if name.lower() == INFO_ENDPOINT_ENV and value:
            return value.rstrip("/")
    return None


async def find_candidates(session, limit: int = 0) -> List[Tuple[str, str, bool]]:
    """``(encoded_url, decoded_url, target_exists)`` for every node needing repair.

    ``limit`` caps *repairs*, not nodes scanned: ``--limit 10`` yields ten nodes to
    inspect rather than however many of the first ten encoded URLs happened to need
    one. A URL can contain ``%`` and still decode to itself. Rows stop being pulled
    once the cap is met, so a capped run does not drag the whole label scan — and
    neither does the existence probe below, which only sees what was kept.
    """
    result = await session.run(
        "MATCH (n:Asset) WHERE n.url CONTAINS '%' RETURN n.url AS url",
    )
    candidates = []
    scanned = 0
    async for record in result:
        scanned += 1
        url = record["url"]
        decoded = decode_uri_path(url)
        if decoded != url:
            candidates.append((url, decoded))
            if limit and len(candidates) >= limit:
                break
    logger.info("Scanned %d node(s) with '%%' in the URL; %d need repair", scanned, len(candidates))
    if not candidates:
        return []

    # One round trip per page, rather than one per node.
    existing = set()
    for start in range(0, len(candidates), PAGE_SIZE):
        page = [decoded for _, decoded in candidates[start : start + PAGE_SIZE]]
        result = await session.run(
            "UNWIND $urls AS url MATCH (n:Asset {url: url}) RETURN n.url AS url",
            urls=page,
        )
        existing.update([record["url"] async for record in result])

    return [(enc, dec, dec in existing) for enc, dec in candidates]


async def apply_rename(session, encoded: str, decoded: str) -> bool:
    """Rename a node onto its decoded URL. False if that URL turned out to be taken.

    The scan's view of which targets are free goes stale the moment it is taken:
    another candidate in this run may claim the URL, or — on a live cluster — the
    graph builder may write the decoded node while the migration runs. ``Asset.url``
    is unique, so the rename then fails. That is a merge, not an error, so report it
    and let the caller fold the duplicate in instead of aborting the whole run.
    """
    try:
        result = await session.run(
            "MATCH (n:Asset {url: $encoded}) SET n.url = $decoded",
            encoded=encoded,
            decoded=decoded,
        )
        # Consumed here so a violation is raised against *this* node. Left
        # unconsumed it surfaces on a later call, blaming an unrelated URL.
        await result.consume()
    except ConstraintError:
        logger.debug("Rename lost a race for %s; merging instead", decoded)
        return False
    return True


async def apply_merge(session, encoded: str, decoded: str) -> None:
    """Fold an encoded duplicate into the node that already holds the decoded URL.

    ``apoc.refactor.mergeNodes`` rather than hand-written Cypher: asset edges carry
    a dynamic type and a ``scene_url`` property that re-pointing by hand would
    flatten. ``properties: "discard"`` keeps the surviving (crawler-written) node's
    metadata; ``mergeRels`` collapses edges both nodes had.

    Both nodes are found by one indexed ``IN`` lookup, then ordered so the decoded
    URL is first — ``mergeNodes`` merges into the head of the list, and a bare
    ``collect`` has no defined order. Matching them separately would read as a
    cartesian product and bury the run in performance notifications.
    """
    result = await session.run(
        """
        MATCH (n:Asset) WHERE n.url IN [$decoded, $encoded]
        WITH n ORDER BY CASE n.url WHEN $decoded THEN 0 ELSE 1 END
        WITH collect(n) AS nodes
        WHERE size(nodes) = 2
        CALL apoc.refactor.mergeNodes(nodes, {properties: "discard", mergeRels: true})
        YIELD node RETURN node
        """,
        encoded=encoded,
        decoded=decoded,
    )
    await result.consume()


def reindex_urls(candidates: List[Tuple[str, str, bool]]) -> List[str]:
    """The decoded URLs to rebuild: the keys the nodes now carry, deduplicated.

    Several encoded spellings can converge on one node, and that asset needs one
    rebuild rather than one per spelling.
    """
    return list(dict.fromkeys(decoded for _, decoded, _ in candidates))


async def reindex_migrated(urls: List[str], endpoint_url: str) -> None:
    """Ask the info endpoint to rebuild the asset graph for each migrated asset.

    Goes through ``reindex.process_asset`` — the same ``/process/asset`` client the
    ``reindex`` command uses, with its retry policy — rather than a second one.
    """
    if not urls:
        # Said out loud: --reindex was asked for, and silence here reads as the
        # step having been skipped rather than having had nothing to do.
        logger.info("Nothing to re-index: no nodes were migrated.")
        return

    semaphore = asyncio.Semaphore(REINDEX_CONCURRENCY)
    failed = []
    # Batched because the semaphore bounds requests *in flight*, not the coroutines
    # `gather` builds up front: a corpus-wide migration would otherwise allocate a
    # task and a result slot per asset before the first one is throttled.
    for start in range(0, len(urls), REINDEX_BATCH):
        batch = urls[start : start + REINDEX_BATCH]
        results = await asyncio.gather(
            *(
                process_asset(
                    asset_url=url,
                    api_semaphore=semaphore,
                    endpoint_url=endpoint_url,
                    include_plugins=[REINDEX_PLUGIN],
                    refresh_metadata=False,
                    refresh_tags=False,
                    refresh_plugins=True,
                )
                for url in batch
            ),
            return_exceptions=True,
        )
        failed.extend(url for url, outcome in zip(batch, results) if outcome is not True)
    logger.info("Submitted %d/%d migrated asset(s) for re-indexing.", len(urls) - len(failed), len(urls))
    if failed:
        # Re-running the migration will not retry these: those nodes no longer look
        # encoded. Name them so they can be resubmitted with the `reindex` command.
        logger.warning("Re-index failed for %d asset(s): %s", len(failed), ", ".join(failed[:SAMPLE_SIZE]))


async def migrate(
    apply: bool = False,
    reindex: bool = False,
    endpoint_url: Optional[str] = None,
    limit: int = 0,
    verbose: bool = False,
) -> int:
    """Run the migration. See :func:`usdsearch.admin.tools.AdminTools.migrate_url_spellings`."""
    configure_logging()

    missing = missing_db_env()
    if missing:
        logger.warning(
            "Not the asset-graph-service pod: %s unset. The asset graph is only reachable "
            "from there — re-run this from that pod:\n"
            "    kubectl exec -it deploy/<release>-asset-graph-service -- \\\n"
            "        python -m usdsearch.admin.tools migrate_url_spellings%s",
            ", ".join(missing),
            " --apply" if apply else "",
        )
        return 2

    endpoint_url = (endpoint_url or info_endpoint_url() or DEFAULT_ENDPOINT_URL).rstrip("/")
    env = db_env()
    driver = AsyncGraphDatabase.driver(env["db_uri"], auth=(env["db_username"], env["db_password"]))
    try:
        async with driver.session(database=env.get(DB_NAME_ENV, DEFAULT_DB_NAME)) as session:
            candidates = await find_candidates(session, limit=limit)

            renames = [c for c in candidates if not c[2]]
            merges = [c for c in candidates if c[2]]
            logger.info(
                "%d node(s) to repair: %d rename(s), %d merge(s) into an existing node",
                len(candidates),
                len(renames),
                len(merges),
            )
            for encoded, decoded, target_exists in candidates if verbose else candidates[:SAMPLE_SIZE]:
                logger.info("  %s\n    -> %s%s", encoded, decoded, "  [merge]" if target_exists else "")
            if not verbose and len(candidates) > SAMPLE_SIZE:
                logger.info("  ... %d more (use --verbose to list)", len(candidates) - SAMPLE_SIZE)

            if not apply:
                if reindex:
                    # The deduplicated count, so the dry run promises what an
                    # --apply run would actually submit.
                    logger.info(
                        "Would submit %d asset(s) to %s for re-indexing", len(reindex_urls(candidates)), endpoint_url
                    )
                logger.info("Dry run — nothing written. Re-run with --apply to migrate.")
                return 0

            # `target_exists` describes the graph as the scan found it, and two
            # encoded spellings can decode to the same free URL, so track targets
            # as they are claimed. The rename still reports a lost race — the scan
            # cannot see a node the graph builder writes mid-run — and that answer,
            # not this set, is what decides the outcome.
            occupied = {decoded for _, decoded, target_exists in candidates if target_exists}
            merged = 0
            for index, (encoded, decoded, target_exists) in enumerate(candidates, start=1):
                renamed = False
                if not (target_exists or decoded in occupied):
                    renamed = await apply_rename(session, encoded, decoded)
                    occupied.add(decoded)
                if not renamed:
                    await apply_merge(session, encoded, decoded)
                    merged += 1
                if index % PAGE_SIZE == 0:
                    logger.info("  migrated %d/%d", index, len(candidates))
            logger.info(
                "Migrated %d node(s): %d renamed, %d merged.", len(candidates), len(candidates) - merged, merged
            )
    finally:
        await driver.close()

    # Unconditional when asked for: an empty run still reports, rather than leaving
    # the operator to guess whether the step ran.
    if reindex:
        await reindex_migrated(reindex_urls(candidates), endpoint_url)
    return 0
