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
from typing import List, Optional, TypeVar

from cache.src import GenericPluginStatus
from fire import Fire

from search_utils.storage_client import (
    AvailableStorageClients,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageConfig
from search_utils.storage_client.nucleus.config import NucleusStorageConfig
from search_utils.storage_client.s3.config import S3StorageClientConfig

from .ls import ls
from .reindex import main as reindex_main

T = TypeVar("T")


class AdminTools:
    def __init__(
        self,
        client_type: Optional[AvailableStorageClients] = None,
        bucket_name: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        ov_server: Optional[str] = None,
        ov_username: Optional[str] = None,
        ov_password: Optional[str] = None,
    ):
        """Admin CLI for managing assets in the usdsearch storage system.

        Args:
            client_type: Storage backend type (s3 or nucleus). Defaults to env-configured value.
            bucket_name: S3 bucket name.
            region_name: AWS region name.
            aws_access_key_id: AWS access key ID.
            aws_secret_access_key: AWS secret access key.
            ov_server: Nucleus server URL.
            ov_username: Nucleus username.
            ov_password: Nucleus password.
        """
        self.client_type = client_type
        if self.client_type is None:
            self.client_type = StorageConfig().storage_backend_type

        self._storage_client_config = None
        self._storage_client = None
        self._auth_kwargs = {
            "bucket_name": bucket_name,
            "region_name": region_name,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
            "ov_server": ov_server,
            "ov_username": ov_username,
            "ov_password": ov_password,
        }

    @property
    def storage_client_config(self) -> Optional[StorageConfig]:
        if self._storage_client_config is not None:
            return self._storage_client_config

        _config = None
        if self.client_type == AvailableStorageClients.s3:
            kwargs = {
                k: v
                for k, v in {
                    "bucket_name": self._auth_kwargs["bucket_name"],
                    "region_name": self._auth_kwargs["region_name"],
                    "aws_access_key_id": self._auth_kwargs["aws_access_key_id"],
                    "aws_secret_access_key": self._auth_kwargs["aws_secret_access_key"],
                }.items()
                if v is not None
            }
            _config = S3StorageClientConfig(**kwargs)
        elif self.client_type == AvailableStorageClients.nucleus:
            nucleus_auth = {
                k: v
                for k, v in {
                    "ov_username": self._auth_kwargs["ov_username"],
                    "ov_password": self._auth_kwargs["ov_password"],
                }.items()
                if v is not None
            }
            kwargs = {}
            if self._auth_kwargs["ov_server"] is not None:
                kwargs["ov_server"] = self._auth_kwargs["ov_server"]
            if nucleus_auth:
                kwargs["auth"] = nucleus_auth
            _config = NucleusStorageConfig(**kwargs)

        self._storage_client_config = _config
        return self._storage_client_config

    @property
    def storage_client(self) -> StorageClient:
        if self._storage_client is not None:
            return self._storage_client
        self._storage_client: StorageClient = get_client(
            client_type=self.client_type, config=self.storage_client_config
        )
        return self._storage_client

    def cache(
        self,
        redis_url: Optional[str] = None,
        stream_name_prefix: Optional[str] = None,
        cache_plugin_prefix: Optional[str] = None,
    ):
        """Admin utilities for inspecting and managing cache Redis streams.

        All parameters are optional; unset values fall back to RedisCacheConfig
        (reads REDIS_URL, CACHE_PLUGIN_PREFIX env vars or their defaults).

        Args:
            redis_url: Redis connection URL. Defaults to RedisCacheConfig.url.
            stream_name_prefix: Prefix shared by all cache streams. Defaults to RedisCacheConfig.stream_name_prefix.
            cache_plugin_prefix: Key prefix used for plugin result storage. Defaults to RedisCacheConfig.plugin_prefix.
        """
        from cache.src.client.config import RedisCacheConfig

        from .cache_tools import CacheTools

        config = RedisCacheConfig()
        return CacheTools(
            redis_url=redis_url or config.url,
            stream_name_prefix=stream_name_prefix or config.stream_name_prefix,
            cache_plugin_prefix=cache_plugin_prefix or config.plugin_prefix.decode(),
        )

    def ls(self, path: str, long_listing_format: bool = False, verbose: bool = False) -> None:
        """List assets at a given storage path.

        Args:
            path: The storage path to list (e.g. s3://bucket/prefix or omniverse://server/path).
            long_listing_format: Show creation date and size alongside each URI.
            verbose: Print each item as it is discovered.
        """
        asyncio.run(
            ls(
                storage_client=self.storage_client,
                path=path,
                long_listing_format=long_listing_format,
                verbose=verbose,
            )
        )

    def reindex(
        self,
        path: str,
        endpoint_url: str = "http://localhost:8000",
        asset_formats: Optional[List[str]] = None,
        exclude_file_patterns: Optional[List[str]] = None,
        include_statuses: Optional[List[GenericPluginStatus]] = None,
        exclude_statuses: Optional[List[GenericPluginStatus]] = [GenericPluginStatus.ok],
        include_plugins: Optional[List[str]] = None,
        num_parallel_api_calls: int = 10,
        dry_run: bool = False,
        output_file: Optional[str] = None,
        ignore_existing_statuses: bool = False,
        refresh_metadata: bool = True,
        refresh_tags: bool = False,
        refresh_plugins: bool = True,
    ) -> None:
        """Trigger reindexing of assets based on their current processing status.

        Args:
            path: Storage path to scan for assets.
            endpoint_url: URL of the info/processing endpoint. Defaults to http://localhost:8000.
            asset_formats: File extensions to include (e.g. ['usd', 'usda']). All formats if None.
            exclude_file_patterns: fnmatch patterns to exclude from the asset list.
            include_statuses: Only reindex assets with these statuses. All statuses if None.
            exclude_statuses: Skip assets with these statuses. Defaults to [ok].
            include_plugins: Limit reindexing to these plugin names. All plugins if None.
            num_parallel_api_calls: Maximum concurrent API calls. Defaults to 10.
            dry_run: Print assets that would be reindexed without triggering any processing.
            output_file: Write dry-run JSON output to this file path.
            ignore_existing_statuses: Reindex all assets regardless of current status.
            refresh_metadata: Refresh asset metadata during processing.
            refresh_tags: Refresh asset tags during processing.
            refresh_plugins: Re-enqueue plugin processing jobs.
        """
        return reindex_main(
            path=path,
            endpoint_url=endpoint_url,
            storage_client=self.storage_client,
            asset_formats=asset_formats,
            exclude_file_patterns=exclude_file_patterns,
            include_statuses=include_statuses,
            exclude_statuses=exclude_statuses,
            include_plugins=include_plugins,
            num_parallel_api_calls=num_parallel_api_calls,
            dry_run=dry_run,
            output_file=output_file,
            ignore_existing_statuses=ignore_existing_statuses,
            refresh_metadata=refresh_metadata,
            refresh_tags=refresh_tags,
            refresh_plugins=refresh_plugins,
        )


if __name__ == "__main__":
    Fire(AdminTools)
