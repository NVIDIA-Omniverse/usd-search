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

# standard modules
import logging
import logging.config
import logging.handlers
import os
import sys
import time
import warnings
from pathlib import Path
from queue import Queue
from types import TracebackType
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp
import orjson
from pythonjsonlogger import jsonlogger

from .data import BaseLoggerSettings, SearchTelemetrySettings


def set_simple_logger(
    logger_name: str,
    loglevel: str = "INFO",
    config: BaseLoggerSettings = BaseLoggerSettings(),
) -> logging.Logger:
    """Create a simple logger.

    Args:
        str logger_name: name of the logger
        str loglevel: logging level (default: 'INFO')
    """
    warnings.warn(
        "set_simple_logger is deprecated, use plain logging.getLogger(__name__) instead",
        DeprecationWarning,
    )
    logger = logging.getLogger(logger_name)
    log_level = eval("logging." + loglevel.upper())
    logger.setLevel(log_level)
    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setLevel(log_level)
    # create formatter and add it to the handlers
    formatter: Union[JsonFormatter, logging.Formatter]
    if config.enable_json_logging:
        formatter = JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt=config.datefmt)
        formatter.default_msec_format = "%s.%03d"
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s - {:} - %(message)s".format(logger_name),
            datefmt=config.datefmt,
        )
    ch.setFormatter(formatter)
    # add handlers to the logger
    logger.handlers = []
    logger.addHandler(ch)
    # log only once
    logger.propagate = False

    return logger


def set_telemetry_logger(
    logger_name: str,
    loglevel: str = "INFO",
    settings: SearchTelemetrySettings = SearchTelemetrySettings(),
) -> logging.Logger:
    """Create a telemetry logger that outputs messages in unchanged format to stdout.

    Args:
        str logger_name: name of the logger
        str loglevel: logging level (default: 'INFO')
    """
    logger = logging.getLogger(logger_name)
    log_level = eval("logging." + loglevel.upper())
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(log_level)
    # create formatter and add it to the handlers
    formatter = logging.Formatter("%(message)s")
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.handlers = []
    logger.addHandler(ch)
    # # log only once
    if settings.exporter_url is not None:
        logger.addHandler(
            HTTPJsonLogHandler(
                url=settings.exporter_url,
                level=eval("logging." + settings.log_level.upper()),
            )
        )
    # logger.propagate = False

    return logger


def get_logger_name(file_path: str, remove_ext: bool = True) -> str:
    """Automatically generate name for the logger

    Args:
        file_path (str): path to a file in the package
        package_root (str): path to the package root
        remove_ext (bool, optional): if ``True`` - remove extension. Defaults to True.

    Returns:
        str: logger name
    """

    file_path = str(Path(file_path).resolve())
    package_root = str(Path(os.path.dirname(os.path.dirname(__file__))).parent.resolve())
    rel_path = file_path.replace(package_root, "")
    rel_path = rel_path.replace("\\", "/")
    rel_path = rel_path.lstrip("/")

    if remove_ext:
        rel_path = os.path.splitext(rel_path)[0]

    return rel_path.replace("/", " ")


def setup_logging(config, log_name: str, script_name: str, enable_file_logging: bool = False) -> logging.Logger:
    """Set up the logging for the service.

    Args:
        config: service configuration from :mod:`config.AssetDBConfig`
        str log_name: name of the log that will be printed to stdout and file
        str script_name: name of the script for the logging is set
        bool enable_file_logging: disable logging to file (default: False)
    """
    logger = set_simple_logger(log_name, config.ts_logging_level)

    # enable file logging
    if enable_file_logging:
        logger.propagate = True
        fh = logging.FileHandler(config.log_file_name)
        fh.setLevel(config.ts_logging_level)
        log_formatter = logging.Formatter("[%(asctime)s][{:}] %(levelname)s: %(message)s".format(log_name))
        fh.setFormatter(log_formatter)
        logger.addHandler(fh)

    return logger


def log_exception(e: BaseException, logger: Callable[[str], None] = logging.info) -> None:
    """Log exception.

    Args:
        Exception e: caught exception
        logger: output function
    """
    _, _, exc_tb = sys.exc_info()
    if exc_tb is not None:
        lineno = exc_tb.tb_lineno
    else:
        lineno = None
    logger(f"{type(e).__name__}({e.args}, line: {lineno}): {e}")


def setup_exceptions_logging(log: logging.Logger, crash_dump_dir: Optional[str] = None) -> None:
    """Set-up logging of the exceptions.

    Args:
        log: logger that is used for exceptions logging.
    """
    import linecache

    def ex_handler(
        exc_type: type[BaseException],
        exc_obj: BaseException,
        tb: Optional[TracebackType],
    ) -> None:
        if tb is not None:
            f = tb.tb_frame
            lineno = tb.tb_lineno
            filename = f.f_code.co_filename
            linecache.checkcache(filename)
            line = linecache.getline(filename, lineno, f.f_globals)
            msg = 'Service exception: file ({},\nline {} "{}"):\n{}'.format(filename, lineno, line.strip(), exc_obj)
        else:
            msg = "Service exception:"

        log.exception(msg)

        if crash_dump_dir is not None:
            # write exceptions to file
            os.makedirs(crash_dump_dir, exist_ok=True)

            with open(f"{crash_dump_dir}/dump.{str(time.time())}", "w", encoding="utf-8") as file_handler:
                file_handler.write(msg)

    sys.excepthook = ex_handler


