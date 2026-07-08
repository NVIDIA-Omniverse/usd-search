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

import base64
import hashlib
import io
import json
import logging
import re
import zipfile
from typing import Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from cachetools import TTLCache
from deepsearch_rendering_job.models import Authentication
from fastapi import HTTPException, Response, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasicCredentials

from ..exceptions import (
    InvalidMTLNames,
    LoadError,
    RenderError,
    UnknownBackendError,
    UnsupportedMediaType,
)
from ..models import RenderingStatus, response_status_gauge
from ..utils import (
    extract_camera_metadata_from_payload,
    extract_images_from_payload,
    unpickle_data,
)
from .config import get_package_version
from .models import ContentType, RenderResponse, SupportedMediaTypes, URLType


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Exclude healthchecks from access logs
        message = record.getMessage()
        return message.find("/health") == -1 and message.find("/readyz") == -1 and message.find("/metrics") == -1


class TooManyRequestsLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Exclude 429 Too Many Requests from access logs
        message = record.getMessage()
        return not ("429" in message or "Too Many Requests" in message)


def get_key(url: str, auth: Optional[Authentication] = None) -> str:
    string_to_hash = str(url)
    if auth is not None:
        string_to_hash += json.dumps(auth.dict())
    return hashlib.sha256(string_to_hash.encode()).hexdigest()


def parse_url(url: str) -> str:
    """
    Parse the URL and return the base URL.
    """
    if url.startswith("omniverse://"):
        return URLType.omniverse
    elif url.startswith("https://") and "amazonaws.com" in url:
        return URLType.s3
    elif url.startswith(("http://", "https://")):
        # Non-AWS S3-compatible endpoints (MinIO, s3proxy, etc.)
        # Kit's Omniverse client library fetches these via the base HTTP provider.
        return URLType.s3
    else:
        raise ValueError(f"Invalid URL: {url}")


def parse_aws_url(url: str) -> Dict[str, str]:
    """
    Parse an AWS S3 URL and extract bucket, region, and key information.

    Args:
        url: The AWS S3 URL to parse (e.g., https://bucket-name.s3.region.amazonaws.com/path/to/file)

    Returns:
        Dictionary containing:
        - bucket: The S3 bucket name
        - region: The AWS region
        - key: The object key (path)
        - endpoint: The S3 endpoint URL

    Raises:
        ValueError: If the URL is not a valid AWS S3 URL
    """
    try:
        # Parse the URL
        parsed = urlparse(url)

        if not parsed.scheme.startswith("https"):
            raise ValueError("URL must use HTTPS protocol")

        # Extract hostname and path
        hostname = parsed.netloc
        path = unquote(parsed.path.lstrip("/"))

        # Match S3 URL pattern
        # Pattern: bucket-name.s3.region.amazonaws.com
        s3_pattern = r"^(.+)\.s3\.([^.]+)?\.amazonaws\.com$"
        match = re.match(s3_pattern, hostname)

        if not match:
            raise ValueError("Invalid AWS S3 URL format")

        bucket = match.group(1)
        region = match.group(2) or "us-east-1"  # Default to us-east-1 if region not specified

        # Construct the endpoint
        endpoint = f"https://s3.{region}.amazonaws.com"

        return {"bucket": bucket, "region": region, "key": path, "endpoint": endpoint}

    except Exception as e:
        raise ValueError(f"Failed to parse AWS URL: {str(e)}")


def get_bucket_and_region(url: str) -> Tuple[str, str]:
    """
    Extract bucket and region from an AWS S3 URL.

    Args:
        url: The AWS S3 URL

    Returns:
        Tuple of (bucket_name, region)
    """
    parsed = parse_aws_url(url)
    return parsed["bucket"], parsed["region"]


def create_zip_archive(images_base64: list[str], camera_metadata: Optional[list[str]], url: str) -> io.BytesIO:
    """
    Create a zip archive containing all the rendered images.

    Args:
        images_base64: List of base64-encoded JPEG images
        url: Original URL for naming purposes

    Returns:
        BytesIO object containing the zip archive
    """
    zip_buffer = io.BytesIO()

    # Extract filename from URL for naming
    url_parts = url.split("/")
    base_name = url_parts[-1].split(".")[0] if url_parts else "rendered"

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i, image_b64 in enumerate(images_base64):
            # Decode base64 image
            image_data = base64.b64decode(image_b64)

            if camera_metadata is not None:
                camera_metadata_data = camera_metadata[i]
                zip_file.writestr(
                    f"{base_name}_camera_metadata_{i+1:03d}.json",
                    json.dumps(json.loads(camera_metadata_data), indent=2),
                )

            # Add image to zip with sequential naming
            filename = f"{base_name}_image_{i+1:03d}.jpg"
            zip_file.writestr(filename, image_data)

        # Optionally add metadata file
        metadata = {
            "source_url": url,
            "total_images": len(images_base64),
            "generated_by": "USD Search Rendering Service",
            "version": get_package_version(),
        }
        zip_file.writestr("metadata.json", json.dumps(metadata, indent=2))

    zip_buffer.seek(0)
    return zip_buffer


