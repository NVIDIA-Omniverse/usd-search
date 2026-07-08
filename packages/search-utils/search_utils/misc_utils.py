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
import base64
import bz2
import ctypes
import hashlib
import inspect
import io
import json
import logging
import os
import pickle
import re
import shutil
import sys
import threading
import time
import zipfile
import zlib
from ast import literal_eval as make_tuple
from contextlib import contextmanager
from multiprocessing import Queue
from types import ModuleType
from typing import (
    Any,
    AsyncGenerator,
    AsyncIterator,
    Callable,
    Iterator,
    Optional,
    TypeVar,
    Union,
)

import numpy as np
import psutil
import yaml
from numpy.typing import NDArray

from . import secure_pickle
from .log_utils import prepare_message, print_wrapper
from .secure_pickle import CACHE_APPROVED_CLASSES

misc_utils_logger = logging.getLogger(__name__)

# Upper bound (bytes) on a single decompressed cache / farm payload. Caps the
# memory a zlib/bz2 decompression bomb can allocate (USDS-004). Generous enough
# for legitimate embedding / point-cloud / render payloads; override via env.
MAX_DECOMPRESSED_BYTES: int = int(os.environ.get("SEARCH_UTILS_MAX_DECOMPRESSED_BYTES", 2 * 1024**3))


T = TypeVar("T")


async def aiter_limit(iterator: AsyncIterator[T], limit: Optional[int] = None) -> AsyncIterator[T]:
    """
    A wrapper for async iterators limiting the number of iterations to {limit}
    """
    if limit is None or limit <= 0:
        async for r in iterator:
            yield r
    for _ in range(limit):
        try:
            yield await iterator.__anext__()
        except StopAsyncIteration:
            pass


def str2bool(s: Any) -> bool:
    """Convert input string to bool"""
    if isinstance(s, str):
        return s.lower() in ("true", "1")
    else:
        return s


# PIL module import handling
try:
    from PIL import Image
except ModuleNotFoundError:
    if not str2bool(os.getenv("PILLOW_UNAVAILABLE", "False")):
        misc_utils_logger.warning("Pillow module is not found, some functionality may not be available")
        os.environ["PILLOW_UNAVAILABLE"] = "True"


dfloat32 = np.dtype(">f4")


class tqdm_mock:
    def __init__(self, input: Iterator[T], **kwargs) -> None:
        self._input = input
        misc_utils_logger.warning("using TQDM module mock")

    def __iter__(self) -> T:
        for it in self._input:
            yield it


def numpy_to_bytestrings(np_array: np.ndarray) -> str:
    """Convert Numpy array to a bytestring

    Args:
        np_array (np.ndarray): input that requires conversion

    Returns:
        str: resulting byte string
    """
    b = np_array.tobytes()
    return b.decode("latin1")


def any_to_hash(input: Any) -> str:
    pickled_object = pickle.dumps(input)
    return hashlib.sha256(pickled_object).hexdigest()


def DL_to_LD(DL: dict) -> list:
    return [dict(zip(DL, t)) for t in zip(*DL.values())]


def LD_to_DL(LD: list) -> dict:
    if len(LD) > 0:
        return {k: [dic[k] for dic in LD] for k in LD[0]}
    else:
        return {}


def none_on_empty_string(input):
    if input == "":
        return None
    else:
        return input


def normalize_embedding(input):
    normalized = np.asarray(input, dtype=np.float32)
    normalized /= np.linalg.norm(normalized)
    return normalized


def base64_to_list(base64_string: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(base64_string), dtype=dfloat32).tolist()


def array_to_base64(arr: np.ndarray) -> str:
    return base64.b64encode(np.array(arr).astype(dfloat32)).decode("utf-8")


def image_to_base64(input, format: str = "JPEG") -> str:
    """Covert image to base64 format

    Args:
        input: PIL image type

    Returns:
        str: base64 encoding of an image
    """
    with io.BytesIO() as output:
        input.convert("RGB").save(output, format=format)
        content = base64.b64encode(output.getvalue()).decode("ascii")
    return content


