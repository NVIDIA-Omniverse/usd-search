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

# standard imports
import sys

bin_path = os.path.dirname(os.path.realpath(__file__))
code_bin_path = f"{bin_path}/../.."

sys.path.extend(
    [
        code_bin_path,
        f"{code_bin_path}/package-links/omniverse_connection/",
        f"{code_bin_path}/package-links/tag_idl_client",
        f"{code_bin_path}/package-links/idl.py",
        f"{code_bin_path}/package-links/discovery.client.py",
        f"{code_bin_path}/package-links/omniverse.auth.client.py",
    ]
)


# local/proprietary modules
import omni.aioconnection.omniverse_aioconnection_wrapper as omni_conn

import search_utils.log_utils as lu
import search_utils.omniverse_utils as ou

# try importing IDL-based tag client
#  on error fallback to the 1.4 client
from search_utils import misc_utils as mu
from search_utils import tag_utils as tu


async def new_client_test(ov_server, ov_port, ov_user, ov_password):

    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    print(f"Omniverse args: {args}")

    paths = [
        "/Users/arozantsev/tmp/Table_Internal.usd",
        "/Users/arozantsev/tmp/Bench_01_Low_Internal.usd",
    ]
    tags = [["furniture", "table"], ["furniture", "bench"]]
    async with (
        ou.omni_connection_wrapper(*args) as c,
        tu.TaggingClientContextAsync(ov_server) as client,
    ):
        for p, t in zip(paths, tags):
            await client.add_user_tags(c=c, paths=[p], tags=t)

        res = await client.read_tags(c=c, path=paths[0])
        tags, vals = tu.get_user_tags_ns(res)
        tu.tag_utils_logger.info(f"{tags}, {vals}")
        tags, vals = tu.get_inferred_tags_ns(res)
        tu.tag_utils_logger.info(f"{tags}, {vals}")


async def new_client_sub_test(ov_server, ov_port, ov_user, ov_password):

    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    print(f"Omniverse args: {args}")
    path = "/Users/arozantsev/tmp"

    async with ou.omni_connection_wrapper(*args) as c:
        async with tu.TaggingClientSubContextAsync(c=c, path=path, ov_server=ov_server) as context:
            print(context.sub.subscription_id)
            r = await context.sub.fetch()
            print(r)


def omni_exec(task, *args, **kwargs):
    """

    Example:
        >>> from .utility_scripts import clean_appearance_inferred_namespaces as clean_ns
        >>> clean_ns("ov-rc.nvidia.com", "3009", )
    """

    async def run():
        """Run main task."""
        try:
            await task(*args, **kwargs)
        except Exception as e:
            print(f"Task initialization exception {str(e)}")

    # create the omniverse connection struct
    with lu.print_wrapper("Omniverse connection settings"):
        settings = omni_conn.OmniConnectionLibrarySettings()
        # settings.logTarget = omni_conn.OMNI_LOG_TARGET_CONSOLE
        settings.logIncomingMessages = False
        settings.logOutgoingMessages = False
        settings.version = omni_conn.OmniverseConnectionLibraryVersion
    # check that the even loop exists
    with lu.print_wrapper("Loop set-up"):
        if asyncio.get_event_loop().is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
    # initialize the connection
    with lu.print_wrapper("Omni init"):
        omni_conn.omni_initialize(settings, loop=loop)
    # omniverse start ticking
    with lu.print_wrapper("Omni start ticking"):
        omni_conn.omniStartTickingThread()

    try:
        tasks = [loop.create_task(run())]
        loop.run_until_complete(asyncio.wait(tasks))
    except KeyboardInterrupt:
        print("KeyboardInterrupt ...")
    finally:
        print("Omni shutting down")
        omni_conn.omni_shutdown()


async def add_dummy_user_tags(ov_server, ov_port, ov_user, ov_password):

    paths = [
        "/Users/arozantsev/tmp/Table_Internal.usd",
        "/Users/arozantsev/tmp/Bench_01_Low_Internal.usd",
    ]
    tags = [["furniture", "table"], ["furniture", "bench"]]

    # set connection arguments
    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    print(f"Omniverse args: {args}")
    with lu.print_wrapper(f"updating {len(paths)} paths"):
        async with (
            ou.omni_connection_wrapper(*args, timeout=60) as c,
            tu.TaggingClientContextAsync(ov_server) as client,
        ):
            for p, t in zip(paths, tags):
                await client.add_user_tags(c=c, paths=[p], tags=t)


