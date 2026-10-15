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

"""Publish a locally-written Storage API token into a Kubernetes Secret.

This is the "syncer" half of the Helm token refresher
(``helm/usdsearch/templates/storage-api-token-refresher/``): a token-vending
sidecar writes the bearer token to a shared file, and this program publishes it
into the credentials Secret that every USD Search service reads. Alongside the
token it writes a ``<secret_key>_refreshed_at`` key holding the UTC timestamp of
the last change, so an operator (or a test) can confirm the mounted Secret was
updated in-pod.

Two modes, selected by the ``MODE`` env var:

* ``loop`` (default) — long-running: re-read the token file and patch the Secret
  whenever the value changes (idempotent; no write when unchanged).
* ``once`` — seed: wait for the token file to appear, patch once, exit. Used by
  the pre-install/pre-upgrade hook so the Secret holds a valid token before any
  service pod starts.

The Kubernetes access uses ``kubernetes_asyncio`` (in-cluster config + the
ServiceAccount mounted under ``/var/run/secrets/...``), matching
``deepsearch_utils.k8s_renderer``. The pure helpers (:func:`build_secret_data`,
:func:`read_token`, :func:`config_from_env`) and the async flow
(:func:`wait_for_token`, :func:`run_once`, :func:`run_loop`) are unit-testable
against a fake patcher, without a cluster.
"""

import asyncio
import base64
import os
import sys
import time
from datetime import datetime, timezone

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client.api_client import ApiClient

REFRESHED_AT_SUFFIX = "_refreshed_at"
_NAMESPACE_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"


def log(message):
    print("[token-refresher] " + message, flush=True)


def iso_now():
    """Current UTC time as a compact ISO-8601 string, e.g. ``2026-07-23T15:04:05Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_token(path):
    """Read and strip the token file. Raises ``OSError`` if missing/unreadable."""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read().strip()


def build_secret_data(secret_key, token, refreshed_at_key=None, timestamp=None):
    """Base64-encode the token (and, when given, the timestamp) as Secret ``data``.

    Pure function — unit-testable without a cluster.
    """
    data = {secret_key: base64.b64encode(token.encode("utf-8")).decode("ascii")}
    if refreshed_at_key and timestamp is not None:
        data[refreshed_at_key] = base64.b64encode(timestamp.encode("utf-8")).decode("ascii")
    return data


def current_namespace(path=_NAMESPACE_PATH):
    """The pod's namespace from the ServiceAccount mount (``"default"`` off-cluster)."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return "default"


def config_from_env(env):
    """Resolve runtime configuration from the process environment."""
    secret_key = env["SECRET_KEY"]
    return {
        "mode": env.get("MODE", "loop"),
        "token_file": env["TOKEN_FILE"],
        "secret_name": env["SECRET_NAME"],
        "secret_key": secret_key,
        "refreshed_at_key": env.get("REFRESHED_AT_KEY", secret_key + REFRESHED_AT_SUFFIX),
        "sync_interval": float(env.get("SYNC_INTERVAL", "30")),
        "seed_timeout": float(env.get("SEED_TIMEOUT", "120")),
    }


class SecretPatcher:
    """Publishes token values into a namespaced Secret via ``kubernetes_asyncio``."""

    def __init__(self, core_v1, secret_name, namespace):
        self._api = core_v1
        self.secret_name = secret_name
        self.namespace = namespace

    async def patch(self, data):
        # A partial body ``{"data": {...}}`` merges the given keys, leaving the
        # rest of the Secret untouched.
        await self._api.patch_namespaced_secret(name=self.secret_name, namespace=self.namespace, body={"data": data})


async def wait_for_token(path, timeout, interval=2.0, sleep=None, clock=time.monotonic):
    """Poll ``path`` until it holds a non-empty token or ``timeout`` seconds pass.

    Returns the token, or ``""`` on timeout. ``sleep``/``clock`` are injectable so
    the loop can be exercised deterministically in tests.
    """
    sleep = asyncio.sleep if sleep is None else sleep
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            token = read_token(path)
            if token:
                return token
        except OSError:
            pass
        await sleep(interval)
    return ""


async def run_once(cfg, patcher, now=iso_now):
    """Seed mode: wait for the token, publish it once. Returns a process exit code."""
    token = await wait_for_token(cfg["token_file"], cfg["seed_timeout"])
    if not token:
        log("timed out after %ss waiting for token file %s" % (cfg["seed_timeout"], cfg["token_file"]))
        return 1
    await patcher.patch(build_secret_data(cfg["secret_key"], token, cfg["refreshed_at_key"], now()))
    log("seeded %s/%s" % (cfg["secret_name"], cfg["secret_key"]))
    return 0


async def run_loop(cfg, patcher, sleep=asyncio.sleep, now=iso_now, iterations=None):
    """Sync mode: publish the token whenever it changes.

    Runs forever in production; ``iterations`` bounds the loop for tests.
    """
    previous = None
    count = 0
    while iterations is None or count < iterations:
        try:
            token = read_token(cfg["token_file"])
            if token and token != previous:
                await patcher.patch(build_secret_data(cfg["secret_key"], token, cfg["refreshed_at_key"], now()))
                previous = token
                log("published rotated token to %s/%s" % (cfg["secret_name"], cfg["secret_key"]))
        except Exception as exc:  # never let the sync loop die on a transient error
            log("error: %s" % exc)
        count += 1
        if iterations is not None and count >= iterations:
            break
        await sleep(cfg["sync_interval"])
    return previous


async def _run(env=None):
    cfg = config_from_env(os.environ if env is None else env)
    config.load_incluster_config()
    namespace = current_namespace()
    async with ApiClient() as api:
        patcher = SecretPatcher(client.CoreV1Api(api), cfg["secret_name"], namespace)
        if cfg["mode"] == "once":
            return await run_once(cfg, patcher)
        await run_loop(cfg, patcher)
        return 0


def main(env=None):
    return asyncio.run(_run(env))


if __name__ == "__main__":
    sys.exit(main())
