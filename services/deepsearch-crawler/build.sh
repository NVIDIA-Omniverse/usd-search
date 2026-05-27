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

# fail on first error
set -eux
export DIR="$( cd "$(dirname "$0")" ; pwd -P )"
echo "running from =>"$DIR

export DOCKER_TOOLS=$DIR/docker/tools
export REQUIREMENTS_DIR=$DIR/_requirements
export LICENSES_DIR=$DIR/_licenses
export POETRY_EXPORT="poetry export -f requirements.txt --without-urls --with-credentials"
# disable package information gathering from licensing tool
export LICENSING_NO_PACKAGE_INFO_CREATE=True

mkdir -p $LICENSES_DIR

echo "----- Poetry build ---------"
poetry self add "poetry-dynamic-versioning[plugin]"
poetry build --format wheel

echo "----- Export requirements --"
mkdir -p $REQUIREMENTS_DIR
$POETRY_EXPORT --only main --output $REQUIREMENTS_DIR/main.txt
$POETRY_EXPORT --only main --without-hashes --output $REQUIREMENTS_DIR/licenses.txt
$POETRY_EXPORT --only test --without-hashes --output $REQUIREMENTS_DIR/test.txt
$POETRY_EXPORT --only lint --without-hashes --output $REQUIREMENTS_DIR/lint.txt
