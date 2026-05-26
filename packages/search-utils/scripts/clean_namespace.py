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

# standard imports
import sys
from argparse import ArgumentParser

bin_path = os.path.dirname(os.path.realpath(__file__))
code_bin_path = f"{bin_path}/../.."

sys.path.extend(
    [
        code_bin_path,
        f"{code_bin_path}/package-links/omniverse_connection/",
        # f"{code_bin_path}/package-links/tag_service_client/bin",
        f"{code_bin_path}/package-links/tag_idl_client",
        f"{code_bin_path}/package-links/idl.py",
        f"{code_bin_path}/package-links/discovery.client.py",
        f"{code_bin_path}/package-links/omniverse.auth.client.py",
    ]
)


from config import AssetDBConfig as service_Config

# local/proprietary modules
import search_utils.log_utils as lu
import search_utils.omniverse_utils as ou

# try importing IDL-based tag client
#  on error fallback to the 1.4 client
from search_utils import misc_utils as mu
from search_utils import tag_utils as tu

logger = lu.set_simple_logger("script clean_namespaces", loglevel=os.getenv("SCRIPT_LOG_LEVEL", "INFO"))


async def get_list_of_paths(args, namespace: str, filter_by: str):
    with lu.print_wrapper("Getting a list of paths"):
        async with (
            ou.omni_connection_wrapper(*args, timeout=60) as c,
            tu.TaggingClientContextAsync(args[0]) as client,
        ):
            query_result = await client.query_paths(
                c=c,
                path=filter_by,
                namespace=namespace,
                return_tags=False,
                return_values=False,
                return_namespaces=False,
            )
            paths = query_result.paths

    logger.info(f"Total number of paths that will be updated: {len(paths)}")
    return paths


async def clean_appearance_inferred_namespaces_task(
    args,
    config,
    filter_by: str = "/Users/arozantsev/Kitchen_set",
    namespace: str = ".debug.generated",
    dry_run: bool = True,
    batch_size: int = 25,
):

    # set connection arguments
    lu.prepare_message(
        msg="cleaning namespaces with:",
        item_list=[
            f"Omniverse args: {args}",
            f"namespace: {namespace}",
            f"filter by: {filter_by}",
            f"dry run: {dry_run}",
            f"batch size: {batch_size}",
        ],
        logger=logger.info,
    )

    new_paths = await get_list_of_paths(args, namespace, filter_by)

    while len(new_paths) > 0 and not dry_run:
        with lu.print_wrapper("Clearing namespaces"):
            async with (
                ou.omni_connection_wrapper(*args, timeout=60) as c,
                tu.TaggingClientContextAsync(config.omni_server) as client,
            ):
                _ = await client.clear_namespaces(
                    c=c,
                    paths=new_paths,
                    namespaces=[namespace] * len(new_paths),
                    max_requests=batch_size,
                )
                logger.debug(f"last updated file was: {new_paths[-1]}")
        # check that the paths got cleaned
        new_paths = await get_list_of_paths(args, namespace, filter_by)


def parse_cmd():
    parser = ArgumentParser("Clean namespace arguments")
    parser.add_argument(
        "--namespace",
        type=str,
        default=os.getenv("NAMESPACE", ".debug.generated"),
        help="namespace that need to be cleaned",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=os.getenv("FILTER", "/"),
        help="string for filtering paths",
    )
    parser.add_argument(
        "--dry-run",
        type=str,
        default=os.getenv("DRY_RUN", "True"),
        help="if True - don't push items to omniverse",
    )
    return parser


def main(args):
    ou.omni_single_task(
        service_Config,
        clean_appearance_inferred_namespaces_task,
        filter_by=args.filter,
        namespace=args.namespace,
        dry_run=mu.str2bool(args.dry_run),
    )


if __name__ == "__main__":
    """Execution command:

    $ OV_SERVER=ov-rc.nvidia.com python clean_namespace.py
    """
    # parse command line arguments
    args = parse_cmd().parse_args()
    # run main task
    main(args)
