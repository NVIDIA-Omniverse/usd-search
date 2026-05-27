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
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Tuple, Union

import numpy as np
from aiohttp.client_exceptions import ClientOSError, ServerDisconnectedError
from deepsearch_utils.farm.client import K8sRenderer, _FarmClient
from deepsearch_utils.farm.data import (
    EmptyScene,
    FarmTimeoutError,
    LoadError,
    RenderingError,
    TaskSubmissionError,
)
from deepsearch_utils.misc_utils import strip_alpha_channel
from deepsearch_utils.rendering_service.client import RenderingServiceClient
from opentelemetry import trace
from PIL import Image

from search_utils.log_utils import prepare_message, print_wrapper, set_simple_logger
from search_utils.misc_utils import remove_directory

rendering_utils_logger = set_simple_logger("rendering utils", os.getenv("RENDERING_UTILS_LOGLEVEL", "INFO"))
tracer = trace.get_tracer(__name__)
RENDERING_REQUEST_TIMEOUT = float(os.getenv("RENDERING_REQUEST_TIMEOUT", "-1"))

# location where to store temporary USD data
usd_tmp_folder = os.getenv("USD_TEMP_DIR")
if not usd_tmp_folder:
    usd_tmp_folder = os.getenv("OMNI_RENDER_TEMP_DIR")
    if usd_tmp_folder is not None:
        rendering_utils_logger.warning("'OMNI_RENDER_TEMP_DIR' is deprecated, use 'USD_TEMP_DIR' instead.")
    else:
        usd_tmp_folder = f"{os.path.abspath(os.path.dirname(__file__))}/../tmp"


class RenderingStatus(str, Enum):
    success = "success"
    incorrect_format = "incorrect_format"
    error = "error"
    connection_error = "connection_error"
    timeout_error = "timeout_error"
    empty_scene = "empty_scene"
    rendering_error = "rendering_error"
    load_error = "load_error"


@dataclass
class PointCloudField:
    data: np.ndarray = None
    info: dict = None


def subsample(p: PointCloudField, n_points: int):
    if p.data.shape[0] > 0:
        return p.data[np.random.choice(range(p.data.shape[0]), int(n_points))]
    else:
        return p.data


def pointcloud_subsampler(input: List[dict], n_points: int):
    if n_points > 0:
        return [subsample(PointCloudField(**p), n_points) for p in input]
    else:
        return [PointCloudField(**p).data for p in input]


async def render_with_fields_async(
    client: Union[_FarmClient, K8sRenderer, RenderingServiceClient],
    path: str,
    fields: List[str] = ["images", "camera_metadata"],
):
    """Request rendering of image from the rendering client."""
    content = await client.render(uri=path, fields=fields)
    return {k: content[k] for k in fields}


async def render_usd_file_async(client: Union[_FarmClient, K8sRenderer, RenderingServiceClient], path: str):
    """Request rendering of image from the rendering client."""
    return (await client.render(uri=path, fields=["images"]))["images"]


async def save_camera_metadata_async(client: Union[_FarmClient, K8sRenderer, RenderingServiceClient], path: str):
    res = await client.render(uri=path, fields=["camera_metadata"])
    return res["camera_metadata"]


async def get_usd_pointcloud_async(
    client: Union[_FarmClient, K8sRenderer, RenderingServiceClient],
    path: str,
    n_points: int = -1,
):
    """Request getting the pointcloud from the rendering client."""
    if isinstance(client, RenderingServiceClient):
        raise NotImplementedError("RenderingServiceClient is not supported for getting pointcloud")

    content = await client.render(uri=path, fields=["pointcloud"])
    return pointcloud_subsampler(content["pointcloud"], n_points=n_points)


async def segment_usd_file_async(client: Union[_FarmClient, K8sRenderer, RenderingServiceClient], path: str):
    """Request rendering of image from the rendering client.

    Args:
        client (icu.RenderingClient): rendering client
        path (str): path to usd file

    Returns:
        icu.AssetContent: compressed segmentation of the asset
    """
    if isinstance(client, RenderingServiceClient):
        raise NotImplementedError("RenderingServiceClient is not supported for segmenting USD file")

    return (await client.render(uri=path, fields=["segmentation"]))["segmentation"]


