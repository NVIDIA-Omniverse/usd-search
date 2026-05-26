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

# Publish script for SigLIP2 Triton Docker image
set -e

export DIR="$( cd "$(dirname "$0")" ; pwd -P )"
echo "publish.sh: running from => $DIR"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

export VERSION=$(cat VERSION.md | tr -d '[:space:]')
export REPO=nvcr.io/omniverse/deeptag-internal/siglip2-triton

echo "========================================"
echo "Publishing SigLIP2 Triton Docker images"
echo "========================================"
echo "Version: $VERSION"
echo "Repository: $REPO"
echo ""

# Check if images exist
if ! docker image inspect $REPO:$VERSION >/dev/null 2>&1; then
    echo -e "${RED}✗ Image $REPO:$VERSION not found${NC}"
    echo "Please run build.sh first"
    exit 1
fi

# Push versioned image
echo "Pushing $REPO:$VERSION"
docker push $REPO:$VERSION

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Published $REPO:$VERSION${NC}"
else
    echo -e "${RED}✗ Failed to publish versioned image${NC}"
    exit 1
fi

# Push latest tag
echo ""
echo "Pushing $REPO:$VERSION"
docker push $REPO:$VERSION

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Published $REPO:$VERSION${NC}"
else
    echo -e "${RED}✗ Failed to publish latest image${NC}"
    exit 1
fi

echo ""
echo "========================================"
echo "Publish complete!"
echo "========================================"
