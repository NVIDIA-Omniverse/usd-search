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

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="ngsearch-backend",
    version="0.1.0",
    author="Nvidia Corporation",
    description="Backend for Deep Search functionality",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=setuptools.find_packages(),
    classifiers=["Programming Language :: Python :: 3"],
    python_requires=">=3.6",
    zip_safe=False,
    install_requires=[
        "pillow==9.3.0",  # https://nvbugs/3689523
        "ftfy==6.0.3",
        "regex==2021.9.30",
        "pyyaml==5.4.1",
        "websockets==10.3",  # https://nvbugs/3827702
        "certifi==2022.12.07",  # https://nvbugs/4033507
        "opentelemetry-launcher==1.8.0",
    ],
)
