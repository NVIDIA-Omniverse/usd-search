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
import asyncio
import hashlib
import inspect

# standard imports
import logging
import os
import os.path as osp
import pickle
import signal
import socket
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional

import psutil
import websockets
from prometheus_client import Counter, Gauge, Info
from pydantic import Field
from pydantic_settings.main import BaseSettings

# local/proprietary modules
# > assumes that the omniverse connection bindings are in the path
# > functionality available from the current package
from search_utils import log_utils as lu
from search_utils import misc_utils as mu
from search_utils.datetime_utils import date_from_timestamp
from search_utils.storage_client import StorageClient, StorageClientConfig, get_client
from search_utils.storage_client.nucleus import DEPLOYMENT_LOOKUP
from search_utils.storage_client.nucleus.auth import NucleusAuth
from search_utils.storage_client.utils import (
    is_correct_format,
    is_exclude_uri,
    task_wrapper,
)

from .cache_utils.redis import CacheDictRedis
from .storage_client.config import StorageConfig, get_backend_config_class

# third party modules


microservice_utils_logger = logging.getLogger(__name__)

try:
    from idl.connection.transport import TransportError
except ModuleNotFoundError:
    if not mu.str2bool(os.getenv("OMNI_UTILS_UNAVAILABLE", "False")):
        microservice_utils_logger.warning(
            "Omniverse Utils module is not found, some functionality may not be available"
        )
        os.environ["OMNI_UTILS_UNAVAILABLE"] = "True"


# # Note this is hard-coded to the new (IDL based tagging utils. The old version is long unused, so should be no issue here)
# try:
#     from search_utils import idl_tag_utils as tu
# except ModuleNotFoundError:
#     microservice_utils_logger.warning("Omni tagging not found")


class MicroserviceSettings(BaseSettings):
    storage_client_ping_timeout: float = Field(
        default=5,
        description="storage client ping timeout",
        env="STORAGE_CLIENT_PING_TIMEOUT",
    )  # in order to switch-off ping functionality - set this value below 0


class EmptyMountSet(Exception):
    pass


class AssetdbMSCronMixin:
    def __init__(
        self,
        *args,
        redis_url: str,
        redis_db_cron: Optional[int] = None,
        use_cron_type_jobs: Optional[bool] = True,
        cron_job_mapping: Optional[dict] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs, redis_url=redis_url)

        if use_cron_type_jobs:
            if cron_job_mapping is None:
                cron_job_mapping = {}

            if redis_db_cron is None:
                raise RuntimeError("When using cron type jobs the redis_db_cron must be set")
            microservice_utils_logger.info(
                f"Service is configured to use cron jobs with the storage: {redis_url}/{redis_db_cron}"
            )
            self.cron_job_cache = CacheDictRedis(redis_url, redis_db_cron)
            self.cron_job_mapping = cron_job_mapping
            self.cron_logger = logging.getLogger(__name__ + ".cron")
            self.cron_task = asyncio.ensure_future(self.run_cron_tasks())

    async def run_cron_tasks(self, timeout: float = 60):
        cron_job_mapping = {k: v for k, v in self.cron_job_mapping.items() if v["timeout"] >= 0}

        if len(cron_job_mapping) == 0:
            self.cron_logger.info("No cron tasks scheduled")
            return

        for k in cron_job_mapping:
            if k not in list(self.cron_job_cache.keys()):
                self.cron_job_cache[k] = time.time()

        while not self.get_stop_service():
            for k, v in cron_job_mapping.items():
                # timeout
                await asyncio.sleep(timeout)
                # run tasks
                if time.time() > self.cron_job_cache[k]:
                    try:
                        self.cron_logger.info(f"Running '{k}' at {date_from_timestamp(time.time())}")
                        bg = time.time()
                        await v["task"]()
                        self.cron_job_cache[k] = time.time() + v["timeout"]
                        lu.prepare_message(
                            msg=f"'{k}' completed",
                            item_list=[
                                f"elapsed time:    {time.time() - bg:.02f} (s)",
                                f"next execution: {date_from_timestamp(self.cron_job_cache[k])}",
                            ],
                            logger=self.cron_logger.info,
                        )
                    except EmptyMountSet:
                        self.cron_logger.debug(f"{v['task']}: Empty mount list")
                    except FileNotFoundError as e:
                        self.cron_logger.warning(f"{v['task']}: Invalid URI: {str(e)}")
                    except ConnectionError as e:
                        self.cron_logger.error(f"'{v['task']}': Connection Error: {str(e)}")
                    except Exception as e:
                        self.cron_logger.exception(f"'{v['task']}': Exception: {str(e)}")
                else:
                    self.cron_logger.debug(
                        f"Task '{k}' will be executed at {date_from_timestamp(self.cron_job_cache[k])}"
                    )