def image_from_base64(input: str):
    msg = base64.b64decode(input.encode("ascii"))
    buf = io.BytesIO(msg)
    return Image.open(buf)


def progress(
    gen,
    timeout: float = 10,
    logger: callable = misc_utils_logger.info,
    desc: str = "",
    disabled: bool = False,
):
    """Show progress of the generator

    Args:
        gen: iterable
        timeout (float, optional): log progress every timeout seconds or every step if timeout < 0. Defaults to 10.
        logger (callable, optional): callable that logs progress. Defaults to misc_utils_logger.info.
        desc (str, optional): optional description of the progress bar. Defaults to "".
        disabled (bool, optional): if True - do not show progress. Defaults to `False`.

    Yields:
        item from the iterable
    """
    bg = time.time()
    try:
        total = len(gen)
    except Exception as e:
        misc_utils_logger.warning(f"Cannot estimate length: {str(e)}")
        total = None

    for count, item in enumerate(gen):
        yield item

        if not disabled and (time.time() - bg > timeout or timeout < 0):
            msg = f"{desc}: " if desc != "" else ""
            msg += f"{count + 1}"
            if total is not None:
                msg += f" / {total} [{get_percentage(count + 1, total):.02f}%]"
            # print progress
            logger(msg)
            bg = time.time()


def kill(proc_pid):
    """Kil process with its children

    Args:
        proc_pid: PID of the process
    """
    process = psutil.Process(proc_pid)
    for proc in process.children(recursive=True):
        proc.kill()
    process.kill()


def get_omni_hidden_file_path(path: str, hidden_folder: str = ".deeptag") -> str:
    """Get the name of the hidden folder in omniverse.

    Args:
        path (str): name of the file, for storing temporal data.
        hidden_folder (str, optional): name of the hidden folder that needs to be created. Defaults to '.deeptag'.

    Returns:
        str: path to the hidden file that will be created
    """
    return f"{os.path.dirname(path)}/{hidden_folder}/{os.path.basename(path)}"


def unzip_archive(src_path: str, dest_folder: str):
    """Unzip archive

    Args:
        src_path (str): path to an archive
        dest_folder (str): path to the output directory
    """
    with zipfile.ZipFile(src_path, "r") as zip_ref:
        zip_ref.extractall(dest_folder)


def zip_files(files_list: list, src_folder: str, dest: str):
    """[summary]

    Args:
        files_list (list): list of files that need to be added
        src_folder (str): source folder where the files are stored
        dest (str): name of the archive
    """
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zipF:
        # zip files into the model folder
        for fl in files_list:
            if os.path.exists(f"{src_folder}/{fl}"):
                zipF.write(f"{src_folder}/{fl}", fl)


@contextmanager
def clean_temporary_directory(dir_path: str):
    """Clean and remove output directory

    Args:
        dir_path (str): path to the directory that needs to be cleaned
    """
    clean_output_directory(dir_path)
    yield
    remove_directory(dir_path)


def remove_directory(dir_path: str):
    """Remove the entire directory, or log an error if operation failed."""
    try:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
    except Exception as e:
        misc_utils_logger.error(f"Could not remove the directory: {str(e)}")


def clean_output_directory(dir_path: str, recreate: bool = True):
    """Check if output directory exists and if yes remove it.

    Args:
        dir_path (str): path to directory that need to be cleaned
        recreate (bool, optional): if ``True`` - recreate directory. Defaults to ``True``.
    """
    remove_directory(dir_path)

    # recreate the output directory
    if recreate:
        os.makedirs(dir_path, exist_ok=True)


def str2dict(input):
    """If input type is string - try convert it to dictionary, otherwise return `input`."""
    if isinstance(input, str):
        json_acceptable_string = input.replace("'", '"')
        return json.loads(json_acceptable_string)
    else:
        return input


def str2list(input):
    """If input type is string - try convert it to dictionary, otherwise return `input`."""
    if isinstance(input, str):
        return list(make_tuple(input))
    else:
        return input


