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

# standard modules
import sys
import time
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)
from unittest import mock

# third party modules
import elasticsearch
from ngsearch_backend.opensearchpy_patches import patch_opensearchpy_client
from opensearchpy.exceptions import NotFoundError
from pydantic import BaseModel, Field

from search_utils.cache_utils.elasticsearch import NestedMetaESCacheDict
from search_utils.cache_utils.redis import CacheDictRedis

# local / proprietary modules
# Patch opensearchpy client
from search_utils.log_utils import print_wrapper
from search_utils.log_utils import setup_logging_from_yaml as setup_logging
from search_utils.misc_utils import get_percentage_string, tqdm_mock
from search_utils.omni_microservice import AssetdbMSWithCron
from search_utils.prometheus_utils import GenericPublisher
from search_utils.storage_client import (
    AvailableStorageClients,
    PathType,
    RemoteFileUri,
    StorageClient,
    get_client,
)
from search_utils.storage_client.config import StorageClientConfig, StorageConfig

from ..config import AssetDBConfig as service_Config
from ..models import (
    DataContent,
    ExistsStatus,
    LivezResponse,
    ReadyzResponse,
    Result,
    SizeResponse,
    Status,
)
from .config import (
    NGSearchStorageSearchBackendConfig,
    SearchBackendConfig,
    SearchBackendType,
)
from .exceptions import (
    BackendIsNotProvided,
    RequestedBackendUnavailable,
    UnsupportedURI,
)

patch_opensearchpy_client()

from search_utils.cache_utils.opensearch import NestedMetaOSCacheDict

# mock tqdm module

tmock = mock.Mock()
tmock.tqdm = tqdm_mock
sys.modules["tqdm.auto"] = tmock


# storage service
idl_logger = logging.getLogger(__name__)

setup_logging()


class ProcessedInput(BaseModel):
    key: Optional[str] = Field(default=None, description="item key")
    key_hash: Optional[str] = Field(default=None, description="hashed item key")
    values: Optional[dict] = Field(default=None, description="item content")
    meta: Optional[dict] = Field(default=None, description="item metadata")
    update_dict: Optional[Dict[str, dict]] = Field(default=None, description="update content")
    update_dict_hashed_keys: Optional[Dict[str, dict]] = Field(
        default=None, description="update content with hashed keys"
    )
    raw: Optional[bool] = Field(default=None, description="trigger to return raw data")
    skip_storage: Optional[bool] = Field(default=None, description="trigger to skip storage processing")
    metadata_key_list: Optional[List[str]] = Field(
        default=None, description="list of metadata fields that need to be returned"
    )
    max_requests: Optional[int] = Field(default=None, description="maximum number of results returned")
    batch_mode: Optional[bool] = Field(default=None, description="trigger to return results in batches")
    data_type: Optional[str] = Field(default=None, description="data field type")
    base_key_filter: Optional[str] = Field(default=None, description="filter returned items by base_key field")
    regexp: Optional[str] = Field(default=None, description="regular expression-based item filter")
    kw_must: Optional[List[str]] = Field(default=None, description="list of keywords that must be included")
    kw_must_not: Optional[List[str]] = Field(default=None, description="list of keywords that must be excluded")


class _NoOpTransport:
    async def close(self) -> None:
        pass