class AssetdbMS:
    """Template implementation of the microservice that works with omniverse

    Args:
        config: some service configuration parameters.
        str log_name: name of the logger
        bool flush_on_model_update: if ``True`` - clean the cache if the model is updated. Default: ``False``
        :py:mod:`db_path` attribute in config and throws an exception if it cannot find it.
    """

    def __init__(
        self,
        config,
        log_name: str = "microservice template",
        db_path: Optional[str] = None,
        use_items_queue: bool = False,
        use_prom_metrics: bool = False,
        connection_names: Optional[List[str]] = None,
        storage_config: Optional[StorageConfig] = None,
        storage_client_config: Optional[StorageClientConfig] = None,
        settings: MicroserviceSettings = MicroserviceSettings(),
        **kwargs,
    ):
        if db_path is None:
            self.db_path = getattr(config, "db_path", None)
        else:
            self.db_path = db_path

        if connection_names is None:
            connection_names = [
                "light",
                "heavy",
            ]
        if storage_config is None:
            storage_config = StorageConfig()
        self.storage_config = storage_config
        self.settings = settings

        # dictionary for all the clients
        self.clients = {}

        # service configuration parameters
        self.config = config
        # set up some general properties
        # > logging
        self.log = lu.setup_logging(config=self.config, log_name=log_name, script_name=osp.basename(__file__))

        # > stop service trigger
        self.stop_service = False

        # > probe blocking trigger
        self.block_probe = False

        # > omniverse connection recreation trigger
        self.recreate_connection = asyncio.Event()
        # self.recreate_connection

        # > get event loop
        self.loop = asyncio.get_event_loop()

        if len(connection_names) > 0:
            # > omniverse connection args
            self.prepare_storage_authentication()

        if storage_client_config is None:
            storage_client_config = get_backend_config_class(self.storage_config.storage_backend_type)()

        self.storage_client_config = storage_client_config

        # > initialize the list of service items (just for visualization)
        self.service_items = []

        # > use single omniverse connection for all subscriptions
        self.service_items.append("Global Omniverse connection")
        self.connection_initialized = asyncio.Event()
        self.connection_init_lock = asyncio.Lock()
        self.exception_handler_lock = asyncio.Lock()
        # create authentication registry
        self.connection_counter = 0
        self.connection_names = connection_names
        self.storage_clients: Dict[str, StorageClient] = {n: None for n in self.connection_names}
        # task for the storage client ping
        self._storage_client_ping_task: Optional[asyncio.Task] = None
        if len(self.storage_clients) > 0:
            loop = asyncio.get_event_loop()
            self._storage_client_ping_task = loop.create_task(
                task_wrapper(self.storage_client_ping, name="Storage Connection ping")
            )

        # > use prometheus metrics
        self.use_prom_metrics = use_prom_metrics
        if use_prom_metrics:
            self.service_items.append("Prometheus metrics")
            # prepare labels for prometheus metrics
            self.prom_labels = dict(
                omni_service=self.get_omni_service(),
                omni_instance=self.config.omni_instance,
                omni_host=self.config.omni_server,
                omni_alert=0,
            )
            # get service pid
            self.pid = os.getpid()
            self.process = psutil.Process(self.pid)
            # initialize prometheus metrics
            self.init_prom_metrics()

        self.use_items_queue = use_items_queue
        # > set-up queue for processing items
        if use_items_queue:
            self.service_items.append("Items queue")
            self.recreate_items_queue()
            if self.use_prom_metrics:
                self.n_processed_items = Counter(
                    "omnideepsearch_service_processed_items",
                    "Count of processed items",
                    list(self.prom_labels.keys()),
                )

        # print service configuration to the screen
        lu.prepare_message(
            msg="Service is configured with:",
            item_list=self.service_items,
            logger=self.log.info,
        )

    async def terminate(self):
        # set stop service to True
        self.stop_service = True
        # close conneciton ping task
        if self._storage_client_ping_task is not None:
            self._storage_client_ping_task.cancel()

    def get_omni_service(self):
        return self.config.omni_service

    async def client_ping_wrapper(
        self,
        client_name,
        initialization_fn: callable,
        timeout: float = 5,
        initialization_timeout: float = 30,
        connection_timeout: Optional[float] = None,
        name: str = "Client",
    ):
        bg = time.time()
        while not self.get_stop_service():
            try:
                client = self.clients.get(client_name)
                if client is not None:
                    await client.demo_test(f"{socket.gethostname()}:{os.getpid()}")
            except websockets.exceptions.ConnectionClosedError as e:
                self.log.warning(f"Connection closed: {str(e)}")
                client = None
                self.clients[client_name] = None
            except Exception as e:
                self.log.warning(f"{name} unavailable: {str(e)}")
                client = None
                self.clients[client_name] = None

            if connection_timeout is not None and connection_timeout > 0 and time.time() - bg > connection_timeout:
                await self.clients[client_name].transport.close()
                self.clients[client_name] = client = None
                self.log.info(f"Client reconnected on timeout: {connection_timeout}")

            try:
                if client is None:
                    with lu.print_wrapper(
                        f"{client_name} connection initialization",
                        print_after=False,
                        logger=self.log.info,
                    ):
                        self.clients[client_name] = await asyncio.wait_for(
                            initialization_fn(), timeout=initialization_timeout
                        )
                        bg = time.time()
                        self.log.info(f"{name} is connected")
            except asyncio.TimeoutError:
                self.log.warning(f"Connection could not be initialized within {initialization_timeout}s")
            except websockets.exceptions.ConnectionClosedError as e:
                self.log.warning(f"Connection closed: {str(e)}")
            except Exception as e:
                self.log.warning(f"Client initialization error: {str(e)}")

            await asyncio.sleep(timeout)

    async def initialize_client(self, interface, event: asyncio.Event, deployment: Optional[str] = None):
        event.clear()
        initialized = False
        if deployment is None:
            deployment = DEPLOYMENT_LOOKUP
        while not initialized:
            try:
                microservice_utils_logger.debug(f"Discovering service {interface=} {deployment=}")
                client = await interface.discover_service(self.config.omni_server, meta={"deployment": deployment})
                initialized = True
            except ConnectionError as e:
                self.log.warning(str(e))
                await asyncio.sleep(5)
            except Exception as e:
                self.log.exception(e)
                await asyncio.sleep(5)

        # set mutex value so that the other processes can go forward
        event.set()
        return client

    def init_prom_metrics(self):
        prom_labels = list(self.prom_labels.keys())
        self.process_memory_info = Gauge(
            "omni_service_process_memory_info",
            "Process Memory information",
            ["type"] + prom_labels,
        )
        self.process_cpu_times = Gauge(
            "omni_service_process_cpu_times",
            "Process CPU utilization total time",
            ["type"] + prom_labels,
        )
        self.process_cpu_percent = Gauge(
            "omni_service_process_cpu_percent",
            "Process CPU utilization in percent",
            prom_labels,
        )
        self.process_status = Info("omni_service_process_status", "Process Status", prom_labels)
        self.process_num_threads = Gauge(
            "omni_service_process_num_threads",
            "Process number of threads",
            prom_labels,
        )

    def get_memory_metrics(self):
        with self.process.oneshot():
            self.process_cpu_times.labels(type="user", **self.prom_labels).set(self.process.cpu_times().user)
            self.process_cpu_times.labels(type="system", **self.prom_labels).set(self.process.cpu_times().system)
            self.process_cpu_percent.labels(**self.prom_labels).set(self.process.cpu_percent())
            self.process_status.labels(**self.prom_labels).info({"status": self.process.status()})
            self.process_num_threads.labels(**self.prom_labels).set(self.process.num_threads())
            mem = self.process.memory_full_info()
            for name, value in mem._asdict().items():
                self.process_memory_info.labels(type=name, **self.prom_labels).set(value)

    async def process_metrics(
        self,
    ):
        while not self.get_stop_service():
            self.get_memory_metrics()
            await asyncio.sleep(self.config.prom_system_metrics_timeout)

    def recreate_items_queue(self):
        self.items_queue = asyncio.Queue(getattr(self.config, "items_queue_size", 0))

    @asynccontextmanager
    async def next_item(self, timeout: float = 20):
        try:
            r = await asyncio.wait_for(self.items_queue.get(), timeout=timeout)
            self.items_queue.task_done()
            yield r
            # increment prometheus metric
            if self.use_prom_metrics:
                self.n_processed_items.labels(**self.prom_labels).inc(1)
        except ValueError as e:
            self.log.warning(f"warning instead of exception: {e}")
            yield None
        except asyncio.TimeoutError:
            self.log.debug(f"idle for {timeout} s")
            yield None
        except RuntimeError as e:
            self.log.error(f"runtime error: {str(e)}")
            yield None

    def items_queue_len(self):
        return self.items_queue.qsize()

    async def enqueue_item(self, item):
        await self.items_queue.put(item)

    async def service_preparation_fn(self, n_tries: int = 1000, require_tagging: bool = True, **kwargs):
        """Setting up some global variables before starting the main loop of the service."""

        # wait for connection to be initialized
        await self.wait_connection_initialization()

        # set a trigger for connection recreationg
        self.recreate_connection.set()
        # check that the tagging service is available
        # if require_tagging:
        #     await self.tagging_service_check(n_tries=n_tries)

    def asset_read_error_callback(self, asset_r, **kwargs):
        """Callback function that is executed, on asset processing error.

        Args:
            asset_r: omniverse subscription result
        """
        self.log.debug(f"Empty data for '{asset_r.uri}'")

    def asset_read_success_callback(self, asset_r, asset_data, **kwargs):
        self.log.debug(f"Data for '{asset_r.uri}' successfully extracted")
        return asset_data

    @property
    def config_listener_kwargs(self):
        return {
            "config": self.config,
            "logger": self.log.info,
            "stop_service_fn": self.get_stop_service,
            "on_change_callback": self.on_config_file_change_callback,
            "exception_handler": self.blocking_exception_handler,
            "preparation_fn": self.config_listener_preparation_fn,
            "storage_client": self.storage_clients["light"],
        }

    def connection_getter(self, name: str, action: str = "warn") -> StorageClient:
        """Return connection from the registry given its name.

        Args:
            name (str): name of the connection that need to be returned
            action (str, optional): action that needs to be taken when connection is not found. Defaults to "warn".

        Raises:
            ConnectionError: when connection with a given name is not found and action is not set to warn

        Returns:
            dict: omniverse connection
        """
        if name not in self.connection_names:
            msg = f"Connection '{name}' not found. Available connections are: {self.connection_names}"
            if action == "warn":
                self.log.warning(msg)
                return None
            else:
                raise ConnectionError(msg)
        else:
            return self.storage_clients[name]

    async def verify_connection_liveness(self) -> bool:
        """Return ``False`` if any of the connections is not alive.

        Returns:
            bool: connection liveness
        """
        alive = True
        client: StorageClient
        for _, client in self.storage_clients.items():
            alive = alive and (await client.check_connection())
        return alive

    def dlmodel_get_local_weights_folder(self, omni_model_path: str) -> str:
        """Return the location of the folder with weights of the DL model on the local machine."""
        local_model_zip = osp.join(self.config.local_model_path, osp.basename(omni_model_path))
        local_model_folder = osp.splitext(local_model_zip)[0]
        return osp.realpath(local_model_folder)

    def check_included_path(self, path: str) -> bool:
        """Check that the path need to be processed."""
        # check that config is properly set
        self.check_config_attr("file_formats")
        self.check_config_attr("exclude_uri_substrings")

        return not (
            not is_correct_format(path, self.config.file_formats)
            or is_exclude_uri(path, self.config.exclude_uri_substrings)
        )

    def check_correct_omni_path(self, r) -> bool:
        """Check that the omniverse item:

            * exists
            * is of correct format
            * is not in excluded paths

        Args:
            r: Omniverse subscription result item
        """
        return not (not r or r.uri is None or not self.check_included_path(r.uri))

    def check_config_attr(self, name: str, msg: str = "attribute {} missing"):
        """Check that requested attribute is found in service configuration.

        Args:
            name (str): name of requested attribute
            msg (str, optional): message that will be printed to the screen. Defaults to "attribute {} missing".

        Raises:
            AttributeError: if the attribute is missing
        """
        if not hasattr(self.config, name):
            raise AttributeError(msg.format(name))

    @staticmethod
    def _raise_not_impl(name):
        raise NotImplementedError(
            f"Using '{name}' function of \n" "the base class, consider re-implementing it\n" "in the derived class"
        )

    def on_config_file_change_callback(self):
        """Callback that is executed when the config file has been changed."""
        self._raise_not_impl(self._this_func_name())

    # set of function for FLANN DB and index building
    def hash_dict(self, dictionary):
        """Compute the hash of the python dictionary by first serializing it with pickle and
        then computing the hash of the serialized string.
        """
        pickled_dct = pickle.dumps(dictionary)
        return hashlib.sha256(pickled_dct).hexdigest()

    # set of general functions for the service
    def prepare_storage_authentication(self):
        """Prepare the arguments that are needed for the omniverse connection. Requires the following attributes to be set in the cofiguration class

        * ``config.omni_server`` -- :py:mod:`config.AssetDBConfig.omni_server`
        * ``config.omni_port`` -- :py:mod:`config.AssetDBConfig.omni_port`
        * ``config.omni_master_user`` -- :py:mod:`config.AssetDBConfig.omni_master_user`
        * ``config.omni_master_password`` -- :py:mod:`config.AssetDBConfig.omni_master_password`
        """
        self.auth = NucleusAuth.model_construct(
            user=self.config.omni_master_user, password=self.config.omni_master_password
        )
        return self.auth

    async def wait_connection_initialization(self):
        """Wait for omniverse connection initialization."""
        if self.connection_initialized is not None:
            await self.connection_initialized.wait()

    async def wait_config_listener_connected(self):
        """Wait for the initialization of connection listener"""
        if self.config_listener_connected is not None:
            await self.config_listener_connected.wait()

    async def initialize_storage_connection(
        self,
    ):
        # make sure mutex is defined
        assert self.connection_initialized is not None, "Incorrect mutex value"
        assert len(self.connection_names) > 0, f"Number of connection names is {len(self.connection_names)}"

        async with self.connection_init_lock:
            # clean authentication registry
            # prepare connection arguments
            self.prepare_storage_authentication()

            for connection_name in self.connection_names:
                client = self.storage_clients[connection_name]
                if client is not None and await client.check_connection(ping_timeout=30):
                    continue

                storage_client: StorageClient = get_client(
                    client_type=self.storage_config.storage_backend_type,
                    config=self.storage_client_config,
                )

                initialized = False
                while not initialized:
                    try:
                        # initialize storage client connection
                        await storage_client.connect()
                        # save it in the dict
                        self.storage_clients[connection_name] = storage_client
                        initialized = True
                    except Exception as e:
                        microservice_utils_logger.exception(f"Connection initialization exception: {str(e)}")
                        await asyncio.sleep(1)

            lu.prepare_message(
                msg="Connection stats",
                item_list=[f"Storage clients' registry: {len(self.storage_clients)}"]
                + [f"{k}: {client.connection_info}" for k, client in self.storage_clients.items()],
                logger=self.log.info,
            )

        # set mutex value so that the other processes can go forward
        self.connection_initialized.set()

    async def storage_client_ping(self) -> None:
        # # initialize connection
        # await self.initialize_storage_connection()
        await self.connection_initialized.wait()
        # run loopto reinitialize connection if needed
        if self.settings.storage_client_ping_timeout <= 0:
            return

        while True:
            try:
                reinit = False
                for c in self.storage_clients.values():
                    if not await c.check_connection(ping_timeout=self.settings.storage_client_ping_timeout):
                        reinit = True
                        break
            except Exception as e:
                self.log.exception(f"Omni ping wrapper exception: {str(e)}")
                reinit = True

            # re-init connection
            if reinit:
                self.connection_initialized.clear()
                await self.initialize_storage_connection()

            await asyncio.sleep(5)

    def _wakeup(
        self,
    ):
        if not self.stop_service:
            self.loop.call_later(1.0, self._wakeup)

    def shutdown_handler(self, signum, frame):
        """Set the  :py:mod:`self.stop_service` to ``True`` and log that the server is shutting down."""
        if not self.stop_service:
            self.log.info("Shutting down ...")
            self.stop_service = True

    def setup_signal_handlers(self):
        """Catch the Ctrl + C signal and set the  :py:mod:`self.stop_service` to ``True``"""
        self.stop_service = False
        self.log.info("Press Ctrl + C to stop the service")
        self.loop.call_later(1.0, self._wakeup)
        signal.signal(signal.SIGINT, self.shutdown_handler)
        signal.signal(signal.SIGTERM, self.shutdown_handler)

    def exception_handler(self, e, **kwargs):
        """Process the exception."""
        lu.log_exception(e, logger=kwargs.get("logger", self.log.info))

    async def blocking_exception_handler(self, e, keep_alive: bool = True, **kwargs):
        """Process the exception and block the liveness probe."""
        self.exception_handler(e, **kwargs)
        async with self.exception_handler_lock:
            if self.connection_initialized is not None and isinstance(
                e,
                (
                    ConnectionError,
                    TransportError,
                    asyncio.TimeoutError,
                ),
            ):
                # check connection liveness
                if (await self.verify_connection_liveness()) and keep_alive:
                    self.log.info("Connection is alive: continue running the service")
                elif self.connection_counter >= getattr(self.config, "max_connection_retries", 0):
                    self.block_probe = True
                    raise e
                else:
                    self.connection_counter += 1
                    self.log.info(f"Try recreating connection: {self.connection_counter}")
                    # wait for the connection to be recreated in the background
                    await asyncio.sleep(5)
                    # await self.initialize_storage_connection()

                # close running loops and restart services
                self.recreate_connection.clear()
            else:
                self.block_probe = True
                raise e

    def get_stop_service(self) -> bool:
        """Return the value of the :mod:`self.stop_service` parameter."""
        if self.block_probe:
            self.stop_service = True
        return self.stop_service

    def get_recreate_connection(self) -> bool:
        """Return the value of the :mod:`self.recreate_connection` parameter."""
        if isinstance(self.recreate_connection, bool):
            return self.recreate_connection
        elif isinstance(self.recreate_connection, asyncio.Event):
            return not self.recreate_connection.is_set()

    def run(self, **kwargs):
        """Exectute the service. ``Note``: This function needs to be implemented for each services that inherits from this one."""
        self._raise_not_impl(self._this_func_name())

    def get_asset_local_path(self, uri):
        """Return path to the file on the local drive, where the asset is stored.

        Args:
            str uri: path of the asset in omniverse

        Returns:
            str: Local path of the temporary asset storage
        """
        self.check_config_attr("db_path")
        _, tail = osp.split(uri)
        local_path = osp.join(self.db_path, "temp_assets", tail)
        os.makedirs(osp.dirname(local_path), exist_ok=True)
        return local_path

    @staticmethod
    def get_asset_thumb_path(uri: str, thumbs_loc: str = ".thumbs", thumbs_res: tuple = (256, 256)) -> str:
        """Return path to the file on the local drive, where the asset is stored.

        Args:
            str uri: path of the asset in omniverse
            str thumbs_loc: Location where the humbanils are stored (default: '.thumbs')
            tuple thumbs_res: resolution of the humbnails (default: (256, 256))

        Returns:
            str: Local path of the temporary asset storage
        """
        head, tail = osp.split(uri)
        # generate the locatio of the thumbnail
        return f"{head.rstrip('/')}/{thumbs_loc}/{thumbs_res[0]}x{thumbs_res[1]}/{tail}.png"

    def get_path_from_omni_list(self, list_of_results, path):
        """Get a pointer to Omniverse object from the list of pointers.

        Args:
            list list_of_results: List of paths from omniverse.
            str path: Path that needs to be found in a list.
        """
        for res in list_of_results:
            if res.uri == path:
                return res

        return None

    @staticmethod
    def _this_func_name():
        return inspect.stack()[1][3]

    async def local_cache_actualization(
        self,
        client: StorageClient,
        cache_object: CacheDictRedis,
        interface,
        connection_config: dict = {},
        log_timeout: float = 30,
        deployment_lookup: str = None,
        batch_size: int = 256,
    ):
        if deployment_lookup is None:
            deployment_lookup = DEPLOYMENT_LOOKUP

        # iterate through all local cache keys and verify that they are relevant
        bg = time.time()
        removed_counter = 0
        ngsearch_storage_client = await asyncio.wait_for(
            interface.get_service(**connection_config),
            timeout=30,
        )

        storage_client: StorageClient
        async with client.connection_context(client.connection_getter()) as storage_client:
            async with ngsearch_storage_client as client:
                batch = []
                for it, k in enumerate(cache_object.iterkeys()):
                    batch.append(k)
                    if len(batch) > batch_size:
                        # get results from the storage service
                        response = await client.exists(keys=batch)

                        nucleus_response = await asyncio.gather(*[storage_client.check_if_exists(k) for k in batch])

                        for r, nr, b in zip(response.exists, nucleus_response, batch):
                            self.cron_logger.debug(f"existence check '{b}': {r}")
                            if not r or not nr[0]:
                                del cache_object[b]
                                removed_counter += 1
                        batch = []

                    if time.time() - bg > log_timeout:
                        self.cron_logger.info(
                            f"removed: {mu.get_percentage_string(removed_counter, it + 1)} "
                            f"processed: {mu.get_percentage_string(it + 1, removed_counter + len(cache_object))}"
                        )
                        bg = time.time()

                if len(batch) > batch_size:
                    response = await client.exists(keys=[self.get_kit_path(k) for k in batch])
                    for r, b in zip(response.exists, batch):
                        self.cron_logger.debug(f"existence check '{b}': {r}")
                        if not r:
                            del cache_object[b]
                            removed_counter += 1

        lu.prepare_message(
            msg="Actualization stats:",
            item_list=[
                f"removed: {mu.get_percentage_string(removed_counter, removed_counter + len(cache_object))}",
                f"current cache size: {len(cache_object)}",
            ],
            logger=self.cron_logger.info,
        )


class AssetdbMSWithCron(AssetdbMSCronMixin, AssetdbMS):
    """AssetdbMS class with the support for cron-type jobs"""

    pass