def prepare_message(
    msg: Optional[str] = None,
    item_list: List[str] = [],
    logger: Optional[Callable[[str], None]] = None,
) -> str:
    """Prepare a message to summarize the list of strings

    Args:
        msg (str, optional): message that will be printed above the list if any. Defaults to ``None``.
        item_list (list, optional): list of items that need to be visualized. Defaults to ``[]``.
        logger (callable, optional): logging function. Defaults to ``None``.

    Returns:
        str: resulting string
    """

    result = "\n     > ".join([f"{item}" for item in [""] + item_list])

    if msg is not None:
        result = f"\n    {msg}{result}"

    if logger is not None:
        logger(result)

    return result


class print_wrapper(object):
    """Simple 'with' wrapper that records the time for the block of code to be executed.

    Args:
        str text: message to be printed
        logger: logging function
        int offset: offset, with which `[done will be printed]`
        bool enabled: if `False` will not print anything (default: `True`)
    """

    def __init__(
        self,
        text: str,
        logger: Callable[[str], Optional[int]] = sys.stdout.write,
        offset: int = 40,
        enabled: bool = True,
        print_after: bool = True,
        line_end: str = "",
    ) -> None:
        self.enabled = enabled
        self.text = text
        self.logger = logger
        self.offset = offset
        self.pa = print_after
        self.le = line_end
        self._bg: float = 0

    def __enter__(self) -> "print_wrapper":
        if self.enabled:
            if not self.pa:
                self.logger(self.text)
            self._bg = time.time()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType,
    ) -> None:
        if self.enabled:
            self.logger(
                f"{self.text if self.pa else ''}"
                + " " * (self.offset - len(self.text))
                + f" [done in {time.time() - self._bg:.04f}s]{self.le}"
            )


def add_queue_handler(logger: logging.Logger, queue: Queue[str], log_level: int = logging.DEBUG) -> None:
    """Add Queue handler to the logger

    Args:
        logger: logger
        queue (Queue): queue for the output
        log_level (optional): logging level. Defaults to 'logging.DEBUG'.
    """
    queue_handler = logging.handlers.QueueHandler(queue)

    logger.addHandler(queue_handler)
    formatter = logging.Formatter("%(threadName)s: %(message)s")
    queue_handler.setFormatter(formatter)
    queue_handler.setLevel(log_level)


async def async_post_task(url: str, content: str, headers: Dict[str, str]) -> Optional[aiohttp.ClientResponse]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url=url, data=content, headers=headers) as resp:
                return resp
    except Exception as exc_info:
        print(f"Log posting failed: {exc_info}")
    return None


class HTTPJsonLogHandler(logging.Handler):
    def __init__(self, url: str, level: int = 0) -> None:
        super().__init__(level)
        self._url = url

    def emit(self, record: logging.LogRecord) -> None:
        # get serialized message text
        msg = record.getMessage()
        # send request
        loop = asyncio.get_event_loop()
        loop.create_task(async_post_task(self._url, msg, headers={"Content-type": "application/json"}))


class JsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._config = BaseLoggerSettings()

    @property
    def config(self) -> BaseLoggerSettings:
        return self._config

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        # update the timestamp format

        log_record["level"] = record.levelname
        log_record["type"] = "log"
        log_record["log_origin"] = self.config.log_origin
        log_record["user_agent"] = self.config.user_agent
        log_record["level_num"] = record.levelno
        log_record["logger_name"] = record.name
        self.set_extra_keys(record, log_record, self._skip_fields)

    @staticmethod
    def is_private_key(key: str) -> bool:
        return hasattr(key, "startswith") and key.startswith("_")

    def is_extra_key(self, key: str) -> bool:
        return hasattr(key, "startswith") and key.startswith(self._config.extra_prefix)

    def set_extra_keys(
        self,
        record: logging.LogRecord,
        log_record: Dict[str, Any],
        reserved: Dict[str, str],
    ) -> None:
        """
        Add the extra data to the log record.
        prefix will be added to all custom tags.
        """
        record_items = list(record.__dict__.items())
        records_filtered_reserved = [item for item in record_items if item[0] not in reserved]
        records_filtered_private_attr = [
            item for item in records_filtered_reserved if not JsonFormatter.is_private_key(item[0])
        ]

        for key, value in records_filtered_private_attr:
            if not self.is_extra_key(key):
                if isinstance(value, (dict, list)):
                    value = orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY)
                new_key_name = f"{self.config.extra_prefix}{key}"
                log_record[new_key_name] = value
                log_record.pop(key, None)


from base_logging import (  # noqa: F401
    get_logging_config as _get_logging_config_from_yaml,
)
from base_logging import setup_logging as setup_logging_from_yaml  # noqa: F401
