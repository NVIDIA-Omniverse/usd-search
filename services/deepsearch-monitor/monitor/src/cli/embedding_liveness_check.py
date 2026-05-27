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

import time

from vision_endpoint import SigLIP2, SigLIP2Config

from .. import logger


def embedding_liveness_check() -> bool:
    triton_server_url = SigLIP2Config().triton_server_url
    logger.info("Connecting to inference service at: %s", triton_server_url)

    while True:
        try:
            client = SigLIP2()
            return client.ping()
        except Exception as exc_info:
            logger.warning("Embedding client not available: %s", str(exc_info))
            time.sleep(1)


if __name__ == "__main__":
    embedding_liveness_check()