async def combiner_async(
    client: Union[_FarmClient, K8sRenderer],
    path: str,
    func_dict: Dict[str, Callable] = {},
) -> Dict[str, Any]:
    """Applies multiple rendering functions to an asset.

    Args:
        client (FarmClient): Rendering client
        path (str): path to the USD file.
        func_dict (dict, optional): dictionary of functions that return ``icu.AssetContent``. Defaults to {}.

    Returns:
        dict: content
    """
    output_dict: Dict[str, Any] = {"usd_path": path}
    for k, fn in func_dict.items():
        content = await fn(client, path)
        output_dict[k] = content

    return output_dict


def clean_up(folder: str = usd_tmp_folder) -> bool:
    """Cleaning function that can be used to remove all temporary files."""
    return remove_directory(folder)


def res_map(res: int) -> Tuple[int, int]:
    if res == 108:
        return (138, 108)
    elif res == 256:
        return (256, 256)
    else:
        rendering_utils_logger.error("Unknown resolution: %s", str(res))
        raise NotImplementedError(f"Unknown resolution: {res}")


async def get_omni_file_renderings(
    data: List[Dict[str, Any]],
    formats: List[str],
    data_types: List[str],
    client: Union[_FarmClient, K8sRenderer],
    rendering_fn: Callable[[_FarmClient | K8sRenderer, str], Any] = render_usd_file_async,
    plugin_name: str = "unknown plugin",
    field: str = "images",
    **kwargs,
) -> Tuple[List[dict], List[int], Dict[int, dict]]:
    """Get path for assets from omniverse from the data (received from the socket) and send to the rendering job.

    Args:
        list data: list of dictionaries with the data for each sample
        list formats: list of the sample formats
        list data_types: list of supported data types
        config: service configuration
        dict batch_data_dict: dictionary of data, where content might be stored
        str plugin_name: name of the plugin that uses this fucntionality
        str usd_tmp_folder: temporary folder for storing USD files
    """
    assert len(data) == len(
        formats
    ), f"Number of data samples does not match number of formats: ({len(data)} v {len(formats)})"

    # initialize lists
    batch_data, indices, error_indices = [], [], {}

    async def sample_processing_fn(item_index: int, item: dict, fmt: str) -> dict:
        # check that the format is correct
        if fmt not in data_types:
            rendering_utils_logger.info(
                "Skipping %s: format '%s' not in supported types %s",
                item.get("omni_path", "unknown"),
                fmt,
                data_types,
            )
            return {"status": RenderingStatus.incorrect_format.value}

        # prepare the data sample
        b_data = dict()

        try:
            with tracer.start_as_current_span("rendering_utils.get_omni_file_renderings") as span:
                span.set_attribute("item_index", item_index)
                span.set_attribute("item", item["omni_path"])
                span.set_attribute("fmt", fmt)
                b_data[field] = await asyncio.wait_for(
                    rendering_fn(client=client, path=item["omni_path"]),
                    timeout=(RENDERING_REQUEST_TIMEOUT if RENDERING_REQUEST_TIMEOUT > 0 else None),
                )

        except TaskSubmissionError:
            rendering_utils_logger.warning("Task submission error (likely Kit Farm is unavailable)")
            return {
                "status": RenderingStatus.connection_error.value,
                "index": item_index,
            }

        except asyncio.TimeoutError:
            if RENDERING_REQUEST_TIMEOUT > 0:
                rendering_utils_logger.warning(
                    "Rendering function did not finish within %.02fs, likely farm unavailable",
                    RENDERING_REQUEST_TIMEOUT,
                )
            else:
                rendering_utils_logger.exception(
                    "Rendering function timed out internally (farm client timeout), likely farm unavailable"
                )
            return {
                "status": RenderingStatus.connection_error.value,
                "index": item_index,
            }

        except ConnectionError:
            rendering_utils_logger.warning("ConnectionError, likely Farm queue or Cache service are unavailable")
            return {
                "status": RenderingStatus.connection_error.value,
                "index": item_index,
            }

        except EmptyScene:
            rendering_utils_logger.warning("Empty Scene for %s", item["omni_path"])
            return {"status": RenderingStatus.empty_scene.value, "index": item_index}

        except LoadError:
            rendering_utils_logger.warning("Load error for %s", item["omni_path"])
            return {"status": RenderingStatus.load_error.value, "index": item_index}

        except FarmTimeoutError:
            rendering_utils_logger.warning("Timeout reached for %s", item["omni_path"])
            return {"status": RenderingStatus.timeout_error.value, "index": item_index}

        except RenderingError as e:
            if e.content.get("status") == RenderingStatus.empty_scene.value:
                return {
                    "status": RenderingStatus.empty_scene.value,
                    "index": item_index,
                }

            prepare_message(
                msg="Rendering Error",
                item_list=[f"{k}: {v}" for k, v in e.content.items()],
                logger=rendering_utils_logger.warning,
            )
            return {
                "status": RenderingStatus.rendering_error.value,
                "index": item_index,
            }

        except ServerDisconnectedError as e:
            rendering_utils_logger.warning("Server disconnected error for %s", item["omni_path"])
            raise ConnectionError("Server disconnected error") from e

        except ClientOSError as e:
            rendering_utils_logger.warning("Client OSError for %s", item["omni_path"])
            raise ConnectionError("Client OSError") from e

        except Exception as e:
            rendering_utils_logger.exception(str(e))
            return {"status": RenderingStatus.error.value, "index": item_index}

        # add omni_path field to the output
        b_data["omni_path"] = item["omni_path"]

        return {
            "status": RenderingStatus.success.value,
            "data": b_data,
            "index": item_index,
        }

    # run multiple rendering requests in parallel
    with print_wrapper(
        f"{plugin_name}: rendering data [{len(data)}]",
        print_after=False,
        logger=rendering_utils_logger.debug,
    ):
        results = await asyncio.gather(
            *[
                sample_processing_fn(item_index, item, fmt)
                for item_index, item, fmt in zip(range(len(data)), data, formats)
            ]
        )

    # process results
    for r in results:
        if r["status"] == RenderingStatus.success.value:
            batch_data.append(r["data"])
            indices.append(r["index"])
        elif r["status"] == RenderingStatus.connection_error.value:
            raise ConnectionError("Farm was not available")
        elif r["status"] == RenderingStatus.incorrect_format.value:
            continue
        else:
            error_indices.update({r["index"]: {"status": f"{r['status']}"}})

    return batch_data, indices, error_indices


