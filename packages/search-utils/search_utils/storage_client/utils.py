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
import logging

# standard modules
import os
import re
from functools import lru_cache, partial
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

# local / proprietary modules
from . import StorageClient
from .data import RemoteFilePath, RemoteFileUri, TagName, TagResults, TagValue

logger = logging.getLogger(__name__)


def is_correct_format(uri: str, formats_list: List[str] = []) -> bool:
    """Checks if the omniverse asset has correct file format or return ``True`` if the list is empty.

    Args:
        str uri: omniverse path
        List[str] exclude_list: List of file formats that can be processed by the server.
    """
    if "any" in formats_list:
        return True
    elif len(formats_list) > 0:
        _, tail = os.path.splitext(uri)
        return tail[1:].lower() in formats_list
    else:
        return True


def get_asset_thumb_path(
    path: Union[RemoteFileUri, RemoteFilePath],
    thumbs_loc: str = ".thumbs",
    thumbs_res: tuple = (256, 256),
    suffix: str = "",
) -> Union[RemoteFileUri, RemoteFilePath]:
    """Return path to the file on the local drive, where the asset is stored.

    Args:
        str path: path of the asset in omniverse
        str thumbs_loc: Location where the thumbnails are stored (default: '.thumbs')
        tuple thumbs_res: resolution of the thumbnails (default: (256, 256))
        str suffix: additional suffix that is appended to the file name. Defaults to "".

    Returns:
        str: Local path of the temporary asset storage
    """
    head, tail = os.path.split(path)
    # generate the location of the thumbnail
    return f"{head.rstrip('/')}/{thumbs_loc}/{thumbs_res[0]}x{thumbs_res[1]}/{tail}{suffix}.png"


def is_exclude_uri(uri: str, exclude_list: List[str]) -> bool:
    """Checks if the omniverse path is in the list of excluded paths.

    Args:
        str uri: omniverse path
        list exclude_list: List of paths that should be excluded from processing
    """
    return match_regex(uri, tuple([f".*{e}.*" for e in exclude_list])) is not None


@lru_cache
def get_regexp_pattern(regex_tuple: Tuple[str]) -> str:
    return f"(?:{'|'.join(regex_tuple)})"


def match_regex(input_str: str, regex_tuple: List[str]):
    """Check if input string matches any regex from the list.

    Args:
        str input_str: input string that needs to be checked
        list regex_list: list of regex expressions
    """
    # Check if string matches regex list
    return re.match(get_regexp_pattern(regex_tuple), input_str)


async def awe_list_wrapper(
    gen: AsyncGenerator, processing_fn: Optional[Union[Callable, Awaitable]] = None
) -> List[Any]:
    """For a given input asynchronous generator convert it to a list and apply processing if needed.

    Args:
        gen (AsyncGenerator): data generator.
        procesing_fn (Optional[Callable], optional): processing function that needs to be applied to data samples. Defaults to None.

    Returns:
        List[Any]: resulting list of processed items
    """
    if processing_fn is None:
        return [it async for it in gen]
    elif asyncio.iscoroutinefunction(processing_fn):
        return [await processing_fn(it) async for it in gen]
    elif isinstance(processing_fn, callable):
        return [processing_fn(it) async for it in gen]
    else:
        raise ValueError(f"Unknown processing_fn type: {type(processing_fn)}")


async def timeout_wrapper(awaitable, timeout: float = None, default_output=None, cancell_callback=None):
    """Wrap awaitable in a function that cancels it after timeout without throwing error.

    Args:
        awaitable: awaitable that needs to be wrapped
        float timeout: timeout for the awaitable
        default_output: output that is returned, when timeout is reached
        cancell_callback: callback that is executed when timeout is reached
    """
    if timeout is None:
        result = await awaitable
    else:
        task = asyncio.ensure_future(awaitable)
        done, _ = await asyncio.wait({task}, timeout=None)
        if task in done:
            result = await task
        else:
            if cancell_callback is not None:
                cancell_callback()
            await cancell_task(task, msg="Timeout reached")
            result = default_output

    return result


async def cancell_task(task, msg: str = ""):
    """Cancell task.

    Args:
        task: task that needs to be cancelled
        logger: logging function
        str msg: message that need to be printed to notify that the task is cancelled
    """

    # cancell task
    task.cancel()
    # logging
    logger.debug(f"task was canceled: due to '{msg}'")
    # finishing the task
    try:
        await asyncio.wait_for(task, timeout=0.1)
    except asyncio.TimeoutError:
        logger("Timeout exception")
    except asyncio.CancelledError:
        pass
    return None


class CombinedAsyncGen:
    """Asynchronous generator that combines results from a dictionary of asynchronous generators.

    Args:
        gen_dict (dict): Dictionary of asynchronous generators where values and keys are generators and their names respectively.
        stop_service_fn (callable, optional): Function that returns ``True`` if generator needs to be stopped. Defaults to ``None``.
    """

    def __init__(self, gen_dict: dict, stop_service_fn: callable = None):
        self.tasks = [
            {
                "name": name,
                "gen": gen,
                "task": f"task: {name}",
            }
            for name, gen in gen_dict.items()
        ]

        self.background_tasks: List[asyncio.Task] = []
        self.stop_service_fn = stop_service_fn
        self._queue = asyncio.Queue()
        asyncio.ensure_future(self.init_generator())

    async def __aenter__(self):
        return self

    def __aiter__(self):
        return self

    async def __aexit__(self, *args, **kwargs):
        # cancel leftover background tasks on exit
        for t in self.background_tasks:
            try:
                t.cancel()
            except Exception as e:
                logger.warning(f"CombinedAsyncGen background task cancellation error: {str(e)}")

    @property
    def stop_service(self) -> bool:
        """Returns ``True`` if generator needs to be stopped.

        Returns:
            bool: ``True`` if generator needs to be stopped.
        """
        if self.stop_service_fn is not None:
            stop_trigger = self.stop_service_fn()
        else:
            stop_trigger = False

        return stop_trigger or (all([t["task"] is None for t in self.tasks]) and self._queue.empty())

    async def __anext__(self):
        if self.stop_service:
            raise StopAsyncIteration("combined async generator completed")
        while not self.stop_service:
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=5)
            except asyncio.TimeoutError:
                logger.debug("Queue empty")

    async def init_generator(
        self,
    ):
        """Initialize child generators and run loop over them until finishing condition is satisfied."""

        async def gen_queue_exporter(task):
            async for it in task["gen"]:
                await self._queue.put(it)
            logger.info("%s is finished", task["name"])
            task["task"] = None

        self.background_tasks = []

        for t in self.tasks:
            self.background_tasks.append(asyncio.create_task(gen_queue_exporter(t)))


