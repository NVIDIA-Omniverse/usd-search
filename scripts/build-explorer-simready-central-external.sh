#!/usr/bin/env bash
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

# Build the Explorer image for the "simready central external" deployment: a
# thin wrapper over scripts/build-explorer.sh that bakes this deployment's
# tuned hybrid-search defaults into the SPA.
#
# Baked defaults:
#   similarity cutoff    = 1.1432   (REACT_APP_DEFAULT_CUTOFF_THRESHOLD)
#   text weight          = 0.9      (REACT_APP_DEFAULT_TEXT_WEIGHT)
#   cross-field operator = and      (REACT_APP_DEFAULT_CROSS_FIELD_OPERATOR)
#   LLM query parsing    = disabled (REACT_APP_ENABLE_LLM_PARSING=false)
#   VLM validation       = disabled (REACT_APP_ENABLE_VLM_VALIDATION=false)
#   dependency views     = disabled (REACT_APP_ENABLE_DEPENDENCY_VIEWS=false)
#   index management     = disabled (REACT_APP_ENABLE_INDEX_MANAGEMENT=false)
#   auth icon + popover  = disabled (REACT_APP_ENABLE_AUTH_UI=false)
#
# REACT_APP_API_URL is left empty on purpose: the SPA calls its own same-origin
# /api/, so this image is meant to sit behind a gateway that routes to the
# backend.
#
# The image tag is suffixed "-simready-central-external" and NOT pushed by
# default; pass --push (or PUSH=true) to publish. Any extra arguments are
# forwarded verbatim to build-explorer.sh, so per-invocation overrides work:
#
#   ./scripts/build-explorer-simready-central-external.sh            # local build
#   ./scripts/build-explorer-simready-central-external.sh --push     # build + push
#   ./scripts/build-explorer-simready-central-external.sh --cutoff 0.9   # override a default

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Deployment defaults come first; forwarded "$@" wins (later flags override
# earlier ones in build-explorer.sh's arg loop), so callers can tweak any knob.
exec "${SCRIPT_DIR}/build-explorer.sh" \
  --cutoff 1.1432 \
  --text-weight 0.9 \
  --cross-field-operator and \
  --enable-llm-parsing false \
  --enable-vlm-validation false \
  --enable-dependency-views false \
  --enable-index-management false \
  --enable-auth-ui false \
  --suffix simready-central-external \
  "$@"
