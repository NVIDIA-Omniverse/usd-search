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

import atexit
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from deepsearch_rendering_job.exceptions import LoadError
from deepsearch_rendering_job.models import Authentication
from deepsearch_rendering_job.utils import redact_url

logger = logging.getLogger(__name__)

# Resolved once per process by ``init_omni_config_path``. Each worker process gets its
# own directory so concurrent renders never share (and race on) a single ``omniverse.toml``.
_OMNI_CONFIG: Dict[str, str] = {}


def _config_dir() -> str:
    config_dir = _OMNI_CONFIG.get("dir")
    if config_dir is None:
        raise RuntimeError("omni config path not initialized; call init_omni_config_path() first")
    return config_dir


def _config_file() -> str:
    config_file = _OMNI_CONFIG.get("file")
    if config_file is None:
        raise RuntimeError("omni config path not initialized; call init_omni_config_path() first")
    return config_file


def _cache_root() -> str:
    """The resolver's on-disk download cache for referenced USD/texture layers.

    Defaults to a subdirectory of the per-process config dir (ephemeral /tmp) so
    local/dev usage needs no extra setup; deployments with a dedicated, shared
    cache volume should set ``OVRTX_USD_CACHE_DIR`` to point at it.
    """
    return os.getenv("OVRTX_USD_CACHE_DIR") or os.path.join(_config_dir(), "cache")


# Bounds the resolver cache's on-disk footprint. Without a cap the client library never
# evicts downloaded layers, so a long-lived renderer process (or a shared cache volume)
# grows unbounded. Defaults to 20GiB; deployments should size this under their mounted
# cache volume's capacity.
_CACHE_MAX_SIZE_BYTES = os.getenv("OVRTX_CACHE_MAX_SIZE_BYTES", str(20 * 1024**3))
_CACHE_CLEANUP_THRESHOLD = os.getenv("OVRTX_CACHE_CLEANUP_THRESHOLD", "0.8")
_CACHE_GC_INTERVAL_SECONDS = os.getenv("OVRTX_CACHE_GC_INTERVAL_SECONDS", "300")

_STAGE_PROBE = os.path.join(os.path.dirname(__file__), "_stage_probe.py")
_STAGE_PROBE_TIMEOUT = 60


@dataclass
class StageProbe:
    """Out-of-band findings about an asset's root layer.

    ``up_axis`` is the authored up axis (``"Y"``/``"Z"``) or ``None``.
    ``default_prim`` is the root layer's ``defaultPrim`` or ``None``.
    ``needs_default_material`` is true when the asset has renderable geometry but no
    renderable material, so it should get Kit's grey-clay fallback.
    """

    up_axis: Optional[str] = None
    default_prim: Optional[str] = None
    needs_default_material: bool = False


def _base_omni_config() -> str:
    """``[paths]``/``[cache]`` config shared by every backend, S3 or not.

    A per-host ``[s3]`` table is appended on top of this by ``_write_s3_config``;
    Nucleus and public-URL renders never call that, so this must stand on its own
    for the cache root and size cap to apply to them too.
    """
    cache_root = _cache_root()
    logs_root = os.path.join(_config_dir(), "logs")
    return (
        f'[paths]\ncache_root = "{cache_root}"\nlogs_root = "{logs_root}"\n\n'
        f'[cache]\npath = "{cache_root}"\nmax_size = {_CACHE_MAX_SIZE_BYTES}\n'
        f"cleanup_threshold = {_CACHE_CLEANUP_THRESHOLD}\n"
        f"garbage_collection_interval = {_CACHE_GC_INTERVAL_SECONDS}\n\n"
    )


def init_omni_config_path() -> None:
    """Point the bundled client library at a private, writable config directory.

    The library captures ``OMNI_CONFIG_PATH`` when it initializes, so this must
    run before ``ovrtx`` is imported.  Writes the base ``[paths]``/``[cache]``
    config up front so the cache root and size cap apply to every backend, not
    just credentialed S3 requests; per-request S3 credentials are then written
    on top of it into this directory's ``omniverse.toml`` for the resolver to
    sign requests and resolve referenced layers natively.

    The directory is per-process: the render worker exports ``OVRTX_OMNI_CONFIG_DIR``
    for its child (and owns the cleanup), while any other in-process use falls back
    to a self-cleaning temp dir.  This keeps concurrent workers from sharing, and
    racing on, one ``omniverse.toml`` (which would leak one request's credentials
    into another's resolver).
    """
    config_dir = os.environ.get("OVRTX_OMNI_CONFIG_DIR")
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    else:
        config_dir = tempfile.mkdtemp(prefix="ovrtx_omni_config_")
        atexit.register(shutil.rmtree, config_dir, ignore_errors=True)
    _OMNI_CONFIG["dir"] = config_dir
    _OMNI_CONFIG["file"] = os.path.join(config_dir, "omniverse.toml")
    os.environ["OMNI_CONFIG_PATH"] = config_dir
    os.makedirs(_cache_root(), exist_ok=True)
    os.makedirs(os.path.join(config_dir, "logs"), exist_ok=True)
    with open(_config_file(), "w", encoding="utf-8") as config_file:
        config_file.write(_base_omni_config())
    _preseed_s3_config()
    _preseed_nucleus_config()


