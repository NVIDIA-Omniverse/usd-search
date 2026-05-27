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
import os
import shutil
import sys

# standard modules
import unittest
from copy import deepcopy
from functools import partial

bin_path = os.path.dirname(os.path.realpath(__file__))
ms_code_src_path = f"{bin_path}/../../"
sys.path.extend(
    [
        f"{ms_code_src_path}",
        f"{ms_code_src_path}/package-links/omniverse_connection/",
        f"{ms_code_src_path}/package-links/idl.py",
        f"{ms_code_src_path}/package-links/discovery.client.py",
        f"{ms_code_src_path}/package-links/omniverse.auth.client.py",
    ]
)

# third party modules
import numpy as np
from config import AssetDBConfig as service_Config

import search_utils.config_utils as cu
import search_utils.log_utils as lu
import search_utils.misc_utils as mu

# local / proprietary modules
import search_utils.omniverse_utils as ou

DRY_RUN = mu.str2bool(os.getenv("DRY_RUN", "True"))

logger = lu.set_simple_logger("omni deeptag tmp cleanup", os.getenv("LOG_LEVEL", "INFO"))


async def omni_delete_file(c, omni_f: list, **kwargs):
    """Delete a list of files from omniverse.

    Args:
        c: omniverse connection
        omni_f (list, str): list of files that need to be deleted

    Raises:
        ValueError: if input type is not ``list`` of ``str``
    """

    if isinstance(omni_f, str):
        omni_f = [omni_f]
    elif not isinstance(omni_f, list):
        raise ValueError(f"unknown input format: expected (str, list), got {type(omni_f)}")

    for f in omni_f:
        file_exists, file = await ou.check_if_exists(c, f, logger=logger.debug)
        if file_exists:
            logger.debug(f"Removing file: {f}")
            # wait for user to confirm
            assert f.find(".deeptag") >= 0
            x = input("Press Y[y]")
            if x.lower() == "y":
                # await asyncio.sleep(0.1)
                await c.delete(f)
            else:
                return
        elif file == "error":
            logger.debug(f"'{f}' file list error")
            assert f.find(".deeptag") >= 0
            x = input("Press Y[y]")
            if x.lower() == "y":
                # await asyncio.sleep(0.1)
                await c.delete(f)
            else:
                return
        else:
            logger.debug(f"'{f}' does not exist")


def delete_file(omni_f: list):
    # delete file
    ou.omni_single_task(
        service_Config,
        task=partial(
            executioner,
            task=partial(omni_delete_file, omni_f=omni_f),
            expected_response=None,
        ),
    )


async def executioner(args, config, **kwargs):

    task = kwargs.get("task", None)
    expected_response = kwargs.get("expected_response", None)
    assert task is not None

    async with ou.omni_connection_wrapper(*args) as c:
        response = await ou.task_wrapper_omni_ping(
            c,
            awaitable=task(c),
            recreate_connection_check_fn=lambda: False,
            ping_freq=2,
            logger=logger.debug,
            msg=f"executing omni task",
            timeout=config.omni_list_idle_timeout,
        )

    logger.debug(response)
    logger.debug(expected_response)
    if response is not None and len(response) > 0:
        response = response[0]
    assert response == expected_response


def main():
    # tmp_files = [
    #     "/Users/AZOELLNER@nvidia.com/release 2020.3/OM-6718_Variants/VariantSimple/.deeptag/appearance/",
    #     # "./Users/AZOELLNER@nvidia.com/release 2020.3/OM-6718_Variants/VariantSimple/.deeptag"
    # ]

    with open("C:/Users/arozantsev/Downloads/deeptag_bad_paths_cleaned_unique_hidden.txt", "r") as f:
        clean_hidden_list_v2 = f.readlines()

    tmp_files = [f.strip() for f in clean_hidden_list_v2]
    print(tmp_files)

    if not DRY_RUN:
        delete_file(tmp_files)


if __name__ == "__main__":
    """Sample command:

    $ DRY_RUN=False OMNIVERSE_UTILS_LOGLEVEL=DEBUG LOG_LEVEL=DEBUG OV_SERVER=ov-content.nvidia.com python scripts/clean_deeptag_files.py
    """
    main()
