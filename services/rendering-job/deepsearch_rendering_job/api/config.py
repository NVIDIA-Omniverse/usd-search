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

from pathlib import Path

# Define cache configuration
CACHE_MAXSIZE = 1000  # Maximum number of items in cache
CACHE_TTL = 3600  # Time to live in seconds (1 hour)


def get_package_version() -> str:
    """Get the package version from metadata or fallback to unknown."""
    try:
        # For Poetry projects: importlib.metadata (Python 3.8+)
        from importlib.metadata import version

        return version("deepsearch-rendering-job")
    except Exception:
        try:
            # Fallback: pkg_resources (more compatible)
            import pkg_resources

            return pkg_resources.get_distribution("deepsearch-rendering-job").version
        except Exception:
            return "unknown"


def get_api_description() -> str:
    with open(f"{Path(__file__).parent}/README.md", "r", encoding="utf-8") as file:
        return file.read()
