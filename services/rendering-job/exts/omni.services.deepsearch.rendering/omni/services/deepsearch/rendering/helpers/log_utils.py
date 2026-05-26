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
import logging
import sys
import time
from typing import Callable, Optional


def set_simple_logger(logger_name: str, loglevel: str = "INFO"):
    """Create a simple logger.

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
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] {:} %(message)s".format("[" + "] [".join(logger_name.split(" ")) + "]")
    )
    ch.setFormatter(formatter)
    # add the handlers to the logger
    logger.handlers = []
    logger.addHandler(ch)
    # log only once
    logger.propagate = False

    return logger


def prepare_message(msg: Optional[str] = None, item_list: list = [], logger: Optional[Callable] = None) -> str:
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
        logger: Callable = sys.stdout.write,
        offset: int = 40,
        enabled: bool = True,
        print_after: bool = True,
        line_end: str = "",
    ):
        self.enabled = enabled
        self.text = text
        self.logger = logger
        self.offset = offset
        self.pa = print_after
        self.le = line_end

    def __enter__(self):
        if self.enabled:
            if not self.pa:
                self.logger(self.text)
            self.bg = time.time()
        return self

    def __exit__(self, *args):
        if self.enabled:
            self.logger(
                f"{self.text if self.pa else ''}"
                + " " * (self.offset - len(self.text))
                + f" [done in {time.time() - self.bg:.04f}s]{self.le}"
            )
