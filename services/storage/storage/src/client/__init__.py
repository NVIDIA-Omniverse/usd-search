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

# standard modules
from typing import Any, AsyncIterator, Dict, Optional

from storage.src.config import AssetDBConfig as service_Config
from storage.src.models import (
    ExistsStatus,
    LivezResponse,
    ReadyzResponse,
    Result,
    SizeResponse,
    Status,
)
from storage.src.services.config import NGSearchStorageSearchBackendConfig
from storage.src.services.ngsearch_storage_service import (
    NGSearchStorage as NGSearchStorageService,
)

# local / proprietary modules
from typing_extensions import NotRequired, TypedDict

from search_utils.storage_client.config import StorageClientConfig, StorageConfig


class BackendUnavailable(ConnectionError):
    pass


class ReducerUnavailable(ValueError):
    pass


class IncorrectItemKey(ValueError):
    pass


class StorageClientInput(TypedDict):
    key: NotRequired[str]
    key_hash: NotRequired[str]
    raw: NotRequired[bool]
    meta: NotRequired[Dict[str, str]]
    values: NotRequired[Dict[str, Any]]


class StorageClientUpdateInput(TypedDict):
    update_dict: NotRequired[Dict[str, Dict[str, Any]]]
    update_dict_hashed_keys: NotRequired[Dict[str, Dict[str, Any]]]


class StorageCLientDataTypeInput(TypedDict):
    data_type: NotRequired[str]


def assert_status_ok(response: Result) -> None:
    assert response.status == Status.ok, response.status


class NGSearchStorageHelper:
    def __init__(self, client: NGSearchStorageService) -> None:
        self.client: NGSearchStorageService = client

    async def add_item(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.add_item(dict(input), backend_name=backend_name))

    async def update_item(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.update_item(dict(input), backend_name=backend_name))

    async def update(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.update(dict(input), backend_name=backend_name))

    async def get_item(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.get_item(dict(input), backend_name=backend_name))

    async def remove_item(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.remove_item(dict(input), backend_name=backend_name))

    async def get_meta(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.get_meta(dict(input), backend_name=backend_name))

    async def update_meta(self, input: StorageClientInput, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.update_meta(dict(input), backend_name=backend_name))

    async def update_items(self, input: dict = {}, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.update_items(dict(input), backend_name=backend_name))

    async def get_keys(self, input: dict = {}, backend_name: Optional[str] = None) -> Result:
        return self.process_response(await self.client.get_keys(dict(input), backend_name=backend_name))

    async def get_keys_for_datatype(
        self, input: StorageCLientDataTypeInput = {}, backend_name: Optional[str] = None
    ) -> Result:
        return self.process_response(await self.client.get_keys_for_datatype(dict(input), backend_name=backend_name))

    async def demo_test(self, input: str):
        return await self.client.demo_test(input)

    async def get_keys_iter(self, input: dict = {}) -> AsyncIterator[Result]:
        async for it in self.client.get_keys_iter(dict(input)):
            yield self.process_response(it)

    async def get_keys_for_datatype_iter(self, input: StorageCLientDataTypeInput = {}) -> AsyncIterator[Result]:
        async for it in self.client.get_keys_for_datatype_iter(dict(input)):
            yield self.process_response(it)

    @staticmethod
    def process_response(response: Result) -> Result:
        if response.status == Status.key_missing:
            raise KeyError(response.data)
        elif response.status == Status.backend_unavailable:
            raise BackendUnavailable("Storage Backend unavailable")
        elif response.status == Status.type_error:
            raise TypeError(response.data)
        elif response.status == Status.reducer_unavailable:
            raise ReducerUnavailable(f"Requested projection is unavailable: {response.data}")
        elif response.status == Status.invalid_item_key:
            raise IncorrectItemKey(response.data)
        elif response.status == Status.error:
            raise Exception(response.data)
        elif response.status == Status.backend_is_not_provided:
            raise ValueError("backend is not provided")
        elif response.status == Status.requested_backend_unavailable:
            raise ValueError(response.data)

        # make sure response status is Ok
        assert_status_ok(response)

        return response

    async def exists(self, keys: list, backend_name: Optional[str] = None) -> ExistsStatus:
        response: ExistsStatus = await self.client.exists(keys=keys, backend_name=backend_name)
        if response.status != Status.ok:
            raise ValueError(f"Status check failed: {response.status}")
        return response

    async def size(self):
        response: SizeResponse = await self.client.size()
        return SizeResponse(status=response.status, size=int(response.size))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        pass

    async def livez(self) -> LivezResponse:
        return await self.client.livez()

    async def readyz(self) -> ReadyzResponse:
        return await self.client.readyz()


class NGSearchStorageClient:
    @staticmethod
    async def get_service(
        search_backend_config: Optional[NGSearchStorageSearchBackendConfig] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        use_prom_metrics: bool = False,
        use_cron_type_jobs: bool = False,
        config: service_Config = service_Config,
    ) -> NGSearchStorageHelper:
        service = NGSearchStorageService(
            config=config,
            search_backend_config=search_backend_config,
            storage_config=storage_config,
            storage_client_config=storage_client_config,
            use_prom_metrics=use_prom_metrics,
            use_cron_type_jobs=use_cron_type_jobs,
        )
        await service.backend_ready.wait()
        return NGSearchStorageHelper(service)