def prepare_rendering_response(
    payload: Optional[ContentType] = None,
    cache_key: Optional[str] = None,
    cache: Optional[TTLCache] = None,
    url: Optional[str] = None,
    content_type: str = "application/json",
    enable_caching: bool = True,
) -> Response:
    """
    Prepare the rendering response from the cache.

    Args:
        cache_key: The cache key
        cache: The TTL cache
        url: Original URL for naming purposes
        content_type: Response format (application/json or application/zip)
        enable_caching: Whether to enable caching
    """
    if payload is None:
        payload: ContentType = cache[cache_key]
    else:
        payload = payload

    rendering_response = payload.content
    unpickled_data = unpickle_data(rendering_response)

    if unpickled_data == RenderingStatus.load_error:
        raise LoadError(
            (payload.exception if payload.exception is not None else "Failed to load the asset"),
            traceback=payload.traceback,
            url=url,
        )

    if unpickled_data == RenderingStatus.invalid_mtl_names:
        raise InvalidMTLNames(
            payload.exception if payload.exception is not None else "Invalid MTL names",
            traceback=payload.traceback,
            url=url,
        )

    if unpickled_data == RenderingStatus.render_error:
        raise RenderError(
            (payload.exception if payload.exception is not None else "Failed to render the asset"),
            traceback=payload.traceback,
            url=url,
        )

    if unpickled_data == RenderingStatus.error:
        raise UnknownBackendError(
            (payload.exception if payload.exception is not None else "Unknown backend error"),
            traceback=payload.traceback,
            url=url,
        )

    if unpickled_data == "":
        if content_type == SupportedMediaTypes.zip:
            zip_buffer: io.BytesIO = create_zip_archive(images_base64=[], camera_metadata=[], url=url)
            url_parts = url.split("/")
            base_name = url_parts[-1].split(".")[0] if url_parts else "rendered"
            filename = f"{base_name}_renders.zip"
            response_status_gauge.labels(status=RenderingStatus.empty_scene.value).inc()
            return StreamingResponse(
                io.BytesIO(zip_buffer.read()),
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        response_status_gauge.labels(status=RenderingStatus.empty_scene.value).inc()
        return RenderResponse(images=[], camera_metadata=[], status=RenderingStatus.empty_scene)

    if unpickled_data == "timeout":
        raise TimeoutError(
            payload.exception if payload.exception is not None else "Rendering timeout",
            traceback=payload.traceback,
            url=url,
        )

    data = extract_images_from_payload(unpickled_data)
    camera_metadata = extract_camera_metadata_from_payload(unpickled_data)

    if content_type == SupportedMediaTypes.zip:
        # Create and return zip archive
        zip_buffer: io.BytesIO = create_zip_archive(images_base64=data, camera_metadata=camera_metadata, url=url)

        # Generate filename for download
        url_parts = url.split("/")
        base_name = url_parts[-1].split(".")[0] if url_parts else "rendered"
        filename = f"{base_name}_renders.zip"

        # Update the response status gauge
        if data == []:
            response_status_gauge.labels(status=RenderingStatus.empty_scene.value).inc()
        else:
            response_status_gauge.labels(status=RenderingStatus.success.value).inc()

        return StreamingResponse(
            io.BytesIO(zip_buffer.read()),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    elif content_type == SupportedMediaTypes.json:
        if enable_caching and payload is not None and cache is not None and cache_key is not None:
            cache[cache_key] = payload

        # Update the response status gauge
        if data == []:
            status = RenderingStatus.empty_scene
        else:
            status = RenderingStatus.success
        response_status_gauge.labels(status=status.value).inc()
        return RenderResponse(images=data, camera_metadata=camera_metadata, status=status)
    else:
        raise UnsupportedMediaType(
            f"Unsupported media type: {content_type}, expected: {SupportedMediaTypes.json} or {SupportedMediaTypes.zip}",
            traceback=None,
            url=url,
        )


def _parse_basic_auth_header(header_value: str) -> HTTPBasicCredentials:
    """
    Parse a Basic authorization value from a custom header into HTTPBasicCredentials.

    Accepts either the full value with the scheme prefix (e.g. "Basic dXNlcjpwYXNz")
    or just the base64 token (e.g. "dXNlcjpwYXNz").
    """
    try:
        if header_value is None:
            raise ValueError("Missing header value")

        value = header_value.strip()
        if value.lower().startswith("basic "):
            value = value[6:].strip()

        decoded = base64.b64decode(value).decode("utf-8")
        username, password = decoded.split(":", 1)
        return HTTPBasicCredentials(username=username, password=password)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-Basic-Auth header",
        ) from exc


def prepare_authentication(
    basic_auth: Optional[HTTPBasicCredentials],
    x_basic_auth: Optional[str],
    url: str,
    x_token_auth: Optional[str] = None,
    storage_api_url: Optional[str] = None,
) -> Authentication:
    """
    Prepare the authentication for the request based on the input URL.
    """
    # Storage API assets are authenticated with credentials forwarded
    # explicitly by the client (gRPC endpoint in the request body, optional
    # bearer token in the X-Token-Auth header), not via X-Basic-Auth and not
    # from this service's own environment. Short-circuit before parse_url,
    # whose URL scheme set does not cover Storage API URIs.
    if storage_api_url:
        return Authentication(storage_api_url=storage_api_url, storage_api_token=x_token_auth)

    url_type: URLType = parse_url(url)

    if basic_auth is None and x_basic_auth is not None:
        basic_auth = _parse_basic_auth_header(x_basic_auth)

    if url_type == URLType.omniverse:
        return Authentication(
            omni_user=basic_auth.username,
            omni_pass=basic_auth.password,
        )
    elif url_type == URLType.s3 and basic_auth is not None:
        bucket, region = get_bucket_and_region(url)
        return Authentication(
            aws_bucket=bucket,
            aws_region=region,
            aws_access_key_id=basic_auth.username,
            aws_access_key=basic_auth.password,
        )

    return Authentication()
