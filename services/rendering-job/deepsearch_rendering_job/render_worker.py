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

"""Run the ovrtx renderer in an isolated child process.

The Kit backend rendered in a separate process guarded by memory and timeout
watchers; the in-process ovrtx migration dropped that safety and now runs the
renderer directly on the API event loop.  This module restores it:

* each render batch runs in a ``spawn``-ed child, so an ovrtx crash (segfault,
  ``abort``) cannot take down the API worker;
* a psutil watcher kills the child if its RSS exceeds ``kit_worker_memory_limit``
  (MB) and surfaces :class:`OutOfMemoryError`.  RSS (not ``RLIMIT_AS``) is used
  on purpose: CUDA reserves a huge virtual address space, so an address-space
  cap would kill the child immediately;
* the parent hard-kills the child once the batch deadline passes.

This module lives outside the ``ovrtx_rendering`` package on purpose: importing
that package runs its ``__init__`` which loads ovrtx, so keeping the worker
separate lets the parent import it while ovrtx is only ever loaded in the child.
Rendered payloads are streamed back over a pipe and the network transport stays
in the parent, which owns the websocket/http/redis connections.
"""

import asyncio
import logging
import multiprocessing
import os
import shutil
import tempfile
import time
import traceback
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnProcess
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import psutil

from .exceptions import LoadError, OutOfMemoryError, TimeoutError, UnknownBackendError
from .models import (
    Authentication,
    kit_process_memory_gauge,
    kit_process_memory_gauge_percentage,
    kit_process_pid_gauge,
    kit_process_rendering_time_gauge,
    kit_process_rendering_time_percentage_gauge,
)
from .transport import ContentType
from .utils import serialize_payload

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.1
_KILL_JOIN_TIMEOUT = 5.0


def get_camera_positions(render_settings: Optional[Dict[str, Any]] = None) -> List[Any]:
    """Build the list of camera positions for a render from the request settings."""
    from .ovrtx_rendering.renderer import CameraPosition

    azimuths = [45, 135, 225, 315]
    elevations = [60, 45]

    if render_settings is None:
        return [CameraPosition(az=az, el=el) for el in elevations for az in azimuths]

    strategy = render_settings.get("camera_placing_strategy", "manual")
    if strategy == "random":
        import numpy as np

        n = render_settings.get("n_random_cameras", 8)
        return [CameraPosition(az=float(np.random.rand() * 360), el=float(np.random.rand() * 90)) for _ in range(n)]

    positions = render_settings.get("camera_positions")
    if positions:
        return [CameraPosition(az=p["az"], el=p["el"]) for p in positions]

    return [CameraPosition(az=az, el=el) for el in elevations for az in azimuths]


def get_camera_parameters(
    render_settings: Optional[Dict[str, Any]] = None, default_width: int = 448, default_height: int = 448
) -> Any:
    """Build the camera parameters (resolution) for a render from the request settings."""
    from .ovrtx_rendering.renderer import CameraParameters

    if render_settings is None:
        return CameraParameters(width=default_width, height=default_height)

    params = render_settings.get("camera_parameters")
    if params:
        return CameraParameters(width=params.get("width", default_width), height=params.get("height", default_height))

    return CameraParameters(
        width=render_settings.get("width", default_width), height=render_settings.get("height", default_height)
    )


def apply_storage_env(auth: Authentication) -> None:
    """Export Storage API settings before ovrtx's client library initializes.

    The bundled client reads these variables once, on the initial ``import ovrtx``;
    set later they take no effect and the backend stays unregistered. ``storage_api_url``
    is a direct endpoint registered via ``OMNI_STORAGE_HOST`` (matching Kit's
    ``register_storage_direct``), while ``storage_api_discovery_url`` instead points the
    client at a Discovery Service that advertises the backing services through
    ``/api/v1/services`` (the self-hosted CI stack).
    """
    if auth.storage_api_discovery_url:
        os.environ["OMNI_STORAGE_DISCOVERY"] = auth.storage_api_discovery_url
        if auth.storage_api_token:
            os.environ["OMNI_STORAGE_AUTHORIZATION"] = f"Bearer {auth.storage_api_token}"
        return
    if not auth.storage_api_url:
        return
    parsed = urlparse(auth.storage_api_url if "://" in auth.storage_api_url else f"//{auth.storage_api_url}")
    port = str(parsed.port) if parsed.port else "443"
    os.environ["OMNI_STORAGE_HOST"] = parsed.hostname or ""
    os.environ["OMNI_STORAGE_PORT"] = port
    os.environ["OMNI_STORAGE_SECURE"] = "1" if parsed.scheme in ("grpcs", "https") or port == "443" else "0"
    if auth.storage_api_token:
        os.environ["OMNI_STORAGE_AUTHORIZATION"] = f"Bearer {auth.storage_api_token}"