def check_colors(input):
    input = strip_alpha_channel(np.asarray(input, dtype=np.float32))
    if np.max(input) > 1:
        input = input / 255
    return input


def rgb_to_xyz(srgb):
    """
    Conversion of the sRGB to XYZ. Follows the transformation described on the following `web page <http://www.brucelindbloom.com/index.html?Eqn_RGB_to_XYZ.html>`_
    """
    srgb = check_colors(srgb)
    srgb_pixels = srgb.reshape(-1, 3)
    linear_mask = np.asarray(srgb_pixels <= 0.04045, dtype=np.float)
    exponential_mask = np.asarray(srgb_pixels > 0.04045, dtype=np.float32)
    rgb_pixels = (srgb_pixels / 12.92 * linear_mask) + (((srgb_pixels + 0.055) / 1.055) ** 2.4) * exponential_mask
    rgb_to_xyz = np.asarray(
        [
            #    X        Y          Z
            [0.412453, 0.212671, 0.019334],  # R
            [0.357580, 0.715160, 0.119193],  # G
            [0.180423, 0.072169, 0.950227],  # B
        ]
    )
    xyz_pixels = np.matmul(rgb_pixels, rgb_to_xyz)
    return xyz_pixels.reshape(srgb.shape)


# XYZ to sRGB