def float_or_none(input):
    """If input is of type :py:mod:`str` and is equal to None return `None`,
    otherwise convert to float.
    """
    if isinstance(input, str) and input.lower() == "none":
        return None
    else:
        return float(input)


def softmax(x):
    """Compute softmax values for each sets of scores in x."""
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()


def load_yaml_file(path: str, error_response: Optional[Any] = None):
    """Load yaml file.

    Args:
        path (str): Path to the yaml file
        error_response: response returned on error.. Defaults to ``None``.

    Returns:
        content of the yaml file
    """
    if path is not None and os.path.exists(path):
        with open(path, "r") as file:
            config = yaml.load(file, Loader=yaml.Loader)
    elif path is None:
        config = error_response
    else:
        misc_utils_logger.warning(
            "%s does not exist, returning %s",
            path,
            str(error_response if error_response is not None else "None"),
        )
        config = error_response
    return config


def merge_dicts(base_dict: dict, update_dict: dict, on_change_callback: callable = None) -> dict:
    """Merge dictionaries and execute callback on change

    Args:
        base_dict (dict): base dictionary that needs to be updated
        update_dict (dict): dictionary, which values should be added.
        on_change_callback (callable, optional): function that is executed on change. Defaults to ``None``.

    Returns:
        dict: resulting dictionary after merging
    """
    if base_dict is None:
        base_dict = {}
    elif not hasattr(base_dict, "items"):
        raise ValueError(f"Incorrect input type: {type(base_dict)}, dict expected")

    # res_dict = {**base_dict}
    for k, v in update_dict.items():
        if isinstance(v, dict):
            base_dict[k] = merge_dicts(base_dict.get(k, {}), v, on_change_callback)
        # added serialization to be able to easily compare nested iterable types
        # > TODO (arozantsev): maybe not the most elegant, may need to be fixed later
        elif any_to_string(base_dict.get(k)) != any_to_string(v):
            if on_change_callback is not None:
                on_change_callback(key=k, old=base_dict.get(k), new=v)
            base_dict[k] = v
    return base_dict


def merge_struct_with_dict(base_class: dict, update_dict: dict, on_change_callback: callable = None) -> dict:
    """Merge structure class with a dictionary and execute callback on change

    Args:
        base_class (s): base dictionary that needs to be updated
        update_dict (dict): dictionary, which values should be added.
        on_change_callback (callable, optional): function that is executed on change. Defaults to ``None``.

    Returns:
        dict: resulting dictionary after merging
    """
    for k, v in update_dict.items():
        if isinstance(v, dict):
            setattr(
                base_class,
                k,
                merge_dicts(getattr(base_class, k, {}), v, on_change_callback),
            )
        elif getattr(base_class, k, None) != v:
            if on_change_callback is not None:
                on_change_callback(key=k, old=getattr(base_class, k), new=v)
            setattr(base_class, k, v)
    return base_class


def get_percentage(value: Union[int, float], max_value: Union[int, float] = 1, eps: float = 1e-6) -> float:
    """Return percentage computed from provided values

    Args:
        value ([int, float]): value that need to be converted to percentage.
        max_value ([int, float], optional): maximum value. Defaults to ``1``.
        eps (float, optional): small number that is used when max_value is set to ``0``. Defaults to ``1e-6``.

    Returns:
        float: percentage computed from input values
    """
    if max_value == 0:
        misc_utils_logger.debug("Provided maximum value is '0'")
        max_value = eps

    return 100 * float(value) / float(max_value)


def get_percentage_string(value: Union[int, float], max_value: Union[int, float] = 1, eps: float = 1e-6) -> str:
    """Return percentage computed from provided values

    Args:
        value ([int, float]): value that need to be converted to percentage.
        max_value ([int, float], optional): maximum value. Defaults to ``1``.
        eps (float, optional): small number that is used when max_value is set to ``0``. Defaults to ``1e-6``.

    Returns:
        float: percentage computed from input values
    """
    return f"{value} / {max_value} [{get_percentage(value, max_value, eps):.02f}%]"


