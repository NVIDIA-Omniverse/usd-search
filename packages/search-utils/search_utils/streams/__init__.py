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

from typing import Any, Callable, Optional

from .base import AvailableStreamTypes, StreamConfig, StreamItem
from .redis import RedisStreamConfig, RedisStreamWorker


def get_stream_worker(
    stream_type: AvailableStreamTypes,
    config: Optional[StreamConfig] = None,
    retry_limit_reached_callback: Optional[Callable[[Any], None]] = None,
) -> RedisStreamWorker:
    """Get the stream Producer

    Args:
        stream_type (AvailableStreamTypes): stream type (currently only Redis is supported)
        config (StreamConfig): stream configuration
        retry_limit_reached_callback (Optional[Callable[[Any], None]], optional): Callback that is executed, when retry limit for the asset is reached. Defaults to None.

    Raises:
        NotImplementedError: on unsupported stream type

    Returns:
        RedisStreamProducer: stream producer
    """
    if stream_type == AvailableStreamTypes.redis:
        if config is None:
            config = RedisStreamConfig()
        return RedisStreamWorker(config=config, retry_limit_reached_callback=retry_limit_reached_callback)

    raise NotImplementedError(f"Unsupported stream_type: '{stream_type}'")


__all__ = ["StreamItem"]
