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
import multiprocessing as mp

# standard imports
import os

try:
    mp.set_start_method("spawn")
except:
    pass

from multiprocessing import Process, Queue
from queue import Empty
from threading import Lock

# local/proprietary modules
from omni.deepsearch import queue_runner

from search_utils import log_utils as lu

logger = lu.set_simple_logger("omni backend", os.getenv("LOG_LEVEL", "INFO"))


class OmniBackend:
    def __init__(
        self,
        ov_server: str = None,
        host: str = None,
        port: int = None,
        timeout: float = 10,
        **kwargs,
    ):
        """Backend that connects to the deepsearch service in omniverse.

        Args:
            ov_server (str, optional): path to omniverse server. Defaults to ``None``.
            host (str, optional): alternatively you can provide direct service host. Defaults to ``None``.
            port (int, optional): and service port. Defaults to ``None``.
            timeout (float, optional): timeout to retrieve backend length. Defaults to ``10``.
        """
        self.ov_server = ov_server
        self.host = host
        self.port = port
        self.input_queue = Queue()
        self.result_queue = Queue()
        self.p = Process(
            target=queue_runner,
            args=(
                self.input_queue,
                self.result_queue,
                self.ov_server,
                self.host,
                self.port,
            ),
        )
        self.p.daemon = True
        self.p.start()
        self.backend_access = Lock()
        self.backend = self
        self.timeout = timeout

    def __len__(self, n_retries: int = 5) -> int:
        """length of the backend

        Returns:
            int: number of items in the backend
        """
        with self.backend_access:
            received = False
            for _ in range(n_retries):
                try:
                    # send request to the backend thread
                    self.input_queue.put({"command": "datasource_info"})
                    # wait for response
                    response = self.result_queue.get(timeout=self.timeout)
                    received = True
                    break
                except Exception as e:
                    self.input_queue.put({"command": "recreate"})

            if not received:
                raise ValueError("Data was not received")

            return int(response["count"])

    def get_top_n(
        self,
        query: str,
        N: int = 5,
        noimages: bool = False,
        nopredictions: bool = False,
        filter_repeating: bool = True,
        timeout: float = 10,
        n_retries: int = 5,
        similarity_threshold: float = 0,
        **kwargs,
    ) -> list:
        """Send a search query to the deepsearch service.

        Args:
            query (str): input query that need to be searched for
            N (int, optional): number of items that need to be returned. Defaults to ``5``.
            noimages (bool, optional): if ``True`` - do not return images as part of the response. Defaults to ``False``.
            nopredictions (bool, optional): if ``True`` - do not return predictions as part of the response. Defaults to ``False``.
            filter_repeating (bool, optional): if ``True`` - filter repeating predictions. Defaults to ``True``.
            timeout (float, optional): timeout for the request. Defaults to ``20``.
            n_retries (int, optional): number of search retries. Defaults to ``5``.
            similarity (float, optional): collapse similar results. Defaults to ``0``.

        Returns:
            list: search response
        """
        req = {
            "command": "search",
            "payload": {
                "query": query,
                "n": N,
                "return_predictions": not nopredictions,
                "return_images": not noimages,
                "similarity_threshold": similarity_threshold,
            },
        }
        with self.backend_access:
            received = False
            for _ in range(n_retries):
                try:
                    # send request to the backend thread
                    self.input_queue.put(req)

                    # wait for response
                    item = self.result_queue.get(timeout=timeout)
                    received = True
                    break
                except Exception as e:
                    self.input_queue.put({"command": "recreate"})

            if not received:
                raise ValueError("Data was not received")

            result = []
            for el in item["data"]:
                content = {
                    "name": el["url"],
                    "value": el["value"],
                    "id": el["id"],
                    "enabled": True,
                }
                if not noimages:
                    content["render"] = el["image"]
                if not nopredictions:
                    content["prediction"] = [{"tag": p["tag"], "prob": p["prob"]} for p in el["predictions"]]
                result.append(content)
            return result