class NGSearchStorage(AssetdbMSWithCron):
    def __init__(
        self,
        config: service_Config = service_Config,
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        use_prom_metrics: bool = True,
        use_cron_type_jobs: bool = True,
        **kwargs,
    ) -> None:
        self.backend_ready = asyncio.Event()
        if search_backend_config is None:
            self._search_backend_config = NGSearchStorageSearchBackendConfig()
        else:
            self._search_backend_config = search_backend_config

        for backend_name, _backend in self._search_backend_config.backends.items():
            if not isinstance(
                self._search_backend_config.backends[backend_name]["search_backend_config"],
                SearchBackendConfig,
            ):
                self._search_backend_config.backends[backend_name]["search_backend_config"] = (
                    SearchBackendConfig.model_construct(**_backend["search_backend_config"])
                )

        self.es_cache: Dict[str, Union[NestedMetaESCacheDict, NestedMetaOSCacheDict]] = {}
        self._es_listing_task: Optional[asyncio.Task] = None

        loop = asyncio.get_event_loop()
        # define some regular jobs
        job_mapping = {
            "es-cache-actualization": {
                "task": self.es_cache_actualization,
                "timeout": config.es_cache_actualization_timeout,
            },
            "nucleus-data-verification": {
                "task": self.es_cache_nucleus_verification,
                "timeout": config.es_cache_nucleus_verification_timeout,
            },
        }
        # initialize prometheus metrics and jobs running at regular intervals
        super().__init__(
            config=config,
            redis_url=config.redis_url,
            redis_db_assetdbms=5,
            redis_db_cron=9,
            log_name="NGSearch storage",
            use_prom_metrics=use_prom_metrics,
            use_cron_type_jobs=use_cron_type_jobs,
            cron_job_mapping=job_mapping,
            connection_names=["verification"],
            storage_config=storage_config,
            storage_client_config=storage_client_config,
            **kwargs,
        )
        if self.use_prom_metrics:
            # start prometheus server
            self.prom_metrics = GenericPublisher(port=self.config.prom_metrics_port, labels=self.prom_labels)
            # create task to export process metrics
            loop.create_task(self.process_metrics())
            # start prometheus server
            self.prom_metrics.start_server()
        # prepare system cache
        self.system_cache = CacheDictRedis(
            redis_url=config.redis_url,
            database=11,
        )
        # backend initialization task
        self.es_init_task = loop.create_task(self.initialize_es_cache())

        # get storage client definition
        self.client: StorageClient = get_client(
            client_type=self.storage_config.storage_backend_type,
            config=self.storage_client_config,
        )

    async def cleanup(self):
        # close all storage backends
        for _cache in self.es_cache.values():
            await _cache.close()

    @property
    def transport(self) -> _NoOpTransport:
        return _NoOpTransport()

    @property
    def is_ready(self):
        return self.backend_ready.is_set()

    async def livez(self) -> LivezResponse:
        return LivezResponse(live=True)

    async def readyz(self) -> ReadyzResponse:
        return ReadyzResponse(ready=self.is_ready)

    async def demo_test(self, input: Optional[str] = None) -> DataContent:
        """Test that the IDL service is working."""
        idl_logger.debug("Input: %s", input)
        return DataContent(data=f"received: {input}")

    async def add_item(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_setitem", backend_name=backend_name)

    async def remove_item(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_delitem", backend_name=backend_name)

    async def update(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_update", backend_name=backend_name)

    async def update_item(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_updateitem", backend_name=backend_name)

    async def update_items(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_updateitems", backend_name=backend_name)

    async def update_meta(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_update_meta", backend_name=backend_name)

    async def get_item(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_getitem", backend_name=backend_name)

    async def get_meta(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_getmeta", backend_name=backend_name)

    async def get_keys(self, input: dict, backend_name: Optional[str] = None) -> Result:
        await self.backend_ready.wait()
        return await self.es_action(input, "async_keys", backend_name=backend_name)

    async def get_keys_iter(self, input: dict, backend_name: Optional[str] = None) -> AsyncIterator[Result]:
        await self.backend_ready.wait()
        try:
            cache = self.get_search_backend(backend_name=backend_name)
            async for it in self.es_gen_action(input, cache.async_keys_iter, batch_mode=True):
                yield it
        except BackendIsNotProvided:
            yield Result(status=Status.backend_is_not_provided)
        except RequestedBackendUnavailable as exc_info:
            yield Result(status=Status.requested_backend_unavailable, data=str(exc_info))

    async def get_keys_for_datatype(self, input: dict, backend_name: Optional[str] = None) -> Result:
        return await self.es_action(input, "async_get_keys_for_datatype", backend_name=backend_name)

    async def get_keys_for_datatype_iter(
        self, input: dict, backend_name: Optional[str] = None
    ) -> AsyncIterator[Result]:
        await self.backend_ready.wait()
        try:
            cache = self.get_search_backend(backend_name=backend_name)
            async for it in self.es_gen_action(input, cache.async_get_keys_for_datatype_iter, batch_mode=True):
                yield it
        except BackendIsNotProvided:
            yield Result(status=Status.backend_is_not_provided)
        except RequestedBackendUnavailable as exc_info:
            yield Result(status=Status.requested_backend_unavailable, data=str(exc_info))

    def get_backend_name_from_uri(self, uri: RemoteFileUri) -> Optional[str]:
        return None

    def get_uris_per_backend(self, batch: List[RemoteFileUri]) -> Dict[Optional[str], List[RemoteFileUri]]:
        output: Dict[Optional[str], List[RemoteFileUri]] = {}
        for uri in batch:
            backend_name: Optional[str] = self.get_backend_name_from_uri(uri=uri)
            if backend_name not in output:
                output[backend_name] = []
            output[backend_name].append(uri)

        return output

    async def exists(self, keys: List[str], backend_name: Optional[str] = None) -> ExistsStatus:
        try:
            await self.backend_ready.wait()
            if backend_name is None:
                uris_backend_mapping = self.get_uris_per_backend(batch=keys)
                response_list: List[List[bool]] = await asyncio.gather(
                    *[
                        self.get_search_backend(backend_name=backend_name).exists_async(uri_list)
                        for backend_name, uri_list in uris_backend_mapping.items()
                    ]
                )
                uri_to_existence_mapping: Dict[str, bool] = {}
                for backend_name, response_list_item in zip(uris_backend_mapping.keys(), response_list):
                    for uri, exists in zip(uris_backend_mapping[backend_name], response_list_item):
                        uri_to_existence_mapping[uri] = exists
                return ExistsStatus(exists=[uri_to_existence_mapping[k] for k in keys], status=Status.ok)
            else:
                cache = self.get_search_backend(backend_name=backend_name)
                return ExistsStatus(exists=await cache.exists_async(keys), status=Status.ok)
        except BackendIsNotProvided:
            return Result(status=Status.backend_is_not_provided)
        except RequestedBackendUnavailable as exc_info:
            return Result(
                status=Status.requested_backend_unavailable,
                data=str(exc_info),
                compression=None,
            )
        except Exception as e:
            idl_logger.exception(e)
            return ExistsStatus(status=Status.error)

    async def size(self) -> SizeResponse:
        try:
            await self.backend_ready.wait()
            return SizeResponse(
                size=sum([len(_cache) for _cache in self.es_cache.values()]),
                status=Status.ok,
            )
        except Exception as e:
            idl_logger.exception(e)
            return SizeResponse(size=0, status=Status.error)

    def check_item_key(self, key: str):
        return self.client.is_valid_uri(key)

    async def es_action(
        self,
        input: dict,
        action: Callable[..., Awaitable[Optional[Union[str, dict]]]],
        backend_name: Optional[str] = None,
    ) -> Result:
        await self.backend_ready.wait()
        content = ProcessedInput.model_construct(**input)

        if content.key is not None and content.key_hash is not None:
            raise ValueError("Can not use both 'key' and 'key_hash'")

        if content.update_dict is not None and content.update_dict_hashed_keys is not None:
            raise ValueError("Can not use both 'update_dict' and 'update_dict_hashed_keys'")

        if content.key is not None:
            if not self.check_item_key(content.key):
                msg = f"Request to update item has incorrect key: {content.key} ({self.config.omni_server})"
                idl_logger.warning(msg)
                return Result(data=msg, status=Status.invalid_item_key)
        if content.update_dict is not None:
            for key in content.update_dict.keys():
                if not self.check_item_key(key):
                    msg = f"Request to bulk update has incorrect key: {key} ({self.config.omni_server})"
                    idl_logger.warning(msg)
                    return Result(data=msg, status=Status.invalid_item_key)

        try:
            cache = self.get_search_backend(backend_name=backend_name)
            response = await getattr(cache, action)(**content.model_dump(exclude_none=True))
            status = Status.ok

        except BackendIsNotProvided:
            return Result(status=Status.backend_is_not_provided)
        except RequestedBackendUnavailable as exc_info:
            return Result(status=Status.requested_backend_unavailable, data=str(exc_info))
        except KeyError:
            response = content.key
            status = Status.key_missing
        except (
            elasticsearch.exceptions.ConnectionError,
            elasticsearch.exceptions.TransportError,
            elasticsearch.exceptions.ConnectionTimeout,
        ):
            loop = asyncio.get_event_loop()
            self.es_init_task = loop.create_task(self.initialize_es_cache())
            response = None
            status = Status.backend_unavailable
        except NotFoundError as exc_info:
            response = str(exc_info)
            status = Status.invalid_item_key
            idl_logger.warning(exc_info)
        except TypeError as e:
            response = str(e)
            status = Status.type_error
            idl_logger.exception(e)

        return Result(data=response, status=status)

    async def es_gen_action(self, input: dict, action: AsyncIterator, **kwargs):
        await self.backend_ready.wait()
        content = ProcessedInput.model_construct(**input)
        idl_logger.info(content)

        if content.key is not None:
            if not self.check_item_key(content.key):
                msg = f"Request to update item has incorrect key: {content.key}"
                idl_logger.warning(msg)
                yield Result(data=msg, status=Status.invalid_item_key)
                return

        if content.update_dict is not None:
            for key in content.update_dict.keys():
                if not self.check_item_key(key):
                    msg = f"Request to bulk update has incorrect key: {key}"
                    idl_logger.warning(msg)
                    yield Result(data=msg, status=Status.invalid_item_key)
                    return

        kwargs.update(**content.model_dump(exclude_none=True))
        try:
            async for it in action(**kwargs):
                yield Result(data=it, status=Status.ok)

        except KeyError:
            yield Result(data=content.key, status=Status.key_missing)
        except (
            elasticsearch.exceptions.ConnectionError,
            elasticsearch.exceptions.TransportError,
            elasticsearch.exceptions.ConnectionTimeout,
        ):
            loop = asyncio.get_event_loop()
            self.es_init_task = loop.create_task(self.initialize_es_cache())
            yield Result(status=Status.backend_unavailable)
        except NotFoundError as exc_info:
            idl_logger.warning(exc_info)
            yield Result(data=str(exc_info), status=Status.invalid_item_key)
        except TypeError as e:
            idl_logger.exception(e)
            yield Result(data=str(e), status=Status.type_error)

    def get_search_backend(
        self, backend_name: Optional[str] = None
    ) -> Union[NestedMetaOSCacheDict, NestedMetaESCacheDict]:
        if len(self.es_cache) == 0:
            raise ValueError("Empty set of backends")
        if len(self.es_cache) == 1:
            return list(self.es_cache.values())[0]

        raise ValueError(
            "Configuration error: single storage backend type "
            f"({self.storage_config.storage_backend_type}) with "
            f"multiple search backends: {self._search_backend_config}"
        )

    async def initialize_es_cache(self) -> None:
        # make sure mutex is defined
        initialized = False
        self.backend_ready.clear()
        while not initialized:
            try:
                for (
                    backend_name,
                    _backend,
                ) in self._search_backend_config.backends.items():
                    if _backend["search_backend_config"].backend_type == SearchBackendType.es_index:
                        es_cache_backend = NestedMetaESCacheDict
                        idl_logger.info("Using ElasticSearch backend for: %s", backend_name)
                    elif _backend["search_backend_config"].backend_type == SearchBackendType.os_index:
                        es_cache_backend = NestedMetaOSCacheDict
                        idl_logger.info("Using OpenSearch backend for: %s", backend_name)
                    else:
                        raise NotImplementedError(
                            f"The selected backend {_backend['search_backend_config'].backend_type} is not supported"
                        )

                    idl_logger.info(_backend["search_backend_config"])

                    self.es_cache[backend_name] = es_cache_backend(
                        host=_backend["search_backend_config"].host,
                        port=_backend["search_backend_config"].port,
                        name=_backend["search_backend_config"].name,
                        dim=_backend["search_backend_config"].dim,
                    )

                initialized = True
            except elasticsearch.exceptions.ConnectionError:
                idl_logger.warning("Elastic Search backend is unavailable")
                await asyncio.sleep(1)
            except Exception as e:
                idl_logger.exception(e)
                await asyncio.sleep(1)
        # notify that ES is ready
        self.backend_ready.set()

    async def es_cache_actualization(self) -> None:
        # make sure backend is initialized
        await self.backend_ready.wait()
        # log some info
        self.cron_logger.info(
            dict(
                message="storage actualization for ES engines",
                **{f"cache_{key}": cache.signature for key, cache in self.es_cache.items()},
            )
        )
        # running cache verification
        with print_wrapper("verifying backend", print_after=False, logger=self.cron_logger.info):
            for cache in self.es_cache.values():
                await cache.actualize_storage(
                    max_requests=self.config.es_cache_actualization_batch_size,
                    lock=None,
                )

    @staticmethod
    async def verify_assets_on_the_storage_backend(
        storage_client: StorageClient,
        url_list: List[str],
        cache_name: str,
        remove_unsupported_urls: bool = False,
    ) -> List[Tuple[Tuple[str, str], Tuple[bool, PathType]]]:
        """Verify a list of URLs against a storage client and construct a list of Tuples with missing files.

        if UnsupportedURI exception is raised during status check - mark this file as missing.

        Returns:
            List[Tuple[Tuple[str, str], Tuple[bool, PathType]]]: List of tuples with 1 element being a tuple: URL, backend; and 2 element being the existence check response
        """

        async def check_existence(url: str) -> Tuple[bool, Optional[PathType]]:
            if not storage_client.is_valid_uri(url):
                raise UnsupportedURI("Unsupported URL")
            return await storage_client.check_if_exists(url)

        results = await asyncio.gather(*[check_existence(url) for url in url_list], return_exceptions=True)

        # find non-existent files
        missing = []
        for r, k in zip(results, url_list):
            if isinstance(r, UnsupportedURI):
                idl_logger.warning("UnsupportedURI exception raised when processing: %s: %s", k, str(r))
                if remove_unsupported_urls:
                    missing.append((k, cache_name))
            elif isinstance(r, tuple):
                if not r[0]:
                    missing.append((k, cache_name))
            else:
                idl_logger.warning(f"Unsupported existence check response format: {r}")

        return (missing, results)

    async def es_cache_nucleus_verification(self, log_timeout: float = 30) -> None:
        # make sure backend is initialized
        await self.backend_ready.wait()
        # log some info
        self.cron_logger.info(
            dict(
                message="storage verification against Storage backend for ES engines",
                **{f"cache_{key}": cache.signature for key, cache in self.es_cache.items()},
            )
        )

        total_miss = 0
        total_processed = 0
        storage_size = sum([len(es_cache) for es_cache in self.es_cache.values()])
        queue = asyncio.Queue()
        es_listing_completed = asyncio.Event()
        bg = time.time()

        async def es_listing_task():
            bg = time.time()
            n_listed = 0
            for cache_name, cache in self.es_cache.items():
                async for it in cache.async_keys_iter(
                    max_requests=self.config.es_nucleus_verification_batch_size,
                    batch_mode=True,
                ):
                    url_list = []
                    for k in it:
                        url_list.append(
                            (await cache.async_getitem(key_hash=k, raw=True, skip_storage=True))["base_key"]
                        )
                    await queue.put((url_list, cache_name))
                    n_listed += len(it)
                    if time.time() - bg > log_timeout:
                        self.cron_logger.info(
                            "ES listing progress: %s",
                            get_percentage_string(n_listed, storage_size),
                        )
                        bg = time.time()
            # notify the main thread that the listing has finished
            es_listing_completed.set()

        # create es listing task
        loop = asyncio.get_event_loop()
        self._es_listing_task = loop.create_task(es_listing_task())

        try:
            # run main processing task and verify files in ES index
            storage_client: StorageClient
            async with self.client.connection_context() as storage_client:
                while not es_listing_completed.is_set() or queue.qsize() > 0:
                    content: Tuple[List[str], Union[NestedMetaESCacheDict, NestedMetaOSCacheDict]] = await queue.get()
                    url_list, cache_name = content
                    with print_wrapper(
                        "verifying files in the Storage Backend",
                        logger=self.cron_logger.debug,
                        print_after=False,
                    ):
                        missing, results = await self.verify_assets_on_the_storage_backend(
                            storage_client=storage_client,
                            url_list=url_list,
                            cache_name=cache_name,
                            remove_unsupported_urls=self.config.es_cache_nucleus_verification_remove_unsupported,
                        )

                    total_miss += len(missing)
                    total_processed += len(results)

                    while True:
                        try:
                            results = await asyncio.gather(
                                *[self.es_cache[cache_name].async_delitem(key=k) for k, cache_name in missing]
                            )
                            break
                        except elasticsearch.exceptions.ConnectionTimeout:
                            self.cron_logger.warning("ES timeout")
                            await asyncio.sleep(1)

                    if time.time() - bg > log_timeout:
                        self.cron_logger.info(
                            dict(
                                missing=get_percentage_string(total_miss, total_processed),
                                processed=get_percentage_string(total_processed, storage_size),
                            )
                        )
                        bg = time.time()
        finally:
            # cancel listing task on any exception to the main function loop
            if self._es_listing_task is not None and not self._es_listing_task.done():
                self._es_listing_task.cancel()

        # log final stats
        self.cron_logger.info(
            dict(
                message="Orphaned data stats",
                missing=get_percentage_string(total_miss, total_processed),
            )
        )
