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
from ast import literal_eval as make_tuple
from dataclasses import dataclass
from typing import Optional

# local/proprietary modules
from search_utils.log_utils import prepare_message
from search_utils.misc_utils import float_or_none, str2bool, str2dict

config_file_loc = os.path.abspath(os.path.dirname(os.path.realpath(__file__)))


@dataclass
class MonitorServiceConfig:
    external: Optional[bool] = None
    use_metrics: Optional[bool] = None
    metrics_port: Optional[int] = None
    batch_size: Optional[int] = None
    omni_service: str = "deepsearch-monitor"
    n_workers: Optional[int] = None


@dataclass
class AdditionalServicesConfig:
    cache: MonitorServiceConfig


class AssetDBConfig:
    """
    Configuration of the Inference service.
    """

    version = os.getenv("DEEPTAG_VERSION", "2.0.0")  # version of deeptag system

    list_wild_card = os.getenv("OV_LIST_WILDCARD", "/*")  #: Path in Omniverse that the service is listening to
    omni_master_user = os.getenv("OV_USERNAME", "deeptag_service")  #: Name of the service user
    omni_master_password = os.getenv("OV_PASSWORD", "deeptag_service_password")  #: Password of the service user
    omni_server = os.getenv("OV_SERVER", "localhost")  #: Omniverse server that the service is connected to
    omni_service = os.getenv("OV_SERVICE", "deepsearch-monitor")
    omni_instance = os.getenv("OV_INSTANCE", f"{omni_server}-instance")
    omni_port = os.getenv("OV_PORT", "3009")  #: Omniverse server port
    rebuild_predictions = str2bool(
        os.getenv("OV_REBUILD_PRED", "False")
    )  #: If set to ``True`` the service will rebuild all the asset predictions
    log_file_name = os.getenv("OV_LOGFILE", "create_assetproc.log")  # Name of the log file (not used by default)
    exclude_uri_substrings = make_tuple(
        os.getenv("OV_EXCLUDE_PATHS", '["/@", "/.tags/", "/.thumbs/", "/.system/"]')
    )  #: Set of patterns which define the paths that are excluded from processing
    # add deeeptag to excluded strings
    exclude_uri_substrings = tuple(list(exclude_uri_substrings) + ["/.deeptag/"])

    items_queue_size = int(os.getenv("ITEMS_QUEUE_SIZE", "0"))

    omni_connection_timeout = float(os.getenv("OV_CONN_TIMEOUT_S", "604800"))  #: Omniverse connection timeout (1 week)
    max_connection_retries = int(
        os.getenv("MAX_CONNECTION_RETRIES", "3")
    )  #: maximum number of times connection will be recreated
    omni_connection_ping = float(os.getenv("OV_CONN_PING_S", "20"))  #: Omniverse connection timeout
    omni_asset_load_timeout = float(
        os.getenv("OV_ASSET_LOAD_TIMEOUT_S", "120")
    )  #: Timeout for loading files from omniverse
    omni_tag_service_timeout = float(
        os.getenv("OV_TAG_SRV_TIMEOUT_S", "5")
    )  #: Tagging service response waiting timeout
    skip_omni_writes = str2bool(os.getenv("OV_SKIP_OMNI_WRITES", "False"))  # Skip pushing tags to the tagging service
    ts_logging_level = os.getenv("OV_LOGGING_LEVEL", "INFO")  #: Service logging level
    cap_size = int(
        os.getenv("OV_PRELOAD_CAP_MB", 512)
    )  #: Maximum number of MBytes that an asset can have (`Note`: only used by USD loader)
    cache_version = "2.0"  # version of cache that is used by the service
    es_cache_version = "3.0"  # version of ES index cache
    es_cache_actualization_timeout = float(os.getenv("ES_CACHE_ACTUALIZATION_TIMEOUT", "86400"))  # default is one day

    omni_config_file = os.getenv(
        "OMNI_CONFIG_FILE", "proc_service_config.json"
    )  #: name of the configuration file in omniverse

    cache_dir = os.getenv(
        "CACHE_DIR", "/tmp/pretrained/pytorch"
    )  #: Path to where the pretrained pytorch embeddings will be stored

    plugin_cache_in_memory_limit = int(os.getenv("PLUGIN_CACHE_IN_MEMORY_LIMIT", "50000"))
    plugin_cache_commit_delay = float(os.getenv("PLUGIN_CACHE_COMMIT_DELAY", "30"))

    fasttext_model = os.getenv(
        "FASTTEXT_MODEL", "/pretrained/pytorch/fasttext/cc.en.100.bin"
    )  #: Path to the location of the fasttext model

    # CPU-only task parameters
    batch_size = int(os.getenv("WORKER_BATCH_SIZE", "1"))
    cpu_queue_max_length = int(os.getenv("CPU_QUEUE_MAX_LENGTH", "0"))
    cpu_queue_num_workers = int(os.getenv("CPU_QUEUE_NUM_WORKERS", "4"))
    maxsize_event_queue = int(os.getenv("MAXSIZE_EVENT_QUEUE", "0"))
    maxsize_item_queue = int(os.getenv("MAXSIZE_ITEM_QUEUE", "0"))
    non_farm_queue_num_workers = int(os.getenv("NON_FARM_QUEUE_NUM_WORKERS", "4"))
    omni_event_queue_num_workers = int(os.getenv("OMNI_EVENT_QUEUE_NUM_WORKERS", "10"))
    max_request_per_second = float(os.getenv("MAX_REQUESTS_PER_SECOND", "2048"))

    # by default QUEUE_PATH is the same as DB_path - maybe we will need to make it different later
    #  These parametes are currently used just by the kubernetes service
    pers_queue_dlen = int(
        os.getenv("INFER_DLEN", "256")
    )  #: Number of elements that can be stored in the persistent queue before the processing microservice is triggered
    unique_fields = ["file_loc"]  #: unique field in persistent queue.
    infer_ip = os.getenv("INFER_IP", "0.0.0.0")  #: Ip where the websocket for data transfer is created
    infer_port = int(os.getenv("INFER_PORT", "5005"))  #: Websocket port
    infer_send_size = int(
        os.getenv("INFER_SEND_SIZE", "1")
    )  #: Number of elements that are sent over the websocket at once
    min_samples_per_job = int(
        os.getenv("MIN_SAMPLES_PER_JOB", "10")
    )  #: Number of elements that are required for a new job to be added
    infer_timeout = float(
        os.getenv("INFER_TIMEOUT", "3600")
    )  #: Number of seconds that the element can stay in the queue before being processed
    job_timeout = float(
        os.getenv("JOB_TIMEOUT", "3600")
    )  #: Maximum number of seconds waiting the inference job (default: 5 hours)
    n_inference_jobs = int(
        os.getenv("N_INFERENCE_JOBS", "1")
    )  #: number of inference jobs that are processing the batch
    inference_queue_batch_size = int(os.getenv("INFERENCE_QUEUE_BATCH_SIZE", "1"))

    default_model_path = os.getenv(
        "DEFAULT_MODEL_PATH", config_file_loc + "/package-links/dl_model/"
    )  #: Location, where the deafult model is stored
    infer_model_num_avg = int(
        os.getenv("INFER_MODEL_NUM_AVG", "5")
    )  # Number of samplings of the model for performance stability (used only by the mesh classification plugin)
    infer_model_num_pts = int(
        os.getenv("INFER_MODEL_NUM_PTS", "1536")
    )  # Number of points in the pointcloud for inference (used only by the mesh classification plugin)

    infer_model_check_delay = int(
        os.getenv("INFER_MODEL_CHECK_DELAY", "20")
    )  # This should be equal to ReScanOnIdleTimeout TODO: verify this and update
    rescan_timeout = float(os.getenv("RESCAN_TIMEOUT", "-1"))  #: Number of hours between the two full rescans

    usd_read_timeout = float(
        os.getenv("USD_READ_TIMEOUT", 120)
    )  #: if Usd cannot be loaded in this timeout seconds - skip it (used only by the USD loader)

    prom_metrics_port = int(os.getenv("PROM_METRICS_PORT", "8000"))  #: port where prometheus metrics are published
    prom_system_metrics_timeout = float(os.getenv("PROM_SYSTEM_METRICS_TIMEOUT", "5"))

    store_batch_data = str2bool(
        os.getenv("STORE_BATCH_DATA", "False")
    )  #: if True - store batch data that will be used for inference

    plugins_path = str(os.getenv("PLUGINS_PATH", f"{config_file_loc}/plugins"))  #: path to plugins
    plugins_config_path = str(
        os.getenv("PLUGINS_CONFIG_PATH", f"{config_file_loc}/configuration/plugin.config.yaml")
    )  #: path to plugin configuration file

    plugin_controllable_params = [
        "model_name",
        "classification_threshold",
    ]  #: plugin controllable parameters

    plugin_cache_context_enabled = str2bool(os.getenv("PLUGIN_CACHE_CONTEXT_ENABLED", "False"))

    system_namespace_prefix = os.getenv("SYSTEM_NAMESPACE_PREFIX", ".deeptag")  #: prefix of the system namespace

    require_farm = str2bool(os.getenv("REQUIRE_FARM", "True"))

    skip_same_hash = str2bool(
        os.getenv("SKIP_SAME_HASH", "False")
    )  #: skip re classifying samples coming from the same hash By default same hashed items are not skipped

    omni_mounts = str2dict(
        os.getenv("OMNI_MOUNT_DICT", {})
    )  #: dictionary with mount points and the respective rescane frequency in hours

    skip_mounts = False
    show_hidden = True

    cache_actualization_timeout = float(os.getenv("CACHE_ACTUALIZATION_TIMEOUT", "86400"))  #: 1 day (in seconds)

    omni_list_idle_timeout = float(
        os.getenv("OMNI_LIST_IDLE_TIMEOUT", "24")
    )  #: Timeout for service being IDLE on list subscription task (in hours)
    listing_timeout = float_or_none(
        os.getenv("OMNI_PATH_LIST_TIMEOUT", "None")
    )  #: Timeout for listing a path in omniverse (non-recursive)

    # IDL Inference API config
    idl_port = os.getenv("INFERENCE_API_IDL_PORT", "3504")
    idl_host = os.getenv("INFERENCE_API_IDL_HOST", "0.0.0.0")
    idl_pub_port = os.getenv("INFERENCE_API_IDL_PUBLIC_PORT", "3504")
    idl_pub_host = os.getenv("INFERENCE_API_IDL_PUBLIC_HOST", "0.0.0.0")
    use_discovery = os.getenv("USE_DISCOVERY", "True")
    path_blacklist = make_tuple(os.getenv("INFERENCE_API_RERUN_BLACKLIST", '["/", "/Users", "/Projects"]'))

    # omni farm set-up
    farm_queue_host = os.getenv("FARM_QUEUE_HOST", "0.0.0.0")
    farm_queue_port = os.getenv("FARM_QUEUE_PORT", "8222")
    farm_queue_protocol = os.getenv("FARM_QUEUE_PROTOCOL", "http")
    farm_ws_host = os.getenv("FARM_CLIENT_WS_HOST", "0.0.0.0")
    farm_ws_port = os.getenv("FARM_CLIENT_WS_PORT", "8765")
    farm_internal_ws_host = os.getenv("FARM_CLIENT_INTERNAL_WS_HOST", "0.0.0.0")
    farm_internal_ws_port = os.getenv("FARM_CLIENT_INTERNAL_WS_PORT", "8765")
    farm_ws_protocol = os.getenv("FARM_CLIENT_WS_PROTOCOL", "ws")
    farm_rendering_batch_size = int(os.getenv("FARM_CLIENT_RENDERING_BATCH_SIZE", "4"))
    farm_rendering_batch_timeout = float(os.getenv("FARM_CLIENT_RENDERING_BATCH_TIMEOUT", "5"))

    # service set-up
    services = AdditionalServicesConfig(
        cache=MonitorServiceConfig(
            external=str2bool(os.getenv("MONITOR_CACHE_EXTERNAL", "False")),
            use_metrics=str2bool(os.getenv("MONITOR_CACHE_PROMETHEUS_ENABLED", "True")),
            metrics_port=int(os.getenv("MONITOR_CACHE_PROMETHEUS_PORT", "8010")),
            omni_service="deepsearch-monitor-cache",
        )
    )

    @staticmethod
    def get_deployment_config():
        from idl.service.config.deployments import DeploymentFile, DeploymentString

        # read deployment config from command line
        deployments_str = DeploymentString("DEEPSEARCH_CRAWLER_SERVICE_DEPLOYMENTS").read()

        if deployments_str:
            return deployments_str

        # read deployment config from config file
        deployments_file = DeploymentFile(
            "DEEPSEARCH_CRAWLER_SERVICE_DEPLOYMENTS_FILE",
            f"{config_file_loc}/configuration/deployment.yaml",
        ).read()

        if deployments_file:
            return deployments_file

    @staticmethod
    def to_string():
        """Print configuration parameters to :func:`sys.stdout`."""

        message = prepare_message(
            msg="Service settings",
            item_list=[
                f"Configuration file:              {AssetDBConfig.omni_config_file}",
                f"Trigger to rebuild predictions:  {AssetDBConfig.rebuild_predictions}",
                f"Excluded string patterns:        {AssetDBConfig.exclude_uri_substrings}",
                f"Skip Omniverse Writes:           {AssetDBConfig.skip_omni_writes}",
            ],
        )
        message += prepare_message(
            msg="Plugins",
            item_list=[
                f"Plugins path:                    {AssetDBConfig.plugins_path}",
                f"Plugins configuration path:      {AssetDBConfig.plugins_config_path}",
                f"Plugin controllable parameters:  {AssetDBConfig.plugin_controllable_params}",
                f"Plugin cache context enabled:    {AssetDBConfig.plugin_cache_context_enabled}",
            ],
        )
        message += prepare_message(
            msg="Omniverse Connection",
            item_list=[
                f"Omniverse Server:                {AssetDBConfig.omni_server}:{AssetDBConfig.omni_port}",
                f"Service name:                    {AssetDBConfig.omni_service}",
                f"Service instance:                {AssetDBConfig.omni_instance}",
                f"Omniverse User:                  {AssetDBConfig.omni_master_user}",
                f"Number of connection retries:    {AssetDBConfig.max_connection_retries}",
            ],
        )
        message += prepare_message(
            msg="Omniverse Farm set-up",
            item_list=[
                f"Farm endpoint:                   {AssetDBConfig.farm_queue_protocol}://{AssetDBConfig.farm_queue_host}:{AssetDBConfig.farm_queue_port}",
                f"Receiving websocket endpoint:    {AssetDBConfig.farm_ws_protocol}://{AssetDBConfig.farm_ws_host}:{AssetDBConfig.farm_ws_port}",
                f"Internal websocket endpoint:     {AssetDBConfig.farm_internal_ws_host}:{AssetDBConfig.farm_internal_ws_port}",
            ],
        )
        message += prepare_message(
            msg="Inference API server",
            item_list=[
                f"IDL service internal port        {AssetDBConfig.idl_port}",
                f"IDL service internal host        {AssetDBConfig.idl_host}",
                f"IDL service public port          {AssetDBConfig.idl_pub_port}",
                f"IDL service public host          {AssetDBConfig.idl_pub_host}",
                f"Use discovery flag               {AssetDBConfig.use_discovery}",
                f"Path black list                  {AssetDBConfig.path_blacklist}",
            ],
        )
        message += prepare_message(
            msg="Timeouts",
            item_list=[
                f"Connection timeout (s):          {AssetDBConfig.omni_connection_timeout}",
                f"Connection Ping Frequency (s):   {AssetDBConfig.omni_connection_ping}",
                f"Tagging service timeout (s):     {AssetDBConfig.omni_tag_service_timeout}",
                f"Inference job max wait (s):      {AssetDBConfig.job_timeout}",
                f"IDLE subscription  timeout (h):  {AssetDBConfig.omni_list_idle_timeout}",
                f"Path listing timeout:            {AssetDBConfig.listing_timeout}",
                f"Full rescan timeout (h):         {AssetDBConfig.rescan_timeout}",
                f"Timeout for the mount check (h): {AssetDBConfig.mount_check_timeout}",
            ],
        )
        message += prepare_message(
            msg="Cache and Queue",
            item_list=[
                f"Cache version:                   {AssetDBConfig.cache_version}",
                f"ES Cache version:                {AssetDBConfig.es_cache_version}",
                f"ES Cache actualization timeout:  {AssetDBConfig.es_cache_actualization_timeout}",
                f"Asset DB file path:              {AssetDBConfig.assetdb_path}",
                f"Rendering temporary directory:   {os.getenv('OMNI_RENDER_TEMP_DIR')}",
                f"Items Queue size:                {AssetDBConfig.items_queue_size}",
                f"Prometheus metrics port:         {AssetDBConfig.prom_metrics_port}",
                f"System metrics timeout:          {AssetDBConfig.prom_system_metrics_timeout}",
                f"Processing file cache:           {AssetDBConfig.processing_request_cache_location}",
                f"Plugin cache in-memory size:     {AssetDBConfig.plugin_cache_in_memory_limit}",
                f"Plugin cache commit delay:       {AssetDBConfig.plugin_cache_commit_delay}",
            ],
        )
        message += prepare_message(
            msg="Logging",
            item_list=[
                f"Log file name (not used):        {AssetDBConfig.log_file_name}",
                f"Service logging level:           {AssetDBConfig.ts_logging_level}",
                f"Omniverse utils logging level:   {os.getenv('OMNIVERSE_UTILS_LOGLEVEL', 'INFO')}",
                f"Tagging utils logging level:     {os.getenv('TAG_UTILS_LOGLEVEL', 'INFO')}",
                f"Socket logging level:            {os.getenv('SOCKET_LOGGER_LOGLEVEL', 'INFO')}",
                f"Liveness probe logging level:    {os.getenv('LIVENESS_PROBE_LOGLEVEL', 'INFO')}",
                f"DateTime utils logging level:    {os.getenv('DATETIME_UTILS_LOGLEVEL', 'INFO')}",
                f"Configuration logging level:     {os.getenv('CONFIG_UTILS_LOGLEVEL', 'INFO')}",
                f"Plugin utils logging level:      {os.getenv('PLUGIN_UTILS_LOGLEVEL', 'INFO')}",
                f"Generic imports logging level:   {os.getenv('GENERIC_LOGLEVEL', 'INFO')}",
                f"Cron tasks logging level:        {os.getenv('CRON_TASKS_LOGLEVEL', 'INFO')}",
            ],
        )
        message += prepare_message(
            msg="Configuration of the inference service",
            item_list=[
                f"TCP port:                        {AssetDBConfig.infer_port}",
                f"Number of pointclouds to send:   {AssetDBConfig.infer_send_size}",
                f"Max time in the waiting queue:   {AssetDBConfig.infer_timeout}",
                f"Max size of CPU task queue:      {AssetDBConfig.cpu_queue_max_length}",
                f"Max size of Event queue:         {AssetDBConfig.maxsize_event_queue}",
                f"Max size of Item queue:          {AssetDBConfig.maxsize_item_queue}",
                f"# workers for CPU tasks:         {AssetDBConfig.cpu_queue_num_workers}",
                f"# threads for non-farm tasks:    {AssetDBConfig.non_farm_queue_num_workers}",
                f"# omni event threads:            {AssetDBConfig.omni_event_queue_num_workers}",
                f"# parallel requests:             {AssetDBConfig.inference_queue_batch_size}",
                f"Max requests per second:         {AssetDBConfig.max_request_per_second}",
                f"Batch size:                      {AssetDBConfig.batch_size}",
            ],
        )
        message += prepare_message(
            msg="Persistent Queue configuration",
            item_list=[
                f"Desired number of elements:      {AssetDBConfig.pers_queue_dlen}",
                f"List of unique fields per item:  {AssetDBConfig.unique_fields}",
            ],
        )
        # message += prepare_message(
        #     msg="Omniverse mounts",
        #     item_list=[
        #         f"schedule: {mtimeout}h: mount name: {mname}"
        #         for mname, mtimeout in AssetDBConfig.omni_mounts.items()
        #     ],
        # )

        def metrics_str(s):
            return "metrics " + f"@ {s['metrics_port']}" if s["use_metrics"] else "unavailable"

        def batch_str(s):
            if s["batch_size"] is not None:
                return f", batch size: {s['batch_size']}"
            else:
                return ""

        def pp_str(s):
            if s["n_parallel_queue_processors"] is not None:
                return f", queue proc: {s['n_parallel_queue_processors']}"
            else:
                return ""

        return message
