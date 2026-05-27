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
import asyncio
import time
from itertools import chain
from types import AsyncGeneratorType
from typing import AsyncIterator, Dict, List, Optional, Tuple, Union

# local / proprietary modules
import omni.tagging.client as tc
from omni.discovery import DiscoverySearch
from omni.tagging.client._generated.data import GetTagsResult

from ... import datetime_utils as dtu
from ... import log_utils as lu
from .. import RemoteFilePath, RemoteFileUri, StorageClient
from ..data import TagAction, TagField, TagName, TagResultField, TagValue
from ..exceptions import AccessDeniedError
from ..utils import gen_wrapper
from . import DEPLOYMENT_LOOKUP, READ_BATCH_SIZE, logger
from .auth import NucleusAuth, NucleusAuthEnv
from .connection import get_path_from_uri
from .exceptions import StatusNotOk, TaggingClientConnectionError


def assert_status_ok_tagging(result: GetTagsResult) -> None:
    if result is None:
        raise ValueError("result is None")
    if result.status != tc.StatusCode.Ok:
        raise StatusNotOk(result)


def get_generated_ns(target_namespace: str) -> str:
    return f".{target_namespace}.generated"


def get_excluded_ns(target_namespace: str) -> str:
    return f".{target_namespace}.excluded"


class MyTCHelper(tc.TaggingClientHelper):
    async def _find_service(self, interface):
        logger.debug(f"Deployment lookup: {DEPLOYMENT_LOOKUP}")
        async with DiscoverySearch(self.server) as search:
            return await search.find(interface, meta={"deployment": DEPLOYMENT_LOOKUP})

    async def _create_interface(self, interface, fallback):
        try:
            return await asyncio.wait_for(self._find_service(interface), timeout=self.timeout)
        except Exception as e:
            logger.exception(e)
            transport = await self._get_transport(fallback)
            return interface(transport) if transport else None