def apply_nucleus_env(auth: Authentication) -> None:
    """Export Nucleus credentials before ovrtx's client library initializes.

    The bundled client reads ``OMNI_USER``/``OMNI_PASS`` once, when it first comes
    up on the initial ``import ovrtx``.  In the long-lived in-process renderer they
    were only set later, inside ``prepare_asset`` after the client was already up,
    so ``omniverse://`` auth silently failed.  Each isolated render is a fresh
    process, so seeding them here (before the ovrtx import) makes Nucleus auth take
    effect per request.  A no-op for non-Nucleus requests, which leave ``omni_user``
    empty.
    """
    if not auth.omni_user:
        return
    os.environ["OMNI_USER"] = auth.omni_user
    os.environ["OMNI_USERNAME"] = auth.omni_user
    os.environ["OMNI_PASS"] = auth.omni_pass
    os.environ["OMNI_PASSWORD"] = auth.omni_pass


def serialize_content(content: Any, compress: bool = True) -> str:
    """Serialize rendered content into the transport's string payload."""
    return serialize_payload(content, compress=compress)


def _render_one(
    renderer: Any,
    prepare_asset: Any,
    probe_stage: Any,
    url: str,
    url_override: str,
    auth: Authentication,
    cfg: Dict[str, Any],
) -> ContentType:
    """Render a single asset into a :class:`ContentType`, mapping failures to error payloads.

    A cooperative :class:`TimeoutError` is left to propagate so the caller can fail the batch.
    """
    try:
        with prepare_asset(url, auth) as openable_url:
            probe = probe_stage(openable_url, auth)
            rendered = renderer.get_asset_renderings(
                omni_path=openable_url,
                camera_positions=cfg["camera_positions"],
                camera_parameters=cfg["camera_parameters"],
                sensors=cfg["sensors"],
                timeout=cfg["per_asset_timeout"],
                up_axis=probe.up_axis,
                apply_default_material=probe.needs_default_material,
                adjust_framing=cfg["adjust_framing"],
                render_existing_views=cfg["render_existing_views"],
                default_prim=probe.default_prim,
            )
        if isinstance(rendered, str) and rendered == "":
            return ContentType(path=url_override, content="empty_scene")
        return ContentType(path=url_override, content=serialize_content(rendered, compress=cfg["compress"]))
    except LoadError as exc:
        return ContentType(
            path=url_override, content="load_error", exception=str(exc), traceback=traceback.format_exc()
        )
    except TimeoutError:
        raise
    except Exception as exc:  # pylint: disable=broad-except
        return ContentType(
            path=url_override, content=f"Error rendering: {exc}", exception=str(exc), traceback=traceback.format_exc()
        )