def _preseed_nucleus_config() -> None:
    """Seed Nucleus credentials before the resolver initializes.

    Like ``_preseed_s3_config``, the client reads ``OMNI_USER``/``OMNI_PASS`` once
    when it first comes up, so seeding from the ambient ``OV_USERNAME``/
    ``OV_PASSWORD`` guarantees ``omniverse://`` auth is configured before the
    resolver initializes rather than set too late (inside ``prepare_asset``).
    ``setdefault`` so a per-request value already exported by the caller wins.
    """
    username = os.getenv("OV_USERNAME")
    password = os.getenv("OV_PASSWORD")
    if not (username and password):
        return
    os.environ.setdefault("OMNI_USER", username)
    os.environ.setdefault("OMNI_USERNAME", username)
    os.environ.setdefault("OMNI_PASS", password)
    os.environ.setdefault("OMNI_PASSWORD", password)


def _preseed_s3_config() -> None:
    """Seed S3 credentials before the resolver initializes.

    The resolver reads ``omniverse.toml`` once when it first comes up, which (for
    a long-lived in-process renderer) happens on the first render regardless of
    its URL type.  Seeding from the ambient AWS environment guarantees a valid
    config is present at that moment, so a per-request write that lands after
    initialization is not silently ignored.
    """
    access_key_id = os.getenv("AWS_ACCESS_KEY_ID")
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    bucket = os.getenv("OVRTX_S3_BUCKET", "deepsearch-test-bucket")
    region = os.getenv("OVRTX_S3_REGION", "eu-central-1")
    if not (access_key_id and secret_access_key and bucket and region):
        return
    auth = Authentication(
        aws_bucket=bucket,
        aws_region=region,
        aws_access_key_id=access_key_id,
        aws_access_key=secret_access_key,
    )
    _write_s3_config(f"https://{bucket}.s3.{region}.amazonaws.com", auth)


def _is_omniverse_url(url: str) -> bool:
    return url.startswith("omniverse://")


def _is_s3_url(url: str) -> bool:
    return url.startswith(("http://", "https://")) and "amazonaws.com" in url


def _has_aws_credentials(auth: Authentication) -> bool:
    return bool(auth.aws_access_key_id and auth.aws_access_key and auth.aws_region)


def _nucleus_overrides(url: str, auth: Authentication) -> Dict[str, str]:
    """Environment overrides that ovrtx's bundled Omniverse Client Library reads
    to authenticate Nucleus connections."""
    overrides: Dict[str, str] = {}
    if _is_omniverse_url(url) and auth.omni_user:
        overrides["OMNI_USER"] = auth.omni_user
        overrides["OMNI_USERNAME"] = auth.omni_user
        overrides["OMNI_PASS"] = auth.omni_pass
        overrides["OMNI_PASSWORD"] = auth.omni_pass
    return overrides


def _write_s3_config(url: str, auth: Authentication) -> None:
    """Write per-host S3 credentials into the client library's ``omniverse.toml``.

    Mirrors the Kit worker's config: the shared ``[paths]``/``[cache]`` base plus
    a per-host ``[s3]`` table keyed by the virtual-hosted bucket endpoint, so the
    resolver signs requests for the asset and every layer it references.
    """
    config = _base_omni_config() + "[s3]\n"
    if auth.aws_endpoint:
        host = re.sub(r"^https?://", "", auth.aws_endpoint)
        config += (
            f'[s3."{host}"]\n'
            f'accessKeyId = "{auth.aws_access_key_id}"\n'
            f'secretAccessKey = "{auth.aws_access_key}"\n'
        )
    else:
        bucket = auth.aws_bucket or urlparse(url).netloc.split(".")[0]
        host = f"{bucket}.s3.{auth.aws_region}.amazonaws.com"
        config += (
            f'[s3."{host}"]\n'
            f'accessKeyId = "{auth.aws_access_key_id}"\n'
            f'bucket = "{bucket}"\n'
            f'region = "{auth.aws_region}"\n'
            f'secretAccessKey = "{auth.aws_access_key}"\n'
        )
    with open(_config_file(), "w", encoding="utf-8") as config_file:
        config_file.write(config)


def _clear_s3_config() -> None:
    """Drop the per-request ``[s3]`` credentials, restoring the base config.

    Not a plain delete: the base ``[paths]``/``[cache]`` config must keep
    applying to whatever request (S3 or not) comes after this one on the same
    long-lived renderer process.
    """
    try:
        with open(_config_file(), "w", encoding="utf-8") as config_file:
            config_file.write(_base_omni_config())
    except OSError:
        pass