def check_dict_field(
    dictionary: dict,
    keys: list,
    msg: str = "key '{}' is missing in dictionary",
    on_error_action: str = "exception",
):
    """Check that a list of keys is in the dictionary

    Args:
        dictionary (dict): dictionary that should contain a list of keys.
        fields (list): list of keys that need to be present in the dictionary
        msg (str, optional): messge printed if key is not found. Defaults to "key '{}' is missing in dictionary".
        on_error_action (str, optional): action that will be taken on missing key error. Defaults to "exception".

    Raises:
        KeyError: when key is not found and on_error_action is set to ``exception`` mode.
    """
    if isinstance(keys, str):
        keys = [keys]

    dict_keys = set(list(dictionary.keys()))

    for k in keys:
        if k not in dict_keys:
            msg = msg.format(k)
            if on_error_action == "exception":
                raise KeyError(msg)
            else:
                if on_error_action != "skip":
                    misc_utils_logger.error("unknown action type")
                misc_utils_logger.warm(msg)


def combine_outputs(prev_val: Any, new_val: Any, on_unknown_action: str = "replace") -> Any:
    """Combine results from inputs.

    Args:
        prev_val (Any): value that need to be updated
        new_val (Any): update value
        on_unknown_action (str, optional): action that needs to be taken,
            when data type is unknown. Defaults to "replace".

    Raises:
        TypeError: if update value is of type dict and existing value is of any other type.

    Returns:
        Any: resulting value after merging the results
    """

    prepare_message(
        msg="combining values",
        item_list=[
            f"prev: {prev_val}",
            f"new: {new_val}",
            f"unknown action: {on_unknown_action}",
        ],
        logger=misc_utils_logger.debug,
    )

    processed = False
    if prev_val is not None:
        if isinstance(new_val, str):
            prev_val += ", " + new_val
            processed = True
        elif isinstance(new_val, list):
            prev_val += new_val
            processed = True
        elif isinstance(new_val, dict):
            if not isinstance(prev_val, dict):
                raise TypeError(f"incompatible element type: {type(prev_val)} (expected: 'dict')")
            for k in new_val.keys():
                prev_val[k] = combine_outputs(prev_val.get(k), new_val[k], on_unknown_action=on_unknown_action)
            processed = True

    if not processed:
        if prev_val is not None:
            misc_utils_logger.warning(f"unknown format: {type(new_val)}, action: {on_unknown_action}")
        if on_unknown_action == "replace":
            prev_val = new_val
        elif on_unknown_action == "ignore":
            pass
        else:
            pass
    return prev_val


def array_to_string(input_array: Optional[NDArray[Union[np.int64, np.float32]]]) -> str:
    """Convert an input 1D array to string

    Args:
        input ([type]): input array

    Returns:
        str: string representation of the input array
    """
    if input_array is None:
        content = None
    else:
        content = np.asarray(input_array, dtype=float).tolist()

    return json.dumps(content)


def any_to_string(input: Any) -> str:
    """Encode any data to string

    Args:
        input (Any): any data

    Returns:
        str: encoded string
    """
    return pickle.dumps(input).decode("latin1")


def any_from_string(input: str, approved_imports: Optional[dict] = None) -> Any:
    """Deserialize data from string using an allowlist-restricted unpickler.

    Args:
        input (str): input string
        approved_imports (Optional[dict]): per-module import allowlist passed to
            the restricted unpickler. Defaults to ``CACHE_APPROVED_CLASSES``
            (data containers + numpy); widen deliberately if a cache stores
            additional non-callable types.

    Returns:
        Any: data decoded from string
    """
    return secure_pickle.loads(
        input.encode("latin1"),
        approved_imports=CACHE_APPROVED_CLASSES if approved_imports is None else approved_imports,
    )


def get_compression_method(compression_type: str) -> ModuleType:
    if compression_type == "none":
        return None
    if compression_type == "zlib":
        return zlib
    if compression_type == "bz2":
        return bz2
    raise NotImplementedError(f"compression method: {compression_type} is not supported")


