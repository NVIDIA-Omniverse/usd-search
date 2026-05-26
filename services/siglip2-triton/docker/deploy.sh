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

set -e

echo "========================================"
echo "SigLIP2 Triton Docker Deploy Script"
echo "========================================"

# Change to project root directory (parent of docker/)
cd "$(dirname "$0")/.."

# Read version from VERSION.md
if [ -f "VERSION.md" ]; then
    VERSION=$(cat VERSION.md | tr -d '[:space:]')
    echo "Version: $VERSION"
else
    echo "Warning: VERSION.md not found, using 'latest' only"
    VERSION=""
fi

export REPO=nvcr.io/omniverse/deeptag-internal

IMAGE_NAME="${REPO}/siglip2-triton:${VERSION}"
CONTAINER_NAME="siglip2-triton-server-${VERSION}"
TRITON_HTTP_PORT=8000
TRITON_GRPC_PORT=8001
TRITON_METRICS_PORT=8002
MODEL_REPO_DIR="$(pwd)/model_repo"

# Stop and remove previous container if exists
if [ "$(docker ps -aq -f name=$CONTAINER_NAME)" ]; then
    echo "Stopping and removing old container $CONTAINER_NAME..."
    docker stop $CONTAINER_NAME
    docker rm $CONTAINER_NAME
fi

# Ensure model_repo exists
if [ ! -d "$MODEL_REPO_DIR" ]; then
    echo "Error: model_repo directory not found in $MODEL_REPO_DIR"
    exit 1
fi

# Launch Triton Inference Server container
echo "Deploying $IMAGE_NAME ..."
docker run -d \
    --rm \
    --gpus all \
    --shm-size=1g \
    --name $CONTAINER_NAME \
    -p $TRITON_HTTP_PORT:8000 \
    -p $TRITON_GRPC_PORT:8001 \
    -p $TRITON_METRICS_PORT:8002 \
    $IMAGE_NAME 

# Print server logs
# docker logs -f $CONTAINER_NAME
