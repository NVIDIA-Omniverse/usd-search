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

import os
from ast import literal_eval as make_tuple

# local/proprietary modules
from .log_utils import prepare_message
from .misc_utils import float_or_none, str2bool

config_file_loc = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))


class AssetDBConfig:
    """
    Configuration of the Inference service.
    """

    list_wild_card = os.getenv("OV_LIST_WILDCARD_INDEXING", "/*")  #: Path in Omniverse that the service is listening to
    omni_master_user = os.getenv("OV_USERNAME", "deeptag_service")  #: Name of the service user
    omni_master_password = os.getenv("OV_PASSWORD", "deeptag_service_password")  #: Password of the service user
    omni_server = os.getenv("OV_SERVER", "localhost")  #: Omniverse server that the service is connected to
    omni_service = os.getenv("OV_SERVICE", "deepsearch-tag-crawler")
    omni_instance = os.getenv("OV_INSTANCE", f"{omni_server}-instance")
    omni_port = os.getenv("OV_PORT", "3009")  #: Omniverse server port
    omni_connection_timeout = float(os.getenv("OV_CONN_TIMEOUT_S", "172800"))  #: Omniverse connection timeout
    ts_logging_level = os.getenv("OV_LOGGING_LEVEL", "INFO")  #: Service logging level
    db_path = os.getenv("ASSETDB_PATH", "/tmp/deepsearch")
    redis_url = os.getenv("REDIS_URL")
    omni_connection_ping = float(os.getenv("OV_CONN_PING_S", "20"))
    omni_list_idle_timeout = float(os.getenv("OMNI_LIST_IDLE_TIMEOUT", "24"))
    local_model_path = os.getenv(
        "LOCAL_MODEL_PATH", "/tmp/deepsearch/dlmodel"
    )  #: Location, where to store the model weights on the local machine

    list_batch_size = int(os.getenv("LIST_BATCH_SIZE", "2"))
    max_backlog_size = int(os.getenv("MAX_BACKLOG_SIZE", "512"))

    show_hidden = str2bool(os.getenv("SHOW_HIDDEN", "False"))
    file_formats = ["any"]

    prom_metrics_port = int(os.getenv("PROM_METRICS_PORT", "8000"))  #: port where prometheus metrics are published
    prom_system_metrics_timeout = float(os.getenv("PROM_SYSTEM_METRICS_TIMEOUT", "5"))

    tag_probe_timeout = float(os.getenv("TAG_PROBE_TIMEOUT", "600"))
    tag_probe_uri = os.getenv("TAG_PROBE_URI", f"/Users/{omni_master_user}/system/tag_probe.txt")

    listing_timeout = float_or_none(
        os.getenv("OMNI_PATH_LIST_TIMEOUT", "None")
    )  #: Timeout for listing a path in omniverse (non-recursive)
    rescan_timeout = float(os.getenv("RESCAN_TIMEOUT", "-1"))  #: Number of hours between the two full rescans
    exclude_uri_substrings = make_tuple(os.getenv("OV_EXCLUDE_PATHS_INDEXING", '["/.thumbs/", ".__omni_channel__"]'))

    items_queue_size = int(os.getenv("ITEMS_QUEUE_SIZE", "0"))

    local_cache_actualization_timeout = float(
        os.getenv("LOCAL_CACHE_ACTUALIZATION_TIMEOUT", "86400")
    )  # default is one day in seconds

    # client
    ngsearch_storage_host = os.getenv("NGSEARCH_STORAGE_HOST", "localhost")
    ngsearch_storage_port = int(os.getenv("NGSEARCH_STORAGE_PORT", "3703"))

    @staticmethod
    def to_string():
        """Print configuration parameters to :func:`sys.stdout`."""

        message = prepare_message(
            msg="Omniverse",
            item_list=[
                f"Omniverse Server:                {AssetDBConfig.omni_server}:{AssetDBConfig.omni_port}",
                f"Service name:                    {AssetDBConfig.omni_service}",
                f"Service instance:                {AssetDBConfig.omni_instance}",
                f"Omniverse User:                  {AssetDBConfig.omni_master_user}",
                f"List Wild Card:                  {AssetDBConfig.list_wild_card}",
                f"Excluded string patterns:        {AssetDBConfig.exclude_uri_substrings}",
                f"Show hidden:                     {AssetDBConfig.show_hidden}",
            ],
        )
        message += prepare_message(
            msg="Timeouts",
            item_list=[
                f"Connection timeout (s):          {AssetDBConfig.omni_connection_timeout}",
                f"Path listing timeout:            {AssetDBConfig.listing_timeout}",
                f"Full rescan timeout (h):         {AssetDBConfig.rescan_timeout}",
                f"Cache actualization timeout (s): {AssetDBConfig.local_cache_actualization_timeout}",
                f"Tag probe timeout (s):           {AssetDBConfig.tag_probe_timeout}",
            ],
        )
        message += prepare_message(
            msg="Cache and Queue",
            item_list=[
                f"Items Queue size:                {AssetDBConfig.items_queue_size}",
                f"Prometheus metrics port:         {AssetDBConfig.prom_metrics_port}",
                f"Max backlog size:                {AssetDBConfig.max_backlog_size}",
            ],
        )
        message += prepare_message(
            msg="Logging",
            item_list=[
                f"Omniverse utils logging level:   {os.getenv('OMNIVERSE_UTILS_LOGLEVEL', 'INFO')}",
                f"Tagging utils logging level:     {os.getenv('TAG_UTILS_LOGLEVEL', 'INFO')}",
                f"Socket logging level:            {os.getenv('SOCKET_LOGGER_LOGLEVEL', 'INFO')}",
                f"Liveness probe logging level:    {os.getenv('LIVENESS_PROBE_LOGLEVEL', 'INFO')}",
                f"DateTime utils logging level:    {os.getenv('DATETIME_UTILS_LOGLEVEL', 'INFO')}",
                f"Generic imports logging level:   {os.getenv('GENERIC_LOGLEVEL', 'INFO')}",
            ],
        )
        message += prepare_message(
            msg="Storage service",
            item_list=[
                f"host:                             {AssetDBConfig.ngsearch_storage_host}",
                f"port:                             {AssetDBConfig.ngsearch_storage_port}",
            ],
        )
        return message