class TaggingClientContextAsync:
    """Create a tag client context."""

    def __init__(self, ov_server):
        self.ov_server = ov_server

    async def init_client(self):
        """Create tagging client."""
        self.th = MyTCHelper(self.ov_server)
        # connect to the tagging service
        self.ts: tc.TaggingService = await self.th.get_tagging_service()
        # check that tagging server is responding
        res: tc.CreateClientResult = await self.ts.generate_client_id()
        # get the ID of the client (this will likely be deprecated)
        self.client_id = res.client_id

    async def close_client(self, client_msg: str = None, *args, **kwargs):
        """Close tagging client."""
        await self.th.__aexit__(*args, **kwargs)
        # log the given message on success
        if client_msg is not None:
            logger.debug(client_msg)

    async def __aenter__(self):
        """Create client and return context"""
        with lu.print_wrapper("client creation", logger=logger.debug):
            await self.init_client()

        logger.debug(f"Created tagging client: {self.client_id}")
        return self

    async def __aexit__(self, *args, **kwargs):
        """Close the client"""
        try:
            await self.close_client(client_msg="client closed")
        except Exception as e:
            logger.error(f"Error closing client: {str(e)}")

    async def tag_update_probe(
        self,
        storage_client: StorageClient,
        auth: Union[NucleusAuthEnv, NucleusAuth],
        probe_uri: Optional[RemoteFilePath] = None,
    ):
        if probe_uri is None:
            probe_uri = f"/Users/{auth.user}/system/tag_probe.txt"
        available, _ = await storage_client.check_if_exists(probe_uri)

        if not available:
            with lu.print_wrapper(
                f"'{probe_uri}' unavailable, creating..",
                print_after=False,
                logger=logger.info,
            ):
                await storage_client.upload_items_content(
                    item_dict={probe_uri: b"tag_crawler_probe"},
                )

        with lu.print_wrapper(
            f"sending tag update to {probe_uri}",
            print_after=False,
            logger=logger.debug,
        ):
            await self.add_tags_namespace(
                storage_client=storage_client,
                paths=[probe_uri],
                target_namespace=".ngsearch.system",
                tags_dict={"probe": dtu.date_from_timestamp(time.time())},
                action=TagAction.reset,
            )

    async def add_user_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        tags: list,
        action: TagAction = TagAction.reset,
        target_namespace: str = "appearance",
    ):
        """Add user tags to an asset path in omniverse.

        Args:
            c: omniverse connection
            client: tagging client
            paths: list of paths, which tags should be updated
            list tags: list of tags that need to be added to a path
        """
        assert isinstance(tags, list), f"passed input is of type: {type(tags)}, only list is supported"
        logger.debug(f"path: {paths}")
        logger.debug(f"action: {action}")
        namespaces = [target_namespace] * len(tags)
        values = [""] * len(tags)
        await self.tags_action(storage_client, paths, namespaces, tags, values, action=action)

    async def add_predicted_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        tags_dict: Dict[TagName, TagValue],
        target_namespace: str = "appearance",
    ):
        """Add generated tags to an asset path in omniverse.

        Args:
            c: omniverse connection
            client ([type]): tagging client
            paths (list): list of paths, which tags should be updated
            tags_dict (dict, optional): dictionary of tags and their probabilities as keys and values respectively. Defaults to None.
            target_namespace (str, optional): namespace, where tags will be added. Defaults to "appearance".
        """
        filt_tags = []
        filt_values = []
        for t, v in tags_dict.items():
            # remove trailing spaces
            t = t.strip()
            # check that the tag is not empty
            if t != "":
                filt_tags.append(t)
                filt_values.append(v)
        # copy namespaces the required number of times
        namespaces = [get_generated_ns(target_namespace)] * len(filt_tags)
        # reset tags
        await self.reset_tags(storage_client, paths, namespaces, tags=filt_tags, values=filt_values)

    async def clear_user_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        target_namespace: str = "appearance",
        **kwargs,
    ) -> None:
        """Clear the name space for the user tags.

        Args:
            c: omniverse connection
            client: tagging client
            paths (list): list of paths, which tags should be updated
            target_namespace (str, optional): namespace, where tags will be added. Defaults to "appearance".
        """
        namespaces = [f"{target_namespace}"] * len(paths)
        await self.clear_namespaces(storage_client, paths, namespaces, **kwargs)

    async def clear_predicted_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        target_namespace: str = "appearance",
        **kwargs,
    ) -> None:
        """Clear the name space for the generated tags.

        Args:
            c: omniverse connection
            client: tagging client
            paths (list): list of paths, which tags should be updated
            target_namespace (str, optional): namespace, where tags will be added. Defaults to "appearance".
        """
        namespaces = [get_generated_ns(target_namespace)] * len(paths)
        await self.clear_namespaces(storage_client, paths, namespaces, **kwargs)

    async def add_banned_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        tags: List[TagName],
        target_namespace: str = "appearance",
        **kwargs,
    ) -> None:
        """Add banned tags to an asset path in omniverse.

        Args:
            c: omniverse connection
            client: tagging client
            paths: list of paths, which tags should be updated
            list tags: list of tags that need to be added to a path
        """
        assert isinstance(tags, list), f"passed input is of type: {type(tags)}, only list is supported"
        namespaces = [get_excluded_ns(target_namespace)] * len(tags)
        values = [""] * len(tags)
        await self.add_tags(storage_client, paths, namespaces, tags, values, **kwargs)

    async def add_tags_namespace(
        self,
        storage_client: StorageClient,
        paths: List[RemoteFilePath],
        target_namespace: str,
        tags_dict: Dict[TagName, TagValue],
        action: TagAction = TagAction.add,
        **kwargs,
    ) -> None:
        """Add some tags in a given namespace to a list of paths.

        Args:
            c: omniverse connection
            client: tagging client
            paths: list of path for which embedding should be updated
            namespaces: list of namespaces, which need to be modified
            tags: list of tags that need to be modified
            values: list of values for tags that need to be set
        """
        tags = list(tags_dict.keys())
        values = list(tags_dict.values())
        namespaces = [target_namespace] * len(tags)

        # if reset is called with empty tags - clear the tags for a given namespaces
        if action == TagAction.reset and len(tags) == 0:
            tags = [None]
            values = [None]
            namespaces = [target_namespace]

        await self.tags_action(storage_client, paths, namespaces, tags, values, action=action, **kwargs)

    async def add_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        namespaces: List[str],
        tags: List[TagName],
        values: List[TagValue],
        **kwargs,
    ) -> None:
        """Add some tags in a given namespace to a list of paths.

        Args:
            c: omniverse connection
            client: tagging client
            paths: list of path for which embedding should be updated
            namespaces: list of namespaces, which need to be modified
            tags: list of tags that need to be modified
            values: list of values for tags that need to be set
        """
        await self.tags_action(
            storage_client,
            paths,
            namespaces,
            tags,
            values,
            action=TagAction.add,
            **kwargs,
        )

    async def clear_namespaces(
        self,
        storage_client: StorageClient,
        paths: List[str],
        namespaces: List[str],
        max_requests: int = 25,
        **kwargs,
    ) -> None:
        """Same as :py:func:`add_tags` but use ``reset`` operation from the tagging service."""

        assert len(paths) == len(namespaces), "Length of namespaces is not the same as length of path"

        cur = 0
        while cur < len(paths):
            p = paths[cur : cur + max_requests]
            tl = [tc.Tag(tag_namespace=ns) for ns in namespaces[cur : cur + max_requests]]

            try:
                _: tc.ModifyTagsResult = await self.ts.modify_tags(
                    auth_token=storage_client.connection.auth.auth_token,
                    client_id=self.client_id,
                    paths=p,
                    tags=tl,
                    modify_type=tc.TagModifyType.Reset,
                )
            except Exception as e:
                # process exception
                if str(e).find("connection closed abnormally [internal]") >= 0:
                    raise TaggingClientConnectionError("tagging service: unavailable")
                elif str(e).find("code = 1011 (unexpected error), no reason") >= 0:
                    raise TaggingClientConnectionError("tagging service: connection lost (websocket timeout)")
                else:
                    lu.prepare_message(
                        msg="Namespace cleaning fail:",
                        item_list=[f"number of paths: {len(p)}", f"Error: {str(e)}"],
                        logger=logger.exception,
                    )
                    # re-raise exception
                    raise e

            cur += max_requests

    async def reset_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        namespaces: List[str],
        tags: List[TagName],
        values: List[TagValue],
        **kwargs,
    ):
        """Same as :py:func:`add_tags` but use ``reset`` operation from the tagging service."""
        await self.tags_action(
            storage_client,
            paths,
            namespaces,
            tags,
            values,
            action=TagAction.reset,
            **kwargs,
        )

    async def set_tags(
        self,
        storage_client: StorageClient,
        paths: List[str],
        namespaces: List[str],
        tags: List[TagName],
        values: List[TagValue],
        **kwargs,
    ):
        """Same as :py:func:`add_tags` but use ``set`` operation from the tagging service."""
        await self.tags_action(
            storage_client,
            paths,
            namespaces,
            tags,
            values,
            action=TagAction.set,
            **kwargs,
        )

    async def tags_action(
        self,
        storage_client: StorageClient,
        paths: Union[List[RemoteFilePath], Tuple[RemoteFilePath], RemoteFilePath],
        namespaces: List[str],
        tags: Union[List[TagName], TagName],
        values: List[TagValue],
        action: TagAction = TagAction.add,
        max_requests: int = 100,
    ):
        """Call tagging service API and execute a given action.

        Args:
            c: omniverse connection
            client: tagging client
            paths: paths, to which the operation should be applied
            namespaces: namespaces that need to be modified
            tags: tags that need to be added
            values: values for tags that need to be added
            str action: action that needs to be executed
        """

        if not isinstance(paths, (list, tuple)):
            paths = [paths]
        if not isinstance(tags, list):
            tags = [tags]

        if len(tags) != len(namespaces) != len(values):
            raise ValueError(
                f"input lengths are inconsistent: {len(tags)} vs {len(namespaces)} vs {len(values)},"
                " which may lead to erroneous results"
            )

        # get a list of items that are going to be set
        tag_list = [tc.Tag(name=tg, tag_namespace=ns, value=val) for tg, ns, val in zip(tags, namespaces, values)]

        if action == TagAction.add:
            modify_type = tc.TagModifyType.Add
        elif action == TagAction.set:
            modify_type = tc.TagModifyType.Set
        elif action == TagAction.reset:
            modify_type = tc.TagModifyType.Reset
        elif action == TagAction.remove:
            modify_type = tc.TagModifyType.Remove
        else:
            raise NotImplementedError(f"provided action is currently not supported: ({action})")

        if max_requests is None or max_requests < 0:
            max_requests = len(paths)

        counter = 0
        while counter < len(paths):
            p = paths[counter : counter + max_requests]
            tl = tag_list[counter : counter + max_requests]

            try:
                res: tc.ModifyTagsResult = await self.ts.modify_tags(
                    auth_token=storage_client.connection.auth.auth_token,
                    client_id=self.client_id,
                    paths=p,
                    tags=tl,
                    modify_type=modify_type,
                )
                for r, path in zip(res["path_result"], p):
                    if tc.StatusCode.Denied in r["status"]:
                        raise AccessDeniedError(f"access to '{path}' denied")
            except Exception as e:
                # process exception
                if str(e).find("connection closed abnormally [internal]") >= 0:
                    raise TaggingClientConnectionError("tagging service: unavailable")
                elif str(e).find("code = 1011 (unexpected error), no reason") >= 0:
                    raise TaggingClientConnectionError("tagging service: connection lost (websocket timeout)")
                else:
                    # re-raise exception
                    lu.prepare_message(
                        msg="Tags modification fail:",
                        item_list=[
                            f"number of paths: {len(p)}",
                            f"number of tags: {len(tl)}",
                            f"modification type: {action.lower()}",
                            f"Error: {str(e)}",
                        ],
                        logger=logger.exception,
                    )
                    raise e
            # log result to debug channel
            logger.debug(f"action '{action}' applied to {len(p)} paths")
            counter += len(p)

    async def read_tags_all_paths_v2(
        self,
        storage_client: StorageClient,
        paths: Union[List[str], str],
        batch_size: int = READ_BATCH_SIZE,
        logging_timeout: float = 10,
    ) -> List[TagResultField]:
        """Read tags from omniverse using the Tagging API.

        Args:
            c: omniverse connection
            client: tagging service client
            paths: paths of omniverse objects for which tags needs be retrieved
            client: tagging client can be specified. [``Optional``]
            logger: function that logs the information. [``Optional``]
        """
        return list(
            chain.from_iterable(
                [
                    list_of_results
                    async for list_of_results in self.read_tags_all_paths_gen(
                        storage_client=storage_client,
                        paths=paths,
                        batch_size=batch_size,
                        logging_timeout=logging_timeout,
                    )
                ]
            )
        )

    async def read_tags_all_paths_gen_from_gen(
        self,
        storage_client: StorageClient,
        paths_gen: AsyncIterator[str],
        batch_size: int = READ_BATCH_SIZE,
    ) -> AsyncIterator[List[TagResultField]]:
        if not isinstance(paths_gen, AsyncGeneratorType):
            raise ValueError("Incorrect type: Async Generator expected")

        async def process_batch(paths: List[str]) -> List[TagResultField]:
            items = await self.ts.get_tags(auth_token=storage_client.connection.auth.auth_token, paths=paths)
            if isinstance(items, dict) and "path_result" in items:
                if len(items["path_result"]) != len(paths):
                    logger.warning(f"{len(items['path_result'])} vs {len(paths)}")
                return [
                    TagResultField(
                        tags=[
                            TagField(
                                name=t.name,
                                value=t.value,
                                tag_namespace=t.tag_namespace,
                            )
                            for t in p_res.tags
                        ],
                        uri=paths[j],
                    )
                    for j, p_res in enumerate(items["path_result"])
                ]
            else:
                logger.exception(f"Erroneous results from the tagging service: {items}")
                if str(items).find("connection closed abnormally") >= 0:
                    raise TaggingClientConnectionError("tagging service: unavailable")
                await asyncio.sleep(1)

        accum: List[str] = []
        async for r in paths_gen:
            accum.append(r)
            if len(accum) >= batch_size:
                yield await process_batch(accum)
                accum = []
        # yield result
        if len(accum) > 0:
            yield await process_batch(accum)

    async def read_tags_all_paths_gen(
        self,
        storage_client: StorageClient,
        paths: Union[
            List[Union[RemoteFilePath, RemoteFileUri]],
            Union[RemoteFilePath, RemoteFileUri],
        ],
        batch_size: int = READ_BATCH_SIZE,
        logging_timeout: float = 10,
    ) -> AsyncIterator[List[TagResultField]]:
        """Read tags from omniverse using the Tagging API.

        Args:
            c: omniverse connection
            client: tagging service client
            paths: paths of omniverse objects for which tags needs be retrieved
            client: tagging client can be specified. [``Optional``]
            logger: function that logs the information. [``Optional``]
        """
        # make sure that provided paths are formed in a list
        if not isinstance(paths, (list, tuple)):
            paths = [paths]

        async def generator() -> AsyncIterator[RemoteFilePath]:
            bg = time.time()
            for it, p in enumerate(paths):
                yield get_path_from_uri(p)

                if time.time() - bg > logging_timeout:
                    logger.info(f"reading paths: {100 * it / len(paths):.02f}% [{it} / {len(paths)}]")
                    bg = time.time()

        item: List[TagResultField]
        async for item in self.read_tags_all_paths_gen_from_gen(storage_client, generator(), batch_size=batch_size):
            yield item

    async def query_paths(
        self,
        storage_client: StorageClient,
        namespace: str = "",
        path: str = "",
        return_paths: bool = True,
        return_tags: bool = True,
        return_values: bool = True,
        return_namespaces: bool = True,
        exclude_hidden: bool = False,
        max_results: Optional[int] = None,
    ):
        query = tc.Query(path=path, tag_name="", tag_namespace=namespace, value="")
        ret_filter = tc.ReturnFilter(
            return_tags=return_tags,
            return_values=return_values,
            return_namespaces=return_namespaces,
            return_paths=return_paths,
            exclude_hidden=exclude_hidden,
        )

        query_result: tc.QueryResult = await self.ts.tag_query(
            auth_token=storage_client.connection.auth.auth_token,
            query=query,
            ret_filter=ret_filter,
            max_results=max_results,
        )

        return query_result

    async def read_tags(self, storage_client: StorageClient, path: str, **kwargs):
        """Read tags from the provided path:

        Args:
            c: omniverse connection
            client: tagging client
            path: path to the file in omniverse, whose tags need to be read
        """
        if isinstance(path, str):
            path = [path]
        elif isinstance(path, list):
            if len(path) > 1:
                logger.info(f"Taking only the first element from the provided list of '{len(path)}'")
            path = path[:1]
        else:
            raise TypeError(f"Incorrect input type: ({type(path)})")

        # read tags
        results = await self.read_tags_all_paths_v2(storage_client, path, **kwargs)
        # return the first element
        return results[0]

    def get_user_tags_ns(
        self, path_results: TagResultField, target_namespace: str = "appearance"
    ) -> Tuple[List[TagName], List[TagValue]]:
        """Get user-provided tags from the tagging service output."""
        return self.get_ns_tags(path_results, target_namespace)

    def get_inferred_tags_ns(
        self, path_results: TagResultField, target_namespace: str = "appearance"
    ) -> Tuple[List[TagName], List[TagValue]]:
        """Get generated tags from the tagging service output."""
        return self.get_ns_tags(path_results, get_generated_ns(target_namespace))

    def get_banned_tags_ns(
        self, path_results: TagResultField, target_namespace: str = "appearance"
    ) -> Tuple[List[TagName], List[TagValue]]:
        """Get excluded tags from the tagging service output."""
        return self.get_ns_tags(path_results, get_excluded_ns(target_namespace))

    def get_ns_tags(
        self, path_result: TagResultField, namespace: str, clean_empty: bool = True
    ) -> Tuple[List[TagName], List[TagValue]]:
        """Get tags from a specific namespace.

        Args:
            path_results: list or dict of path results for the tagging service
            str namespace: namespace for which tags should be read
            bool clean_empty: flag to ignore empty tags
        """

        tags, vals = [], []
        for tag in path_result.tags:
            if tag.tag_namespace == namespace:
                if not clean_empty or tag.name != "":
                    tags.append(tag.name)
                    # output tag when no value is found
                    if tag.value is not None:
                        vals.append(tag.value)
                    else:
                        logger.debug(f"Tag without value: {tag}")
                        vals.append("")
        return tags, vals