async def recursive_list(c, path_list, logger=print, max_concurent_requests: int = 1):
    list_runner = 0
    paths = []

    while len(path_list[list_runner:]) > 0:
        if max_concurent_requests > 0:
            max_runner = list_runner + max_concurent_requests
        else:
            max_runner = None
        # create list of coocurent request to the server
        print(path_list[list_runner:max_runner])
        awaitables = [c.list(p + "/*", recursive=False, show_hidden=True) for p in path_list[list_runner:max_runner]]
        list_runner += len(awaitables)
        items_list = await asyncio.gather(*awaitables)

        # go through all the item lists from concurrent requests
        for items in items_list:
            # go through all the files
            for item in items:
                if item.status != omni_conn.OmniErrorType.kOmniErrorTypeOk:
                    continue
                if item.pathType == omni_conn.OmniPathType.kOmniPathTypeFolder:
                    path_list.append(item.path)
                else:
                    paths.append(item.path)
                    # print(
                    # f"hashValue: {item.hashValue}\n"
                    # f"onMount: {item.onMount}\n"
                    # f"etag: {item.etag}\n"
                    # f"access: {item.access}\n"
                    # f"connection: {item.connection}\n"
                    # f"createdBy: {item.createdBy}\n"
                    # f"createdTimestamp: {item.createdTimestamp}\n"
                    # f"empty: {item.empty}\n"
                    # f"eventType: {item.eventType}\n"
                    # f"hashBlockSize: {item.hashBlockSize}\n"
                    # f"hashType: {item.hashType}\n"
                    # f"hashValue: {item.hashValue}\n"
                    # f"modifiedBy: {item.modifiedBy}\n"
                    # f"modifiedTimestamp: {item.modifiedTimestamp}\n"
                    # f"path: {item.path}\n"
                    # f"pathType: {item.pathType}\n"
                    # f"serverTimestamp: {item.serverTimestamp}\n"
                    # f"size: {item.size}\n"
                    # f"status: {item.status}\n"
                    # f"statusDescription: {item.statusDescription}\n"
                    # )
                    # assert item.etag is None
                # break

        # make sure that there are not repeating paths in the set
        assert len(set(path_list)) == len(path_list), "File names should be unique"
        logger(f"Path list length: {len(path_list)}, number of files: {len(paths)}")

    return paths


async def get_recursive_list(args, path_list, logger=print, omni_conn_timeout=3600):

    with lu.print_wrapper("Getting a list of paths"):
        async with ou.omni_connection_wrapper(*args, timeout=omni_conn_timeout) as c:
            paths = await ou.recursive_list(c, path_list)  # , max_concurrent_requests=1)

    return paths


async def get_list_of_paths_mounts(ov_server, ov_port, ov_user, ov_password, path, logger=print):

    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    paths = await get_recursive_list(args, [path], logger)

    # get paths
    logger(f"Total number of paths: {len(paths)}")
    return paths


async def get_list_of_paths(args, namespace, filter_by, query_by_path=False, logger=print):
    with lu.print_wrapper("Getting a list of paths"):
        async with ou.omni_connection_wrapper(*args, timeout=60) as c:
            if query_by_path:
                items = await ou.recursive_list(c, ["/*"])
                # items = await c.list(filter_by + "/*", recursive=True, show_hidden=True)
                paths = []
                for item in items:
                    if item.status != omni_conn.OmniErrorType.kOmniErrorTypeOk:
                        continue
                    elif item.path.find(".usd") < 0 and item.path.lower().find(".obj") < 0:
                        continue
                    elif item.path.find(".tags") >= 0:
                        continue
                    paths.append(item.path)
            else:
                async with tu.TaggingClientContextAsync(args[0]) as client:
                    query_result = await client.query_paths(
                        c=c,
                        path=filter_by,
                        namespace=namespace,
                        return_tags=False,
                        return_values=False,
                        return_namespaces=False,
                    )
                # print(query_result)
                paths = query_result.paths

    logger(f"Total number of paths that will be updated: {len(paths)}")
    return paths