def _verify_s3_access(url: str, auth: Authentication) -> None:
    """Reject a request whose credentials do not grant access to the S3 asset.

    The bundled resolver caches the credentials it first authenticates a host
    with, so once the process is warm a later request cannot be served with a
    different set of credentials than the one already cached.  A signed HEAD with
    the request's own credentials restores per-request enforcement: a caller
    presenting credentials without access is rejected instead of being served
    through the resolver's cached connection.
    """
    parsed = urlparse(url)
    client = boto3.client(
        "s3",
        region_name=auth.aws_region,
        aws_access_key_id=auth.aws_access_key_id,
        aws_secret_access_key=auth.aws_access_key,
        endpoint_url=auth.aws_endpoint or None,
        config=Config(retries={"max_attempts": 0}, connect_timeout=5, read_timeout=5),
    )
    try:
        client.head_object(Bucket=auth.aws_bucket or parsed.netloc.split(".")[0], Key=parsed.path.lstrip("/"))
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") in (401, 403):
            raise LoadError(f"Access denied for {url}", url=url) from exc


def _s3_client(auth: Authentication) -> "boto3.client":
    return boto3.client(
        "s3",
        region_name=auth.aws_region,
        aws_access_key_id=auth.aws_access_key_id,
        aws_secret_access_key=auth.aws_access_key,
        endpoint_url=auth.aws_endpoint or None,
        config=Config(retries={"max_attempts": 1}, connect_timeout=5, read_timeout=30),
    )


def _localize_root_layer(url: str, auth: Authentication) -> Tuple[Optional[str], Callable[[], None]]:
    """Return a local path to the asset's root layer (downloading remote ones) and a cleanup callback.

    Only the root layer is needed since the authored ``upAxis`` lives there. Nucleus
    (``omniverse://``) assets have no ovrtx-independent reader, so they are skipped.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()

    if scheme in ("", "file"):
        path = parsed.path if scheme == "file" else url
        return (path if os.path.exists(path) else None, lambda: None)

    if _is_omniverse_url(url):
        return (None, lambda: None)

    suffix = os.path.splitext(parsed.path)[1] or ".usd"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.close()

    def _cleanup() -> None:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    if _is_s3_url(url) and _has_aws_credentials(auth):
        bucket = auth.aws_bucket or parsed.netloc.split(".")[0]
        _s3_client(auth).download_file(bucket, parsed.path.lstrip("/"), handle.name)
        return handle.name, _cleanup

    if scheme in ("http", "https"):
        import httpx

        with httpx.stream("GET", url, timeout=30, follow_redirects=True) as response:
            response.raise_for_status()
            with open(handle.name, "wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
        return handle.name, _cleanup

    _cleanup()
    return (None, lambda: None)


def probe_stage(url: str, auth: Authentication) -> StageProbe:
    """Read the asset's up axis, defaultPrim and material-fallback hint in one isolated subprocess.

    ``usd-core``'s ``pxr`` cannot share a process with a live ``ovrtx.Renderer`` (both
    register USD schema types), so the root layer is inspected out of band.
    """
    local_path, cleanup = None, None
    try:
        local_path, cleanup = _localize_root_layer(url, auth)
        if local_path is None:
            return StageProbe()
        # Strip PXR_* (ovrtx exports PXR_PLUGINPATH_NAME pointing at its own USD
        # plugins); inheriting it makes usd-core load ovrtx's schemas and clash.
        env = {key: value for key, value in os.environ.items() if not key.startswith("PXR_")}
        result = subprocess.run(
            [sys.executable, _STAGE_PROBE, local_path],
            capture_output=True,
            text=True,
            timeout=_STAGE_PROBE_TIMEOUT,
            check=False,
            env=env,
        )
        parsed = json.loads(result.stdout.strip() or "{}")
        return StageProbe(
            up_axis=parsed.get("up_axis") or None,
            default_prim=parsed.get("default_prim") or None,
            needs_default_material=bool(parsed.get("needs_default_material")),
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("Could not probe stage for %s: %s", redact_url(url), exc)
        return StageProbe()
    finally:
        if cleanup is not None:
            cleanup()


@contextmanager
def prepare_asset(url: str, auth: Authentication) -> Iterator[str]:
    """Yield an openable asset URL with credentials configured for ovrtx's resolver.

    Credentialed S3 assets get their bucket credentials written to the client
    library's ``omniverse.toml`` so the resolver signs requests and resolves
    multi-file references natively.  Nucleus assets keep their ``omniverse://``
    URL with credentials exposed through the environment.  Public assets are
    yielded unchanged.
    """
    if _is_s3_url(url) and _has_aws_credentials(auth):
        _verify_s3_access(url, auth)
        _write_s3_config(url, auth)
        try:
            yield url
        finally:
            _clear_s3_config()
        return

    overrides = _nucleus_overrides(url, auth)
    if not overrides:
        yield url
        return

    previous: Dict[str, Optional[str]] = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield url
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
