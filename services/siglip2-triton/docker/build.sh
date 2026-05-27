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

# Build script for SigLIP2 Triton Docker image

set -e

echo "========================================"
echo "SigLIP2 Triton Docker Build Script"
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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

export REPO=nvcr.io/omniverse/deeptag-internal

# Export dependencies from pyproject.toml
echo ""
echo "Exporting server dependencies..."
uv export --no-hashes -o docker/requirements.txt --project docker
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Server dependencies exported to docker/requirements.txt${NC}"
else
    echo -e "${RED}✗ Failed to export server dependencies${NC}"
    exit 1
fi

# Check for required files
echo ""
echo "Checking required files..."
required_files=(
    "../../docker/Dockerfile.siglip2-triton"
    "docker/requirements.txt"
    "docker/PACKAGE-LICENSES"
    "model_repo/siglip2_vision_encoder_onnx"
    "model_repo/siglip2_text_encoder_onnx"
    "_licenses"
)

for file in "${required_files[@]}"; do
    if [ ! -e "$file" ]; then
        echo -e "${RED}✗ Missing: $file${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Found: $file${NC}"
done


echo ""
echo "Building Docker image..."
if [ ! -z "$VERSION" ]; then
    docker build -f ../../docker/Dockerfile.siglip2-triton -t ${REPO}/siglip2-triton:${VERSION} -t ${REPO}/siglip2-triton:latest .
else
    docker build -f ../../docker/Dockerfile.siglip2-triton -t ${REPO}/siglip2-triton:latest .
fi

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Docker image built successfully${NC}"
    echo ""
    if [ ! -z "$VERSION" ]; then
        echo "Images:"
        echo "  - ${REPO}/siglip2-triton:${VERSION}"
        echo "  - ${REPO}/siglip2-triton:latest"
    else
        echo "Image: ${REPO}/siglip2-triton:latest"
    fi
    echo ""
    echo "To run the container:"
    echo "  docker-compose up -d"
    echo "  or"
    echo "  docker run --gpus all -p 8000:8000 -p 8001:8001 -p 8002:8002 ${REPO}/siglip2-triton:latest"
else
    echo -e "${RED}✗ Failed to build Docker image${NC}"
    exit 1
fi

echo ""
echo "========================================"
echo "Build complete!"
echo "========================================"