def _child_render(conn: Connection, spec: Dict[str, Any]) -> None:
    """Child entry point: render every URL in ``spec`` and stream results back.

    Runs in the spawned process, so all ovrtx imports happen here.  Each asset
    produces one ``("result", url, url_hash, ContentType)`` message; the batch
    ends with ``("done", ...)``, a cooperative timeout with ``("timeout", ...)``,
    and a startup failure with ``("fatal", ...)``.
    """
    try:
        # ovrtx reads storage and Nucleus credentials, and captures the config path, once when
        # first imported, so point it at this child's private config dir and set creds first.
        auth = spec["auth"]
        os.environ["OVRTX_OMNI_CONFIG_DIR"] = spec["omni_config_dir"]
        os.environ["OVRTX_SHADER_CACHE_DIR"] = spec["material_cache_dir"]
        apply_storage_env(auth)
        apply_nucleus_env(auth)

        # Imported here so ovrtx is only ever loaded in the child, after the env is set.
        from .ovrtx_rendering import OvrtxViewRenderer
        from .ovrtx_rendering.asset_source import prepare_asset, probe_stage

        render_settings = spec["render_settings"]
        cfg = {
            "camera_positions": get_camera_positions(render_settings),
            "camera_parameters": get_camera_parameters(render_settings),
            "sensors": render_settings.get("sensors") if render_settings else None,
            "adjust_framing": render_settings.get("adjust_camera_multiplier", True) if render_settings else True,
            "render_existing_views": render_settings.get("render_existing_views", True) if render_settings else True,
            "per_asset_timeout": spec["per_asset_timeout"],
            "compress": spec.get("compress_payload", True),
        }

        renderer = OvrtxViewRenderer()
        try:
            for url, url_override, url_hash in zip(spec["urls"], spec["url_overrides"], spec["url_hashes"]):
                try:
                    content = _render_one(renderer, prepare_asset, probe_stage, url, url_override, auth, cfg)
                except TimeoutError:
                    # A cooperative timeout fails the whole batch, matching the pre-isolation behaviour.
                    conn.send(("timeout", url_override, None, traceback.format_exc()))
                    return
                conn.send(("result", url_override, url_hash, content))
        finally:
            renderer.shutdown()
        conn.send(("done", None, None, None))
    except Exception as exc:  # pylint: disable=broad-except
        try:
            conn.send(("fatal", None, None, f"{exc}\n{traceback.format_exc()}"))
        except Exception:  # pylint: disable=broad-except
            pass
    finally:
        conn.close()


def _kill(proc: SpawnProcess) -> None:
    """Terminate the worker, escalating to SIGKILL if it does not exit."""
    if proc.is_alive():
        proc.terminate()
        proc.join(_KILL_JOIN_TIMEOUT)
    if proc.is_alive():
        proc.kill()
        proc.join(_KILL_JOIN_TIMEOUT)


def _raise_for_terminal(kind: str, payload: Any) -> None:
    """Raise the matching exception for a terminal (``timeout``/``fatal``) child message."""
    if kind == "timeout":
        raise TimeoutError(payload if isinstance(payload, str) else "Rendering timeout")
    if kind == "fatal":
        raise UnknownBackendError(f"Render worker failed to start: {payload}")


def _update_worker_gauges(
    worker_label: str, memory_limit_mb: int, rss_mb: Optional[float], elapsed: float, batch_timeout: float
) -> None:
    """Publish the render worker's live rendering-time and memory metrics."""
    kit_process_rendering_time_gauge.labels(worker_id=worker_label).set(elapsed)
    if batch_timeout > 0:
        kit_process_rendering_time_percentage_gauge.labels(worker_id=worker_label).set(elapsed / batch_timeout * 100)
    if rss_mb is None or memory_limit_mb <= 0:
        return
    labels = {"worker_id": worker_label, "memory_limit": memory_limit_mb}
    kit_process_memory_gauge.labels(**labels).set(rss_mb)
    kit_process_memory_gauge_percentage.labels(**labels).set(rss_mb / memory_limit_mb * 100)


def _reset_worker_gauges(worker_label: str, memory_limit_mb: int) -> None:
    """Clear the render worker's metrics once the batch ends, so they do not pin to stale values."""
    kit_process_pid_gauge.labels(worker_id=worker_label).set(0)
    kit_process_rendering_time_gauge.labels(worker_id=worker_label).set(0)
    kit_process_rendering_time_percentage_gauge.labels(worker_id=worker_label).set(0)
    if memory_limit_mb > 0:
        labels = {"worker_id": worker_label, "memory_limit": memory_limit_mb}
        kit_process_memory_gauge.labels(**labels).set(0)
        kit_process_memory_gauge_percentage.labels(**labels).set(0)


