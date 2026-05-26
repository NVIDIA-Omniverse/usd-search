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

import argparse
import os
import pickle
import sys

# standard modules
import unittest

bin_path = os.path.dirname(os.path.realpath(__file__))
ms_code_src_path = f"{bin_path}/../../"
usd_build_path = f"{ms_code_src_path}/package-links/nv-usd-py36/release"
usd_ext_path = f"{ms_code_src_path}/package-links/usd_ext_py36/release"

sys.path.extend(
    [
        f"{ms_code_src_path}",
        f"{ms_code_src_path}/package-links/omniverse_connection/",
        f"{ms_code_src_path}/package-links/idl.py",
        f"{ms_code_src_path}/package-links/discovery.client.py",
        f"{ms_code_src_path}/package-links/omniverse.auth.client.py",
        f"{usd_build_path}/lib/python",
        f"{usd_ext_path}/bin",
    ]
)

os.environ["PATH"] = os.environ["PATH"] + ";" + ";".join([f"{usd_build_path}/lib", f"{usd_ext_path}/lib"])

from config import AssetDBConfig as service_Config

import search_utils.log_utils as lu

# local / proprietary modules
import search_utils.omniverse_utils as ou
import search_utils.usd_utils as uu

logger = lu.set_simple_logger("data loader", os.getenv("LOG_LEVEL", "INFO"))
tmp_dir = os.getenv("TMP_FOLDER", f"{bin_path}/tmp")


def parse_arguments():
    """Parse arguments for the service."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--omni_path",
        type=str,
        # default="/Users/arozantsev/Kitchen_set/",
        # default="/NVIDIA/Samples/",
        # default="/Projects/QA/OVContent/SubwayEnvironment/Overview/SharedExport/Props/",
        default="/Projects/QA/OVContent/AncientTreasures/Overview/ModularExport/Props/",
        help="Path in Omniverse",
    )
    parser.add_argument(
        "--folder",
        type=str,
        default=os.getenv("TMP_USD_PATH", f"{bin_path}/usd"),
        help="local folder",
    )

    return parser


def condition(r) -> bool:
    """Condition that an omniverse path should be included in extraction

    Args:
        r ([type]): [description]

    Returns:
        bool: [description]
    """
    if r.empty or r.size == 0:
        return False
    if not r.path.endswith(".usd"):
        return False

    return True


async def get_recursive_list(args, config, path_list, logger=print, omni_conn_timeout=3600):

    with lu.print_wrapper("Getting a list of paths"):
        async with ou.omni_connection_wrapper(*args, timeout=omni_conn_timeout) as c:
            paths = await ou.recursive_list(c, path_list)

    # create directory
    os.makedirs(tmp_dir, exist_ok=True)
    # filter paths
    paths = [p.path for p in paths if condition(p)][::-1]
    # save paths in a local directory
    with open(f"{tmp_dir}/path.pkl", "wb") as f:
        pickle.dump(paths, f)


def main(args):
    # get a list of assets in omniverse
    ou.omni_single_task(
        service_Config,
        get_recursive_list,
        path_list=[
            # args.omni_path
            "/Projects/QA/OVContent/SubwayTrain/Overview/SharedExport/Props/",
            "/Projects/QA/OVContent/SoulCave/DemoMap/SharedExport/Props/",
            "/Projects/QA/OVContent/SciFiHallway/SharedExport/Props/",
            "/Projects/QA/OVContent/STL_Office/Props/",
            "/Projects/QA/OVContent/FreeFurniturePack/ModularExport/Props/",
            "/Projects/QA/OVContent/EpicZenGarden/Zen_P/Props/",
            "/Projects/QA/OVContent/DeskClutterKit/SharedExport/Props/",
            "/Projects/QA/OVContent/CrumblingRuins/Demo/SharedExport/Props/",
            "/Projects/QA/OVContent/CityTrashAndWaste/SamplesMap/SharedExport/Props/",
            "/Projects/QA/OVContent/CitySubwayTunnel/Overview/SharedExport/Props/",
            "/Projects/QA/Mountain_Pond/USDs/",
            "/Projects/QA/AutoExports/2020-05-29_10-51-26/WithTemplates/ArchvizKitchenette/Kitchenette/Props/",
            "/Projects/Dev/House/",
            "/Users/arozantsev/Kitchen_set",
            "/NVIDIA/Samples/",
            "/Projects/QA/OVContent/SubwayEnvironment/Overview/SharedExport/Props/",
        ],
        logger=logger,
    )

    with open(f"{tmp_dir}/path.pkl", "rb") as f:
        paths = pickle.load(f)

    logger.info(f"Number of paths found in omniverse: {len(paths)}")
    # load all the files from the list locally
    uu.get_usd_files_from_omniverse(omni_files=paths, usd_tmp_folder=args.folder, config=service_Config)


if __name__ == "__main__":
    """Test, whether the training functionality is working.
    Examples:

        $ USD_UTILS_LOGLEVEL=DEBUG OV_SERVER=ov-rc.nvidia.com python download_usd_files.py --folder=//netapp-zu02/zurich-vega-scratch/arozantsev/dig_wld/datasets/usd_data/DoNotDistribute/ov-rc
    """
    # read command line arguments
    args = parse_arguments().parse_args()
    # run loading
    main(args)