async def run_callable(func: Optional[Union[Awaitable, Callable]], *args, **kwargs) -> Any:
    if func is None:
        pass
    elif asyncio.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    elif isinstance(func, partial) and asyncio.iscoroutinefunction(func.func):
        return await func(*args, **kwargs)
    elif isinstance(func, Callable):
        return func(*args, **kwargs)
    else:
        raise ValueError(f"Unknown exception handler type: {type(func)}")


async def task_wrapper(task, name: str = "", **kwargs):
    """Run main task.

    Args:
        task: task that will be executed
        str name: name of the task
    """
    logger.debug(f"Task '{name}' created")
    try:
        await task(**kwargs)
    except Exception as e:
        logger.exception(f"Task '{name}' exception: {str(e)}")
        raise e


async def gen_wrapper(gen: AsyncGenerator, timeout: Optional[float] = 30):
    while True:
        try:
            task = asyncio.ensure_future(gen.__anext__())
            finished = False
            while not finished:
                done, _ = await asyncio.wait([task], timeout=timeout)
                list_done = list(done)
                if len(list_done) > 0:
                    yield await list_done[0]
                    finished = True
                else:
                    logger.debug("No updates: waiting..")
                    yield None
        except RuntimeError as e:
            logger.error(f"Runtime Error: {str(e)}")
        except StopAsyncIteration:
            logger.debug("List subscription terminated")
            break
        except Exception as e:
            logger.warning(f"Tagging client connection was lost: {str(e)}")
            break


def process_label_string(label_string: str, res_dict: Dict[TagName, TagValue]) -> Dict[TagName, TagValue]:
    """Process the string of predictions and create a dictionary from it."""
    if re.search(r" [^%]*%", label_string) is not None:
        label_string = label_string.replace(" (", "(")

    tags_prob = label_string.split(", ")
    for el in tags_prob:
        split_res = el.split("(")
        tag = split_res[0]
        prob = float(split_res[1].strip()[: split_res[1].find("%")]) / 100 if len(split_res) > 1 else 1
        res_dict[tag] = prob

    return res_dict


def get_tags_list(label_string: str) -> TagResults:
    """Extract tags with respective probabilities from the prediction string."""
    res_dict: Dict[TagName, TagValue] = process_label_string(label_string, {})
    res = TagResults(tag=[], value=[])
    for name, value in res_dict.items():
        res.tag.append(name)
        res.value.append(value)

    return res


def match_patterns(path: Union[RemoteFilePath, RemoteFileUri], patterns: Optional[List[str]] = None) -> bool:
    """Check if a file path matches one of the provided patterns

    Args:
        path (Union[RemoteFilePath, RemoteFileUri]): input path
        match_patterns (Optional[List[str]], optional): List of patterns that a string can match. Defaults to None.

    Returns:
        bool: _description_
    """
    if patterns is None:
        return False
    return len(patterns) > 0 and match_regex(path, tuple(patterns))


async def get_thumbnails_nucleus_style(
    storage_client: StorageClient,
    uri: RemoteFileUri,
    thumbnail_path_templates: Optional[List[str]] = None,
    thumbs_loc: str = ".thumbs",
    suffixes: Optional[List[str]] = None,
    res_map: Optional[List[Tuple[int, int]]] = None,
) -> List[str]:
    """Get thumbnails in nucleus style

    Args:
        uri: RemoteFileUri: input URI
        thumbnail_path_templates: Optional[List[str]]: list of thumbnail path templates
        thumbs_loc: str: location of the thumbnails
        suffixes: Optional[List[str]]: list of suffixes
        res_map: Optional[List[Tuple[int, int]]]: list of resolutions
    """
    if thumbnail_path_templates is not None:
        thumbnail_uris_list: List[str] = []
        folder_name, file_name = os.path.split(uri)
        for template in thumbnail_path_templates:
            template = template.format(folder_name=folder_name, file_name=file_name)
            async for result in storage_client.list_items(
                path_list=[f"{folder_name}/{thumbs_loc}"],
                recursive=True,
                ignore_patterns=None,
                show_hidden=True,
            ):
                if re.match(template, result.uri):
                    thumbnail_uris_list.append(result.uri)
    else:
        if suffixes is None:
            suffixes = ["", ".auto"]
        if res_map is None:
            res_map = [(138, 108), (256, 256)]

        thumbnail_uris_list = [
            storage_client.get_uri_from_path(
                get_asset_thumb_path(
                    storage_client.get_path_from_uri(uri),
                    thumbs_loc=thumbs_loc,
                    thumbs_res=resolution,
                    suffix=suffix,
                )
            )
            for suffix in suffixes
            for resolution in res_map
        ]

    return thumbnail_uris_list