async def clean_appearance_inferred_namespaces_task(
    ov_server,
    ov_port,
    ov_user,
    ov_password,
    filter_by="/Users/arozantsev/Kitchen_set",
    namespace=".appearance.inferred",
    dry_run=True,
    query_by_path=False,
    batch_size: int = 25,
):

    # set connection arguments
    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    print(f"Omniverse args: {args}")
    new_paths = await get_list_of_paths(args, namespace, filter_by, query_by_path)

    if len(new_paths) > 0 and not dry_run:
        with lu.print_wrapper("Clearing namespaces"):
            async with (
                ou.omni_connection_wrapper(*args, timeout=60) as c,
                tu.TaggingClientContextAsync(ov_server) as client,
            ):
                cur = 0
                while cur < len(new_paths):
                    _ = await client.clear_namespaces(
                        c=c,
                        paths=new_paths[cur : cur + batch_size],
                        namespaces=[namespace],
                    )
                    cur += batch_size

    # check that the paths got cleaned
    new_paths = await get_list_of_paths(args, namespace, filter_by, query_by_path)


async def copy_old_user_tag_to_new_namespace(
    ov_server,
    ov_port,
    ov_user,
    ov_password,
    filter_by="/Users/arozantsev/Kitchen_set",
    dry_run=True,
    query_by_path=False,
):

    # set connection arguments
    args = (f"{ov_server}", f"{ov_port}", f"{ov_user}", f"{ov_password}")
    print(f"Omniverse args: {args}")
    new_paths = await get_list_of_paths(args, "appearance.user", filter_by, query_by_path=True)
    # new_paths = await get_list_of_paths(args, "appearance.user", filter_by, query_by_path)

    if len(new_paths) > 0:
        async with (
            ou.omni_connection_wrapper(*args, timeout=60) as c,
            tu.TaggingClientContextAsync(ov_server) as client,
        ):

            path_results = await client.read_tags_all_paths_v2(c=c, paths=new_paths)

            awaitables = []

            with lu.print_wrapper("updating paths", print_after=False):
                for path, result in zip(new_paths, path_results):
                    user_t, _ = tu.get_ns_tags(result, "appearance.user")
                    if len(user_t) == 0:
                        continue

                    if not dry_run:
                        awaitables.append(client.add_user_tags(c=c, paths=[path], tags=user_t))

                        if len(awaitables) >= 100:
                            _ = await asyncio.gather(*awaitables, return_exceptions=True)
                            awaitables = []

            if not dry_run:
                _ = await asyncio.gather(*awaitables, return_exceptions=True)
                awaitables = []

                new_path_results = await client.read_tags_all_paths_v2(c=c, paths=new_paths)

                with lu.print_wrapper("verifying paths", print_after=False):
                    for path, res, new_res in zip(new_paths, path_results, new_path_results):
                        user_t, _ = tu.get_ns_tags(res, "appearance.user")
                        if len(user_t) == 0:
                            continue
                        new_user_t, _ = tu.get_user_tags_ns(new_res)
                        try:
                            assert new_user_t == user_t, f"Error in {path}"
                        except Exception as e:
                            print(e)

            if not dry_run:
                with lu.print_wrapper("Cleaning old user tags"):
                    _ = await client.clear_namespaces(c=c, paths=new_paths, namespaces=["appearance.user"])

    # check that the paths got cleaned
    new_paths = await get_list_of_paths(args, "appearance.user", filter_by, query_by_path)
    # if dry_run:
    #     break


if __name__ == "__main__":
    """Execution command:

    $ OV_SERVER=ov-rc.nvidia.com python utility_scripts.py
    """

    connection_args = (
        os.getenv("OV_SERVER"),
        "3009",
        "deeptag_service",
        "deeptag_service_password",
    )

    # omni_exec(
    #     new_client_test,
    #     # new_client_sub_test,
    #     *connection_args,
    # )

    omni_exec(
        clean_appearance_inferred_namespaces_task,
        *connection_args,
        filter_by="/Users/arozantsev@nvidia.com",
        namespace=".debug.generated",
        dry_run=mu.str2bool(os.getenv("DRY_RUN", "True")),
        query_by_path=False,
    )

    # omni_exec(
    #     copy_old_user_tag_to_new_namespace,
    #     *connection_args,
    #     filter_by="/",
    #     dry_run=True
    # )
