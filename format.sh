#!/bin/bash
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

if [[ $1 == "--check" ]]; then
  echo "Running in check-only mode, no code will be modified"
  check_flag="--check"
  shift
else
  check_flag=""
fi

echo "################################################################################"
echo "################################ Running isort #################################"
isort $check_flag "$@"
isort_status=$?

if (( isort_status != 0 )); then
  echo "!!! isort check failed !!!"
fi

echo "################################################################################"
echo "################################ Running black #################################"
black $check_flag "$@"
black_status=$?

if (( black_status != 0 )); then
  echo "!!! black check failed !!!"
fi

if (( black_status != 0 || isort_status != 0 )); then
  exit 1
fi