def compress_data(input, compress: bool = True, compression_type: str = "zlib") -> str:
    """Serialize numpy data using :func:`pickle.dumps` functionality"""
    serialized = pickle.dumps(input)
    if compress and compression_type != "none":
        with print_wrapper("compressing", logger=misc_utils_logger.debug):
            compression_method = get_compression_method(compression_type)
            compressed = compression_method.compress(serialized)
        prepare_message(
            item_list=[
                f"serialized: {sys.getsizeof(serialized) / 1024 / 1024:.02f} Mb",
                f"compressed: {sys.getsizeof(compressed) / 1024 / 1024:.02f} Mb",
            ],
            logger=misc_utils_logger.debug,
        )
        return compressed.decode("latin1")
    else:
        return serialized.decode("latin1")


def _decompress_bounded(data: bytes, compression_type: str, max_output_bytes: int) -> bytes:
    """Decompress ``data`` while capping the output size.

    Uses incremental decompressors so a decompression bomb cannot allocate
    unbounded memory before the limit is noticed — the read stops as soon as
    more than ``max_output_bytes`` would be produced and raises ``ValueError``.
    """
    if compression_type == "zlib":
        decompressor = zlib.decompressobj()
    elif compression_type == "bz2":
        decompressor = bz2.BZ2Decompressor()
    else:
        raise NotImplementedError(f"compression method: {compression_type} is not supported")

    # Request one byte past the cap so an over-limit payload is detectable.
    out = decompressor.decompress(data, max_output_bytes + 1)
    if len(out) > max_output_bytes:
        raise ValueError(
            f"decompressed payload exceeds the {max_output_bytes}-byte cap " "(possible decompression bomb)"
        )
    # A well-formed payload is fully consumed in a single bounded read; leftover
    # input means the stream did not terminate within the cap.
    if getattr(decompressor, "unconsumed_tail", b"") or not getattr(decompressor, "eof", True):
        raise ValueError(
            f"decompressed payload exceeds the {max_output_bytes}-byte cap " "(possible decompression bomb)"
        )
    return out


def decompress_data(
    input: str,
    compress: bool = True,
    compression_type: str = "zlib",
    approved_imports: Optional[dict] = None,
    max_output_bytes: int = MAX_DECOMPRESSED_BYTES,
) -> Any:
    """Deserialize numpy data using an allowlist-restricted unpickler.

    Args:
        input: latin1-encoded (optionally compressed) pickled payload.
        compress / compression_type: as written by :func:`compress_data`.
        approved_imports: per-module import allowlist for the restricted
            unpickler; defaults to ``CACHE_APPROVED_CLASSES``.
        max_output_bytes: upper bound on the decompressed size, guarding
            against decompression-bomb OOM (USDS-004).
    """
    input = input.encode("latin1")
    if compress and compression_type != "none":
        with print_wrapper("decompressing", logger=misc_utils_logger.debug):
            input = _decompress_bounded(input, compression_type, max_output_bytes)
    return secure_pickle.loads(
        input,
        approved_imports=CACHE_APPROVED_CLASSES if approved_imports is None else approved_imports,
    )


def clean_queue(queue: Queue):
    """Clean the data queue.

    Args:
        queue (Queue): queue that needs to be cleaned
    """
    while not queue.empty():
        try:
            queue.get_nowait()
        except Exception:
            continue


