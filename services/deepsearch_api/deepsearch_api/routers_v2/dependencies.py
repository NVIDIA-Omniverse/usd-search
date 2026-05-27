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

import asyncio
import logging
import os
import time
from enum import Enum
from typing import Annotated, Dict, Optional, Tuple

from asset_graph_service_client.api_client import ApiClient
from asset_graph_service_client.configuration import Configuration
from deepsearch_api.auth import http_api_key, http_basic, http_bearer
from deepsearch_api.exceptions import AuthenticationError
from deepsearch_api.search_backend.embeddings import (
    EmbeddingType,
    USDSearchEmbeddingClient,
)
from deepsearch_api.search_backend.filtered import FilteredSearchClient
from deepsearch_api.search_backend.image_loader import (
    BaseImageLoader,
    MockImageLoader,
    OpenSearchImageLoader,
)
from deepsearch_api.search_backend.main import SearchBackendClientV2, SearchSettings
from deepsearch_api.utils import ags_client_with_headers
from deepsearch_api.validation import SearchResultValidator
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBasicCredentials
from opentelemetry import trace
from opentelemetry.context import attach, detach, set_value

from search_utils.storage_client import (
    AvailableStorageClients,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageConfig
from search_utils.storage_client.nucleus.auth import (
    NucleusAuth,
    NucleusStorageClientAuthenticationError,
)
from search_utils.storage_client.nucleus.config import NucleusStorageConfig

logger = logging.getLogger(__name__)

tracer = trace.get_tracer(__name__)


class Role(str, Enum):
    ADMIN = "admin"


class StorageConnectionCache:
    """LRU cache with TTL for storage connections."""

    def __init__(self, max_size: int = 25, ttl_seconds: int = 60 * 15):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Tuple[any, float, any]] = {}  # key -> (authenticated_client, timestamp, context_manager)
        self.access_order: Dict[str, float] = {}  # key -> access_time for LRU

    async def _close_connection(self, key: str) -> None:
        """Properly close a cached connection."""
        if key in self.cache:
            authenticated_client, _, context_manager = self.cache[key]
            try:
                # Close the connection context properly
                if context_manager is not None:
                    await context_manager.__aexit__(None, None, None)
                    logger.debug(f"Closed connection for cache key: {key}")
            except Exception as e:
                logger.warning(f"Error closing connection for cache key {key}: {e}")

    async def _evict_expired(self) -> None:
        """Remove expired entries from cache."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp, _) in self.cache.items() if current_time - timestamp > self.ttl_seconds
        ]
        for key in expired_keys:
            await self._close_connection(key)
            self.cache.pop(key, None)
            self.access_order.pop(key, None)

    async def _evict_lru(self) -> None:
        """Remove least recently used entry if cache is full."""
        if len(self.cache) >= self.max_size:
            # Find the least recently accessed key
            lru_key = min(self.access_order.keys(), key=lambda k: self.access_order[k])
            await self._close_connection(lru_key)
            self.cache.pop(lru_key, None)
            self.access_order.pop(lru_key, None)

    async def get(self, key: str) -> Optional[any]:
        """Get authenticated client from cache, updating access time."""
        await self._evict_expired()

        if key in self.cache:
            authenticated_client, _, _ = self.cache[key]
            self.access_order[key] = time.time()
            return authenticated_client
        return None

    async def put(self, key: str, authenticated_client: any, context_manager: any) -> None:
        """Put authenticated client in cache, evicting if necessary."""
        await self._evict_expired()
        await self._evict_lru()

        current_time = time.time()
        self.cache[key] = (authenticated_client, current_time, context_manager)
        self.access_order[key] = current_time


# Global cache instance and lock
_storage_connection_cache = StorageConnectionCache()
_storage_connection_creation_lock = asyncio.Lock()


def _create_cache_key(
    backend_type: AvailableStorageClients,
    role: Optional[Role],
    token_credentials: Optional[str],
    basic_username: Optional[str],
    basic_password: Optional[str],
) -> str:
    """Create a unique cache key for storage client configuration."""
    key_parts = [str(backend_type)]

    if role:
        key_parts.append(f"role:{role}")
    if token_credentials:
        # Use hash of token for security
        key_parts.append(f"token:{hash(token_credentials)}")
    if basic_username:
        key_parts.append(f"user:{basic_username}")
    if basic_password:
        # Use hash of password for security
        key_parts.append(f"pass:{hash(basic_password)}")

    return "|".join(key_parts)


async def _cached_storage_connection(
    backend_type: AvailableStorageClients,
    role: Optional[Role],
    token_credentials: Optional[str],
    basic_username: Optional[str],
    basic_password: Optional[str],
    config: Optional[StorageConfig],
) -> any:
    """Create or retrieve cached authenticated storage connection."""
    cache_key = _create_cache_key(backend_type, role, token_credentials, basic_username, basic_password)

    # Use lock to prevent race condition on check-create-cache sequence
    async with _storage_connection_creation_lock:
        # Try to get from cache first
        cached_connection = await _storage_connection_cache.get(cache_key)
        if cached_connection is not None:
            logger.debug(f"Using cached storage connection for key: {cache_key}")
            return cached_connection

        # Create new client and get authenticated connection if not in cache
        logger.debug(f"Creating new storage connection for key: {cache_key}")
        client = get_client(client_type=backend_type, config=config)

        # Get context manager and properly initialize connection
        try:
            connection_context = client.connection_context()
            authenticated_client = await connection_context.__aenter__()
        except NucleusStorageClientAuthenticationError as e:
            logger.error(f"Error creating storage connection for key: {cache_key}: {e}")
            raise AuthenticationError(f"Error creating storage connection for key: {cache_key}: {e}") from e
        except Exception as e:
            logger.error(f"Error creating storage connection for key: {cache_key}: {e}")
            if "DENIED" in str(e):
                raise AuthenticationError(f"Error creating storage connection for key: {cache_key}: {e}") from e
            else:
                raise ConnectionError(f"Error creating storage connection for key: {cache_key}: {e}") from e

        # Cache the authenticated connection with its context manager
        await _storage_connection_cache.put(cache_key, authenticated_client, connection_context)

        return authenticated_client


async def async_ags_client(request: Request) -> ApiClient:
    headers = {
        "X-Request-ID": request.headers["X-Request-ID"],
    }
    if "x-api-key" in request.headers:
        headers["x-api-key"] = request.headers["x-api-key"]
    if "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]

    logger.debug("Creating AGS client with headers: %s", headers)

    async with ags_client_with_headers(
        client=ApiClient(Configuration(host=request.app.global_settings.deepsearch_backend_asset_graph_service_url)),
        headers=headers,
    ) as async_ags_client:
        yield async_ags_client


async def api_key_auth_role(
    api_key: Annotated[str, Depends(http_api_key)],
    request: Request,
) -> Role | None:
    """
    Validate API key and return the corresponding role.
    Raises HTTPException if the API key is invalid.
    """
    if not api_key:
        return None

    if (
        request.app.global_settings.deepsearch_backend_admin_access_key is not None
        and api_key == request.app.global_settings.deepsearch_backend_admin_access_key
    ):
        return Role.ADMIN

    raise HTTPException(status_code=401, detail="Unauthorized: Invalid API key")


async def storage_client(
    token_auth: Annotated[HTTPAuthorizationCredentials, Depends(http_bearer)],
    basic_auth: Annotated[HTTPBasicCredentials, Depends(http_basic)],
    role: Annotated[Role, Depends(api_key_auth_role)],
    request: Request,
) -> StorageClient:
    storage_config = StorageConfig()
    backend_type = storage_config.storage_backend_type

    # Create storage config based on backend type and auth method
    config = None

    # Handle Nucleus-specific authentication
    if backend_type == AvailableStorageClients.nucleus:
        if role == Role.ADMIN:
            # For admin role, use environment-based config
            config = NucleusStorageConfig()  # This will use env vars by default
        elif token_auth:
            # For bearer token auth, create config with token
            config = NucleusStorageConfig(auth=NucleusAuth(token=token_auth.credentials))
        elif basic_auth and basic_auth.password:
            # For basic auth with password, create config with nucleus username and password
            config = NucleusStorageConfig(
                auth=NucleusAuth.model_construct(
                    user=basic_auth.username,
                    password=basic_auth.password,
                    assert_admin_user=False,
                )
            )
        elif basic_auth and basic_auth.username:
            # For username-only auth, config remains None but username is used for telemetry context
            logger.info(f"Username-only auth detected for Nucleus backend, user: {basic_auth.username}")
            config = None
    else:
        if basic_auth and basic_auth.username:
            logger.info(
                f"Basic auth detected for non-Nucleus backend ({backend_type}), using username for telemetry: {basic_auth.username}"
            )
        config = None  # Use default config for non-Nucleus backends

    if config is None and request.app.global_settings.storage_require_auth:
        # Only enforce auth requirement for Nucleus backends
        if backend_type == AvailableStorageClients.nucleus:
            raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid credentials")
        else:
            logger.info(f"Auth not required for backend type: {backend_type}")

    # Create or get cached authenticated connection with config containing credentials
    authenticated_client = await _cached_storage_connection(
        backend_type=backend_type,
        role=role,
        token_credentials=token_auth.credentials if token_auth else None,
        basic_username=basic_auth.username if basic_auth else None,
        basic_password=basic_auth.password if basic_auth else None,
        config=config,
    )

    # Set username as span attribute and context for telemetry
    current_span = trace.get_current_span()
    username = None

    # Extract username from different auth sources
    if backend_type == AvailableStorageClients.nucleus:
        # Extract username from JWT token
        from deepsearch_api.telemetry_decorator import (
            extract_telemetry_user_id_from_jwt,
        )

        username = extract_telemetry_user_id_from_jwt(authenticated_client.connection.auth.auth_token)
    elif basic_auth and basic_auth.username:
        username = basic_auth.username
    elif role == Role.ADMIN:
        username = "admin_access"

    if username and current_span:
        current_span.set_attribute("user.name", username)

        # Also set in OpenTelemetry context for child spans to access
        from deepsearch_api.telemetry_decorator import USERNAME_CONTEXT_KEY

        context = set_value(USERNAME_CONTEXT_KEY, username)
        token = attach(context)
        try:
            yield authenticated_client
        finally:
            detach(token)
    else:
        yield authenticated_client


async def siglip2_embedding_client(request: Request) -> USDSearchEmbeddingClient:
    return request.app.usd_search_embedding_client


async def search_backend_client_v2(
    request: Request,
    siglip2_embedding_client: Annotated[USDSearchEmbeddingClient, Depends(siglip2_embedding_client)],
    async_ags_client: Annotated[ApiClient, Depends(async_ags_client)],
    storage_client: Annotated[StorageClient, Depends(storage_client)],
) -> FilteredSearchClient:
    embedding_backends = {EmbeddingType.SIGLIP2_EMBEDDING: siglip2_embedding_client}
    async with SearchBackendClientV2(
        request.app.search_backend_settings, embedding_clients=embedding_backends
    ) as search_backend_client_v2:
        yield FilteredSearchClient(
            search_client=search_backend_client_v2,
            ags_client=async_ags_client,
            storage_client=storage_client,
            validate_access=request.app.global_settings.storage_require_auth,
        )


async def image_loader(request: Request) -> BaseImageLoader:
    """Create an image loader based on environment settings."""
    from search_utils.misc_utils import str2bool

    # Check if we should use mock image loader (useful for testing)
    mock_images = str2bool(os.getenv("MOCK_IMAGES", "False"))

    if mock_images:
        return MockImageLoader()
    else:
        # Create OpenSearch client with same settings as search backend
        settings: SearchSettings = request.app.search_backend_settings
        from opensearchpy import AsyncOpenSearch

        client = AsyncOpenSearch(
            hosts=[settings.opensearch_host],
            http_auth=(
                (settings.opensearch_username, settings.opensearch_password)
                if settings.opensearch_username and settings.opensearch_password
                else None
            ),
            timeout=settings.opensearch_timeout,
            use_ssl=settings.opensearch_use_ssl,
            verify_certs=settings.opensearch_verify_certs,
        )

        return OpenSearchImageLoader(client=client, image_cache_index=settings.opensearch_image_cache_index_name)


async def aggregations_access_check(request: Request) -> None:
    if not request.app.search_backend_settings.enable_aggregations:
        raise HTTPException(status_code=403, detail="Forbidden: Aggregations are disabled")


async def vlm_validator(request: Request) -> Optional[SearchResultValidator]:
    """Get the VLM validator from app state if available."""
    if hasattr(request.app, "vlm_validator"):
        return request.app.vlm_validator
    return None