class TaggingClientSubContextAsync:
    """Subscription Create a tag client context."""

    def __init__(
        self,
        auth_token: str,
        ov_server: str,
        path: str,
        subscription_ready: Optional[asyncio.Event] = None,
        client_id: Optional[str] = None,
        **kwargs,
    ):
        self.ov_server = ov_server
        self.th = MyTCHelper(self.ov_server)
        # save the path
        self.path = path
        self.timeout = kwargs.get("timeout", None)
        self.subscription_ready = subscription_ready
        self.client_id = client_id
        self.client = None
        if self.client_id is None:
            self.client = TaggingClientContextAsync(ov_server=self.ov_server)
        self.auth_token = auth_token

    async def __aenter__(self):
        """Init tagging client, subscribe to path and return context."""
        with lu.print_wrapper("subscription creation", logger=logger.debug):
            if self.client_id is None:
                await self.client.init_client()

            client_id = self.client_id if self.client_id is not None else self.client.client_id

            self.tsub: tc.TagSubscription = await self.th.get_tag_subscription_service()

            # subscribe
            self.sub = gen_wrapper(
                self.tsub.subscribe(
                    auth_token=self.auth_token,
                    client_id=client_id,
                    query=tc.Query(path=self.path, tag_name="", tag_namespace="", value=""),
                )
            )

            # notify that the subscription is ready
            if self.subscription_ready is not None:
                self.subscription_ready.set()

        logger.debug(f"Initialized tagging client: {client_id}")

        # return subscription context
        return self

    async def __aexit__(self, *args, **kwargs):
        """CLose client."""
        try:
            await self.sub.aclose()
        except Exception as e:
            logger.error(f"Error closing subscription: {str(e)}")

        try:
            if self.client_id is None:
                await self.client.close_client(client_msg="subscription closed")
        except Exception as e:
            logger.error(f"Error closing client: {str(e)}")


def result_wrapper(result: Optional[tc.SubscriptionEvent] = None) -> TagResultField:
    """Wrapper to map results from the tagging service 2.0 to the tagging service 1.4 format."""

    if result is None:
        return None

    if result.status in [tc.StatusCode.Denied, tc.StatusCode.TokenExpired]:
        raise AccessDeniedError(f"Access denied: {result}")
    elif result.status != tc.StatusCode.Ok:
        raise StatusNotOk(f"Not Ok status: {result}")

    try:
        return TagResultField(
            tags=[TagField(name=t.name, value=t.value, tag_namespace=t.tag_namespace) for t in result.tags],
            uri=result.path,
            op=result.type,
        )
    except KeyError as e:
        msg = f"Unexpected tagging result format: missing Key: {str(e)}: {result}"
        logger.error(msg)
        raise KeyError(msg)
    except Exception as e:
        msg = f"Unexpected tagging result format: {str(e)}"
        logger.exception(msg)
        raise ValueError(msg)