async def concurrent_processor(
    proc_fn: callable,
    input_list: list,
    max_concurrent_requests: int = 5,
    log_timeout: float = 5,
    process_results_fn: callable = None,
    logging_fn: callable = None,
):
    """Process several request concurrently.

    Args:
        proc_fn (callable): awaitable function that does processing of the item in the list.
        input_list (list): list of items that need to be processed.
        max_concurrent_requests (int, optional): Maximum number of concurrent requests. Defaults to 5.
        log_timeout (float, optional): logging timeout. Defaults to 5.
        process_results_fn (callable, optional): function that processes results from the awaitables. Defaults to None.
        logging_fn (callable, optional): logging function that notifies about the progress. Defaults to None.
    """
    runner = 0
    max_items = len(input_list)
    bg = time.time()

    while len(input_list[runner:]) > 0:
        if max_concurrent_requests > 0:
            max_runner = runner + max_concurrent_requests
        else:
            max_runner = None

        # create list of coocurent request to the server
        awaitables = [proc_fn(it) for it in input_list[runner:max_runner]]
        # update runner
        runner += len(input_list[runner:max_runner])
        # wait for awaitables to finish
        items_list = await asyncio.gather(*awaitables)
        # process results from awaitables
        if process_results_fn is not None:
            process_results_fn(items_list)
        # log progress
        if time.time() - bg > log_timeout:
            if logging_fn is not None:
                logging_fn(runner, max_items)
            bg = time.time()


class fetch_wrapper:
    """Wrapper around async generator of the tagging service 2.0 to have the same API as tagging 1.4."""

    def __init__(self, gen):
        self.gen: AsyncGenerator = gen

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(self, *args, **kwargs):
        misc_utils_logger.debug("finishing fetch wrapper")
        try:
            await self.gen.aclose()
        except Exception as e:
            misc_utils_logger.warning("Generator cancellation error: %s", str(e))

    async def fetch(self):
        """Fetch next item from the subscription"""
        # try:
        return await self.gen.__anext__()
        # except StopAsyncIteration:
        #     return


def parse_env_variables(prefix: str = "ES_") -> dict:
    """Parse environment variables and for those that have prefix - construct
    them in the dict.

    Args:
        prefix (str, optional): Prefix for filtering environment variables. Defaults to "ES_".

    Returns:
        dict: dictionary parsed from environment variables.
    """
    env_dict = {}
    for k, v in sorted(os.environ.items()):
        if k.startswith(prefix):
            env_dict[k[len(prefix) :].lower()] = v

    return env_dict


def while_exception_wrapper(
    proc_fn: Callable,
    max_retries: int = 100,
    exception_handler: Optional[Callable] = None,
):
    except_counter = 0
    executed_with_no_errors = False
    while not executed_with_no_errors:
        try:
            res = proc_fn()
            executed_with_no_errors = True
        except Exception as exc:
            if max_retries < 0 or except_counter < max_retries:
                except_counter += 1
                exception_handler(exc)
            else:
                raise Exception(exc) from exc
    return res


def create_asyncio_loop() -> asyncio.AbstractEventLoop:
    """Get asyncio loop or create a new one

    Returns:
        asyncio.AbstractEventLoop: asyncio loop
    """
    if asyncio.get_event_loop().is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
    return asyncio.get_event_loop()


def start_background_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Start asyncio loop in the background

    Args:
        loop (asyncio.AbstractEventLoop): asyncio loop
    """
    asyncio.set_event_loop(loop)


def _this_func_name():
    return inspect.stack()[1][3]


class event_context:
    def __init__(self, event: asyncio.Event):
        """Event context wrapper. Clears the event and waits until it is set again.

        Args:
            event (asyncio.Event): async event
        """
        self.event = event

    async def __aenter__(
        self,
    ):
        self.event.clear()
        return self

    async def __aexit__(self, *args, **kwargs):
        await self.event.wait()


class KillableThread(threading.Thread):
    def get_id(self):
        # returns id of the respective thread
        if hasattr(self, "_thread_id"):
            return self._thread_id
        for id, thread in threading._active.items():
            if thread is self:
                return id

    def kill(self):
        thread_id = self.get_id()
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, ctypes.py_object(SystemExit))
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            misc_utils_logger.error("Exception raise failure")


def remove_brackets(input_string: str) -> str:
    """Remove brackets from input string"""
    # remove openning and closing brackets and replace them with spaces
    input = re.sub("(?:\\(+|\\)+)", " ", input_string)
    # clean repeating spaces from the tag
    input = re.sub(" +", " ", input_string)
    return input
