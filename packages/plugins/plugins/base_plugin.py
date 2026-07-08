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
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple, TypeAlias

# third-party modules
import numpy as np

# local/proprietary modules
from cache.src import PluginItemStatus
from deepsearch_utils.ds_plugin_utils import GetFileResponse
from opentelemetry import trace
from pydantic_settings import BaseSettings

from search_utils.log_utils import set_simple_logger
from search_utils.storage_client import StorageClient

from .models import GenericPluginErrorItem, PluginProcessingResult

tracer = trace.get_tracer(__name__)

PLuginBatchItem: TypeAlias = dict[str, np.ndarray]


class BasePluginConfig(BaseSettings):
    active: bool = True
    use_embedding_client: bool = True
    # Max concurrent data-load operations across the worker's parallel queue
    # processors. None or <= 0 means unlimited. Set this to a small positive
    # integer for plugins that load large assets where uncontrolled parallelism
    # would exhaust memory.
    data_load_concurrency: Optional[int] = None


class BasePlugin(ABC):
    def __init__(
        self,
        plugin_name: str,
        data_types: list[str],
        render: bool,
        namespace: str,
        system_namespace: str,
        config: Optional[BasePluginConfig] = None,
    ):
        self.plugin_name = plugin_name
        self.data_types = data_types
        self.render = render
        self.namespace = namespace
        self.system_namespace = system_namespace
        self.logger = set_simple_logger(logger_name=plugin_name, loglevel="INFO")
        self._config = config if config else BasePluginConfig()
        self.active = self._config.active
        self._batch_data_field = "data"

    @property
    def batch_data_field(self) -> str:
        return self._batch_data_field

    @property
    def config(self) -> BasePluginConfig:
        return self._config

    def should_process(self, file_type: str) -> bool:
        """Check if file of this type can be processed by the plugin"""

        return "any" in self.data_types or file_type in self.data_types

    def load_data(
        self,
        omni_path: str,
        data: Optional[np.ndarray],
        status: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        if data is None:
            self.logger.debug("content for '%s' is not provided", omni_path)
            if status is not None:
                return {
                    "omni_path": omni_path,
                    "status": status,
                    "error_message": error_message,
                }
            return {"omni_path": omni_path}
        return {self.batch_data_field: data, "omni_path": omni_path}

    def get_omni_file(self) -> GetFileResponse:
        raise NotImplementedError

    def asset_state_hash(self, hash_value: str) -> str:
        return hash_value

    @abstractmethod
    def preprocess(
        self, data: list, batch_data_dict: dict, storage_clien: StorageClient
    ) -> Tuple[list, list, Dict[int, GenericPluginErrorItem]]:
        pass

    async def process(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        error_indices: Dict[int, GenericPluginErrorItem],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        with tracer.start_as_current_span(
            "plugin.process",
            attributes={
                "plugin.name": self.plugin_name,
                "plugin.batch_size": len(batch_data),
                "plugin.valid_count": len(indices),
                "plugin.error_count": len(error_indices),
            },
        ) as span:
            try:
                valid_results = await self.process_valid_items(
                    batch_data=batch_data,
                    indices=indices,
                    sample_ids=sample_ids,
                    **kwargs,
                )
                error_results = await self.process_failed_items(
                    error_indices=error_indices, sample_ids=sample_ids, **kwargs
                )
                combined = {**valid_results, **error_results}
                span.set_attribute("plugin.result_count", len(combined))
                return combined
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(trace.StatusCode.ERROR, str(exc))
                raise

    @abstractmethod
    async def process_valid_items(
        self,
        batch_data: list[PLuginBatchItem],
        indices: list[int],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        pass

    async def process_failed_items(
        self,
        error_indices: Dict[int, GenericPluginErrorItem],
        sample_ids: list[int],
        **kwargs,
    ) -> Dict[int, PluginProcessingResult]:
        return {
            sample_ids[error_index]: PluginProcessingResult(
                asset_status=PluginItemStatus(
                    status=error_item.status,
                    processing_timestamp=time.time(),
                    exception=error_item.error_message,
                ),
                search_backend_content={self.plugin_name: None},
            )
            for error_index, error_item in error_indices.items()
        }

    def clean_up(self):
        raise NotImplementedError
