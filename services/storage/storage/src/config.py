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

# standard imports
import os

# third party modules
from idl.service.config.deployments import (
    DeploymentConfig,
    DeploymentFile,
    DeploymentString,
)

# local/proprietary modules
from search_utils.log_utils import prepare_message
from search_utils.misc_utils import str2bool

# get config path location
config_file_loc = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))


class AssetDBConfig:
    """
    Configuration of the Inference service.
    """

    list_wild_card = os.getenv("OV_LIST_WILDCARD_INDEXING", "/")  #: Path in Omniverse that the service is listening to
    omni_master_user = os.getenv("OV_USERNAME", "deeptag_service")  #: Name of the service user
    omni_master_password = os.getenv("OV_PASSWORD", "deeptag_service_password")  #: Password of the service user
    omni_server = os.getenv("OV_SERVER", "localhost")  #: Omniverse server that the service is connected to
    omni_service = os.getenv("OV_SERVICE", "ngsearch-storage")
    omni_instance = os.getenv("OV_INSTANCE", f"{omni_server}-instance")
    omni_port = os.getenv("OV_PORT", "3009")  #: Omniverse server port
    omni_connection_timeout = float(os.getenv("OV_CONN_TIMEOUT_S", "172800"))  #: Omniverse connection timeout
    ts_logging_level = os.getenv("OV_LOGGING_LEVEL", "INFO")  #: Service logging level
    omni_connection_ping = float(os.getenv("OV_CONN_PING_S", "20"))

    backend_type = os.getenv("BACKEND_TYPE", "es_index")  # Backend type - es_index or os_index
    es_host = os.getenv("ES_HOST", "localhost")  # IP of ES engine endpoint
    es_port = int(os.getenv("ES_PORT", "9200"))  # IP of ES engine endpoint
    es_name = os.getenv("ES_NAME", "clip-embedding")  # name that is used to form ES index
    ds_embedding_dim = int(os.getenv("DS_EMBEDDING_DIM", "1536"))  # name that is used to form ES index
    es_cache_actualization_timeout = float(os.getenv("ES_CACHE_ACTUALIZATION_TIMEOUT", "86400"))  # default is one day
    es_cache_actualization_batch_size = float(
        os.getenv("ES_CACHE_ACTUALIZATION_BATCH_SIZE", "512")
    )  # default is one day
    es_cache_nucleus_verification_timeout = float(
        os.getenv("ES_CACHE_NUCLEUS_VERIFICATION_TIMEOUT", "86400")
    )  # default is one day
    es_cache_nucleus_verification_remove_unsupported = str2bool(
        os.getenv("ES_CACHE_NUCLEUS_VERIFICATION_REMOVE_UNSUPPORTED", "False")
    )

    es_nucleus_verification_batch_size = int(os.getenv("ES_NUCLEUS_VERIFICATION_BATCH_SIZE", "256"))
    es_update_batch = int(os.getenv("ES_UPDATE_BATCH", "1"))  #: batch size for updating ES engine

    prom_metrics_port = int(os.getenv("PROM_METRICS_PORT", "8007"))  #: port where prometheus metrics are published

    prom_system_metrics_timeout = float(os.getenv("PROM_SYSTEM_METRICS_TIMEOUT", "5"))
    db_path = os.getenv("ASSETDB_PATH")
    redis_url = os.getenv("REDIS_URL")
    cache_version = float(os.getenv("CACHE_VERSION", "4.0"))

    @staticmethod
    def get_deployment_config() -> DeploymentConfig:
        deployments_str = DeploymentString("NGSEARCH_STORAGE_SERVICE_DEPLOYMENTS").read()
        if deployments_str:
            return deployments_str

        deployments_file = DeploymentFile(
            "NGSEARCH_STORAGE_SERVICE_DEPLOYMENTS_FILE",
            default=f"{config_file_loc}/configuration/deployment.yaml",
        ).read()

        if deployments_file:
            return deployments_file

    @staticmethod
    def to_string():
        """Print configuration parameters to :func:`sys.stdout`."""

        message = prepare_message(
            msg="Omniverse",
            item_list=[
                f"Omniverse Server:                   {AssetDBConfig.omni_server}:{AssetDBConfig.omni_port}",
                f"Service name:                       {AssetDBConfig.omni_service}",
                f"Service instance:                   {AssetDBConfig.omni_instance}",
                f"Omniverse User:                     {AssetDBConfig.omni_master_user}",
                f"List Wild Card:                     {AssetDBConfig.list_wild_card}",
            ],
        )
        message += prepare_message(
            msg="Elastic Search configuration",
            item_list=[
                f"host:                               {AssetDBConfig.es_host}",
                f"port:                               {AssetDBConfig.es_port}",
                f"name:                               {AssetDBConfig.es_name}",
                f"update batch size:                  {AssetDBConfig.es_update_batch}",
                f"nucleus verification batch size:    {AssetDBConfig.es_nucleus_verification_batch_size}",
            ],
        )
        message += prepare_message(
            msg="Timeouts",
            item_list=[
                f"Connection timeout (s):             {AssetDBConfig.omni_connection_timeout}",
                f"Cache actualization timeout:        {AssetDBConfig.es_cache_actualization_timeout}",
                f"Cache nucleus verification timeout: {AssetDBConfig.es_cache_nucleus_verification_timeout}",
                f"Metrics refresh timeout:            {AssetDBConfig.prom_system_metrics_timeout}",
            ],
        )
        message += prepare_message(
            msg="Cache and Queue",
            item_list=[
                f"Prometheus metrics port:            {AssetDBConfig.prom_metrics_port}",
                f"DB path:                            {AssetDBConfig.db_path}",
                f"Cache version:                      {AssetDBConfig.cache_version}",
            ],
        )
        message += prepare_message(
            msg="Logging",
            item_list=[
                f"Omniverse utils logging level:      {os.getenv('OMNIVERSE_UTILS_LOGLEVEL', 'INFO')}",
                f"Tagging utils logging level:        {os.getenv('TAG_UTILS_LOGLEVEL', 'INFO')}",
                f"Socket logging level:               {os.getenv('SOCKET_LOGGER_LOGLEVEL', 'INFO')}",
                f"Liveness probe logging level:       {os.getenv('LIVENESS_PROBE_LOGLEVEL', 'INFO')}",
                f"DateTime utils logging level:       {os.getenv('DATETIME_UTILS_LOGLEVEL', 'INFO')}",
                f"NGSearch storage logging level:     {os.getenv('IDL_LOG_LEVEL', 'INFO')}",
                f"Generic imports logging level:      {os.getenv('GENERIC_LOGLEVEL', 'INFO')}",
            ],
        )
        return message
