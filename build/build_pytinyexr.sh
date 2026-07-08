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

# Build pytinyexr wheels and place them in wheels/.
#
# With Docker available (host): builds for each version in PYTHON_VERSIONS using
# an isolated python:<ver>-bookworm container, skipping any version whose wheel
# already exists in WHEELS_DIR. Builds run in parallel up to PYTINYEXR_JOBS
# concurrent containers (default 5); each job's output is captured and
# replayed contiguously after it finishes so CI section folds stay intact.
#
# Without Docker (inside a container): builds once for the current Python version.
#
# Usage:
#   ./build/build_pytinyexr.sh
#   PYTHON_VERSIONS="3.12 3.13" ./build/build_pytinyexr.sh
#   PYTINYEXR_JOBS=1 ./build/build_pytinyexr.sh                 # force sequential
#   PYTINYEXR_REPO=https://... WHEELS_DIR=/tmp/wheels ./build/build_pytinyexr.sh
set -eux

DIR="$( cd "$(dirname "$0")" ; pwd -P )"

WHEELS_DIR="${WHEELS_DIR:-$DIR/../wheels}"
REPO="${PYTINYEXR_REPO:-https://github.com/syoyo/pytinyexr}"
PYTHON_VERSIONS="${PYTHON_VERSIONS:-3.11 3.12 3.13 3.14}"
PYTINYEXR_JOBS="${PYTINYEXR_JOBS:-5}"

mkdir -p "$WHEELS_DIR"

section_start() { echo -e "\e[0Ksection_start:$(date +%s):${1}[collapsed=true]\r\e[0K${2}"; return; }
section_end()   { echo -e "\e[0Ksection_end:$(date +%s):${1}\r\e[0K"; return; }

# Returns 0 (true) if a wheel for the given cpXYZ tag already exists.
wheel_exists() {
    local py_tag="$1"
    ls "$WHEELS_DIR"/pytinyexr-*-${py_tag}-*.whl 2>/dev/null | head -1 | grep -q .
    return
}

py_version_to_tag() {
    local py_version="$1"
    echo "cp$(echo "$py_version" | tr -d '.')"
    return
}

build_direct() {
    local py_version="$1"
    local py_tag; py_tag="$(py_version_to_tag "$py_version")"

    if wheel_exists "$py_tag"; then
        echo "pytinyexr wheel for Python $py_version already present, skipping."
        return
    fi

    section_start "tinyexr_${py_tag}" "Building tinyexr for Python ${py_version} (direct)"
    tmp_dir=$(mktemp -d /tmp/pytinyexr-XXXXXX)
    trap "rm -rf '$tmp_dir'" EXIT

    git clone --recursive --branch 0.9.1 --depth 1 "$REPO" "$tmp_dir/src"
    pip install --quiet pybind11 wheel setuptools
    cd "$tmp_dir/src"
    python setup.py bdist_wheel
    cp ./dist/*.whl "$WHEELS_DIR/"

    trap - EXIT
    rm -rf "$tmp_dir"
    section_end "tinyexr_${py_tag}"
}

build_via_docker() {
    local py_version="$1"
    local py_tag; py_tag="$(py_version_to_tag "$py_version")"

    if wheel_exists "$py_tag"; then
        echo "pytinyexr wheel for Python $py_version already present, skipping."
        return
    fi

    section_start "tinyexr_${py_tag}" "Building tinyexr for Python ${py_version} (docker)"
    docker run --rm \
        -v "$WHEELS_DIR":/dist \
        "python:${py_version}-bookworm" \
        bash -c "
            set -eux
            git clone --recursive --branch 0.9.1 --depth 1 '${REPO}' /package
            pip install --quiet pybind11 wheel setuptools
            cd /package
            python setup.py bdist_wheel
            cp ./dist/*.whl /dist/
        "
    section_end "tinyexr_${py_tag}"
}

if command -v docker &>/dev/null; then
    log_dir=$(mktemp -d /tmp/pytinyexr-parallel-XXXXXX)
    trap "rm -rf '$log_dir'" EXIT

    declare -A pid_version
    declare -A pid_logfile
    running=0
    failures=0

    # Reap one finished background job: stream its captured output back out
    # (preserving section_start/section_end markers from build_via_docker)
    # and decrement the in-flight counter.
    drain_one() {
        local completed rc v lf
        set +e
        wait -n -p completed
        rc=$?
        set -e
        v="${pid_version[$completed]}"
        lf="${pid_logfile[$completed]}"
        echo "---- pytinyexr py${v} (pid $completed, exit $rc) ----"
        cat "$lf"
        if [[ $rc -ne 0 ]]; then
            failures=$((failures + 1))
        fi
        running=$((running - 1))
        return 0
    }

    for py_version in $PYTHON_VERSIONS; do
        while [[ $running -ge $PYTINYEXR_JOBS ]]; do
            drain_one
        done
        lf="$log_dir/${py_version}.log"
        # Subshell + redirect so set -e inside build_via_docker doesn't
        # short-circuit the parent and each job's output stays isolated.
        ( build_via_docker "$py_version" ) > "$lf" 2>&1 &
        pid=$!
        pid_version[$pid]="$py_version"
        pid_logfile[$pid]="$lf"
        running=$((running + 1))
    done

    while [[ $running -gt 0 ]]; do
        drain_one
    done

    if [[ $failures -gt 0 ]]; then
        echo "FAILED: $failures pytinyexr build(s) failed" >&2
        exit 1
    fi
else
    # No Docker — build directly for the running Python (e.g. inside a container).
    current_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    build_direct "$current_version"
fi

echo "---- tinyexr wheels in $WHEELS_DIR ----"
ls -1 "$WHEELS_DIR"/pytinyexr-*.whl 2>/dev/null || echo "(none built yet)"
