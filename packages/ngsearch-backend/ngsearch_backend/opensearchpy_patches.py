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

from opensearchpy import TransportError
from opensearchpy.helpers.actions import (
    _ActionChunker,
    _process_bulk_chunk_error,
    _process_bulk_chunk_success,
)


class _ActionChunkerPatched(_ActionChunker):
    """_ActionChunker patched to be compatible with the orjson serializer"""

    def feed(self, action, data):
        ret = None
        raw_data, raw_action = data, action
        action = self.serializer.dumps(action)
        # +1 to account for the trailing new line character
        if isinstance(action, bytes):
            # When using orjson serializer, its output is of bytes type, and thus we do not encode it
            cur_size = len(action) + 1
        else:
            cur_size = len(action.encode("utf-8")) + 1

        if data is not None:
            data = self.serializer.dumps(data)
            if isinstance(data, bytes):
                # When using orjson serializer, its output is of bytes type, and thus we do not encode it
                cur_size += len(data) + 1
            else:
                cur_size += len(data.encode("utf-8")) + 1

        # full chunk, send it and start a new one
        if self.bulk_actions and (self.size + cur_size > self.max_chunk_bytes or self.action_count == self.chunk_size):
            ret = (self.bulk_data, self.bulk_actions)
            self.bulk_actions, self.bulk_data = [], []
            self.size, self.action_count = 0, 0

        self.bulk_actions.append(action)
        if data is not None:
            self.bulk_actions.append(data)
            self.bulk_data.append((raw_action, raw_data))
        else:
            self.bulk_data.append((raw_action,))

        self.size += cur_size
        self.action_count += 1
        return ret


async def _process_bulk_chunk_patched(
    client, bulk_actions, bulk_data, raise_on_exception=True, raise_on_error=True, ignore_status=(), *args, **kwargs
):
    """
    Send a bulk request to opensearch and process the output.
    Patched to work with the orjson serializer.
    """
    if not isinstance(ignore_status, (list, tuple)):
        ignore_status = (ignore_status,)

    try:
        # send the actual request
        if len(bulk_actions) and isinstance(bulk_actions[0], bytes):
            resp = await client.bulk(b"\n".join(bulk_actions) + b"\n", *args, **kwargs)
        else:
            resp = await client.bulk("\n".join(bulk_actions) + "\n", *args, **kwargs)
    except TransportError as e:
        gen = _process_bulk_chunk_error(
            error=e,
            bulk_data=bulk_data,
            ignore_status=ignore_status,
            raise_on_exception=raise_on_exception,
            raise_on_error=raise_on_error,
        )
    else:
        gen = _process_bulk_chunk_success(
            resp=resp,
            bulk_data=bulk_data,
            ignore_status=ignore_status,
            raise_on_error=raise_on_error,
        )
    for item in gen:
        yield item


def patch_opensearchpy_client():
    # A patched _ActionChunker class and _process_bulk_chunk function are needed when using the orjson serializer
    import opensearchpy.helpers.actions

    opensearchpy._async.helpers._ActionChunker = _ActionChunkerPatched
    opensearchpy._async.helpers._process_bulk_chunk = _process_bulk_chunk_patched
