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

set -e
set -u

# Check for libGLX_nvidia.so.0 (needed for vulkan)
ldconfig -p | grep libGLX_nvidia.so.0 || NOTFOUND=1
if [[ -v NOTFOUND ]]; then
    cat << EOF > /dev/stderr

Fatal Error: Can't find libGLX_nvidia.so.0...

Ensure running with NVIDIA runtime. (--gpus all) or (--runtime nvidia)
If no GPU is required, please run startup_nogpu.sh as the entrypoint.

EOF
    exit 1
fi

echo 'Running: [...]kit in GPU mode, please run startup_nogpu.sh if no GPU is required' $@

# set some parameters that are required for DeepSearch rendering service

exec /opt/nvidia/omniverse/kit-kernel/kit \
    "--allow-root" \
    "--no-window" \
    "--/app/extensions/registryEnabled=0" \
    "--/log/level=Info" \
    "--/log/fileLogLevel=Info" \
    "--/log/outputStreamLevel=Info" \
    "--/log/flushStandardStreamOutput=true" \
    "--/app/python/logSysStdOutput=true" \
    "--/app/python/interceptSysStdOutput=false" \
    "--/plugins/carb.scripting-python.plugin/logScriptErrors=true" \
    "--/crashreporter/enabled=false" \
    "--/app/python/logSysStdOutput=0" \
    "--/app/fastShutdown=true" \
    "--/app/file/ignoreUnsavedOnExit=true" \
    "--/app/asyncRendering=false" \
    "--/app/renderer/waitIdle=true" \
    "--/app/hydraEngine/waitIdle=true" \
    "--/rtx/materialDb/syncLoads=true" \
    "--/omni.kit.plugin/syncUsdLoads=true" \
    "--/rtx/hydra/materialSyncLoads=true" \
    "--/rtx/hydra/perMaterialSyncLoads=true" \
    "--/rtx/hydra/geometrySyncLoads=true" \
    "--/rtx-transient/dlssg/enabled=false" \
    "--/rtx-transient/resourcemanager/texturestreaming/async=false" \
    "--/rtx-transient/resourcemanager/texturestreaming/streamingBudgetMB=0" \
    "--/rtx-transient/resourcemanager/enableTextureStreaming=false" \
    "--/rtx/aovConverter/disocclusionScale=10000000" \
    "--/renderer/multiGpu/enabled=false" \
    "--/renderer/multiGpu/maxGpuCount=1" \
    "--/rtx/hydra/curves/splits=8" \
    "--/rtx-transient/samplerFeedbackTileSize=1" \
    "--/exts/omni.kit.window.viewport/blockingGetViewportDrawable=true" \
    "--ext-folder /opt/nvidia/omniverse/code-launcher/extscache/" \
    "--/app/extensions/fastImporter/enabled=false" \
    "--/app/material/disableMdlReload=true" \
    "--/app/python/extraPaths/0=/home/ubuntu/.local/lib/python3.10/site-packages" \
    $@