def xyz_to_rgb(xyz):
    """
    Conversion of the XYZ to sRGB. Follows the transformation described on the following `web page <http://www.brucelindbloom.com/index.html?Eqn_XYZ_to_RGB.html>`_
    """
    xyz_pixels = xyz.reshape(-1, 3)
    xyz_to_rgb = np.asarray(
        [
            #     r           g          b
            [3.2404542, -0.9692660, 0.0556434],  # x
            [-1.5371385, 1.8760108, -0.2040259],  # y
            [-0.4985314, 0.0415560, 1.0572252],  # z
        ]
    )
    rgb_pixels = np.matmul(xyz_pixels, xyz_to_rgb)
    # avoid a slightly negative number messing up the conversion
    rgb_pixels[rgb_pixels < 0] = 0

    linear_mask = np.asarray(rgb_pixels <= 0.0031308, dtype=np.float)
    exponential_mask = np.asarray(rgb_pixels > 0.0031308, dtype=np.float)
    srgb_pixels = (rgb_pixels * 12.92 * linear_mask) + ((rgb_pixels ** (1.0 / 2.4) * 1.055) - 0.055) * exponential_mask

    return srgb_pixels.reshape(xyz.shape)


def xyz_to_lab(xyz):
    """
    Conversion of the XYZ to CIE Lab. Follows the transformation described on the following `web page <http://www.brucelindbloom.com/index.html?Eqn_XYZ_to_Lab.html>`_
    """
    xyz = check_colors(xyz)

    xyz_pixels = xyz.reshape([-1, 3])
    # convert to fx = f(X/Xn), fy = f(Y/Yn), fz = f(Z/Zn)
    # normalize for D65 white point
    xyz_normalized_pixels = np.multiply(xyz_pixels, [1.0 / 0.950456, 1.0, 1.0 / 1.088754])

    epsilon = 6.0 / 29.0
    linear_mask = np.asarray(xyz_normalized_pixels <= (epsilon**3), dtype=np.float32)
    exponential_mask = np.asarray(xyz_normalized_pixels > (epsilon**3), dtype=np.float32)
    fxfyfz_pixels = (xyz_normalized_pixels / (3.0 * epsilon**2) + 4.0 / 29.0) * linear_mask + (
        xyz_normalized_pixels ** (1.0 / 3.0)
    ) * exponential_mask

    # convert to lab
    fxfyfz_to_lab = np.asarray(
        [
            #  l       a       b
            [0.0, 500.0, 0.0],  # fx
            [116.0, -500.0, 200.0],  # fy
            [0.0, 0.0, -200.0],  # fz
        ]
    )
    lab_pixels = np.matmul(fxfyfz_pixels, fxfyfz_to_lab) + np.asarray([-16.0, 0.0, 0.0])

    return lab_pixels.reshape(xyz.shape)


def hex_to_rgb(h: str) -> tuple:
    """Convert Hex format to RGB."""
    return tuple(int(h.strip("#")[i : i + 2], 16) for i in (0, 2, 4))


def from_pil(input: Image):
    """Convert PIL image to numpy array."""
    return np.asarray(input.convert(mode="RGB"))


def autocomplete_image_list(item_list: List[dict], fields: list = ["images"], max_views: int = -1) -> List[dict]:
    im_array_lengths = [item[fields[0]].shape[0] for item in item_list]
    max_ims_in_batch = max(im_array_lengths)
    if max_views > 0:
        max_ims_in_batch = min(max_ims_in_batch, max_views)
    # log some information
    prepare_message(
        msg="Image array lengths:",
        item_list=[f"max length: {max_ims_in_batch}", f"all items: {im_array_lengths}"],
        logger=rendering_utils_logger.debug,
    )

    res_item_list = []

    for item in item_list:
        ims = item[fields[0]]
        n_ims = ims.shape[0]
        if n_ims < max_ims_in_batch:
            ind = np.random.choice(range(n_ims), max_ims_in_batch - n_ims, replace=True)

            for f in fields:
                item[f] = np.concatenate([item[f], item[f][ind]], axis=0)
        elif n_ims > max_ims_in_batch:
            ind = np.random.choice(range(n_ims), max_ims_in_batch, replace=False)

            for f in fields:
                item[f] = item[f][ind]

        res_item_list.append(item)

    return res_item_list