def _make_material_cache_dir() -> str:
    """Create a private ovrtx material (UJITSO datastore) cache for one render child.

    ovrtx keys compiled MDL materials of remote assets by the module's content alone and
    bakes in the texture URLs resolved for whichever asset compiled it first. SimReady
    ships byte-identical MDL files next to each asset's own textures, so a cache shared
    across renders gives later assets the wrong (or inaccessible) textures. A per-child
    cache costs a few seconds per render; the expensive driver shader cache is separate.
    Created under ``OVRTX_SHADER_CACHE_DIR`` when set, keeping it on the mounted volume.
    """
    cache_root = os.getenv("OVRTX_SHADER_CACHE_DIR") or None
    if cache_root:
        os.makedirs(cache_root, exist_ok=True)
    return tempfile.mkdtemp(prefix="ovrtx_material_cache_", dir=cache_root)


def _remove_private_dirs(spec: Dict[str, Any]) -> None:
    shutil.rmtree(spec["omni_config_dir"], ignore_errors=True)
    shutil.rmtree(spec["material_cache_dir"], ignore_errors=True)


async def run_isolated_render(
    spec: Dict[str, Any], *, memory_limit_mb: int, batch_timeout: float
) -> AsyncIterator[Tuple[str, str, ContentType]]:
    """Render ``spec`` in a child process, yielding ``(url, url_hash, content)`` per asset.

    Raises :class:`OutOfMemoryError` if the child exceeds ``memory_limit_mb`` (when
    positive), :class:`TimeoutError` on the batch deadline or a cooperative
    timeout, and :class:`UnknownBackendError` if the child crashes.
    """
    # A private config dir per child isolates each render's omniverse.toml; the parent owns it
    # so cleanup is guaranteed even when the child is killed on timeout or OOM.
    spec = {
        **spec,
        "omni_config_dir": tempfile.mkdtemp(prefix="ovrtx_omni_config_"),
        "material_cache_dir": _make_material_cache_dir(),
    }

    ctx = multiprocessing.get_context("spawn")
    parent_conn, child_conn = ctx.Pipe()
    proc = ctx.Process(target=_child_render, args=(child_conn, spec))
    try:
        proc.start()
    except Exception:  # pylint: disable=broad-except
        # start() failing here is before the try/finally below, so release the pipe and private dirs.
        child_conn.close()
        parent_conn.close()
        _remove_private_dirs(spec)
        raise
    child_conn.close()  # only the child writes to its end

    watch_memory = memory_limit_mb > 0
    ps_proc = psutil.Process(proc.pid) if watch_memory else None
    deadline = time.monotonic() + batch_timeout if batch_timeout > 0 else None

    worker_label = f"pid_{proc.pid}"
    start_time = time.monotonic()
    kit_process_pid_gauge.labels(worker_id=worker_label).set(proc.pid)

    try:
        while True:
            now = time.monotonic()
            rss_mb = None
            if ps_proc is not None:
                try:
                    rss_mb = ps_proc.memory_info().rss / 1024 / 1024
                except psutil.NoSuchProcess:
                    rss_mb = 0.0
            _update_worker_gauges(worker_label, memory_limit_mb, rss_mb, now - start_time, batch_timeout)

            if parent_conn.poll(0):
                kind, url_override, url_hash, payload = parent_conn.recv()
                if kind == "result":
                    yield url_override, url_hash, payload
                    continue
                _raise_for_terminal(kind, payload)  # raises for timeout/fatal
                return  # "done"

            if rss_mb is not None and rss_mb > memory_limit_mb:
                logger.warning("Render worker exceeded %d MB (RSS %.0f MB); killing", memory_limit_mb, rss_mb)
                _kill(proc)
                raise OutOfMemoryError(f"Render worker exceeded {memory_limit_mb} MB (RSS {rss_mb:.0f} MB)")

            if deadline is not None and now > deadline:
                logger.warning("Render worker exceeded batch timeout of %.0fs; killing", batch_timeout)
                _kill(proc)
                raise TimeoutError(f"Rendering timeout after {batch_timeout:.0f} seconds")

            if not proc.is_alive() and not parent_conn.poll(0):
                # A clean finish always sends "done" first, so reaching here means the child died.
                raise UnknownBackendError(f"Render worker crashed (exit code {proc.exitcode})")

            await asyncio.sleep(_POLL_INTERVAL)
    finally:
        _reset_worker_gauges(worker_label, memory_limit_mb)
        _kill(proc)
        parent_conn.close()
        _remove_private_dirs(spec)
