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

from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


async def filter_objects(
    access_check_coro: Callable[[list[str]], Awaitable[list[str]]],
    objects: list[T],
    url_keys: str | list[str],
) -> list[T]:
    if isinstance(url_keys, str):
        url_keys = [url_keys]

    all_urls = [[getattr(obj, url_key) for url_key in url_keys] for obj in objects]
    # flatten
    all_urls = [url for urls in all_urls for url in urls]

    if not all_urls:
        return []

    verified_urls = await access_check_coro(set(all_urls))
    return [obj for obj in objects if all(getattr(obj, url_key) in verified_urls for url_key in url_keys)]
