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

"""Print a local USD layer's authored upAxis, defaultPrim and material-fallback hint as JSON.

Run as a standalone script (``python this_file.py <layer_path>``), never imported
as part of the package: ``usd-core``'s ``pxr`` and a live ``ovrtx.Renderer`` both
register USD schema types and cannot share a process, so the read is isolated here.

Output: ``{"up_axis": "Y"|"Z"|"", "default_prim": str, "needs_default_material": bool}``.  A true
``needs_default_material`` signals that the asset carries renderable geometry but no
renderable surface (no MDL, no ``UsdPreviewSurface``, no ``displayColor``) - the case
where Kit shows grey clay instead of ovrtx's red missing-material placeholder.
"""

import json
import sys


def _has_renderable_material(stage) -> bool:
    from pxr import UsdGeom, UsdShade  # pylint: disable=import-error

    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Gprim):
            display_color = prim.GetAttribute("primvars:displayColor")
            if display_color and display_color.HasAuthoredValue():
                return True
        if prim.IsA(UsdShade.Shader):
            if prim.GetAttribute("info:mdl:sourceAsset").Get():
                return True
            if prim.GetAttribute("info:id").Get() == "UsdPreviewSurface":
                return True
    return False


def _has_geometry(stage) -> bool:
    from pxr import UsdGeom  # pylint: disable=import-error

    return any(prim.IsA(UsdGeom.Gprim) for prim in stage.Traverse())


def _probe(path: str) -> dict:
    from pxr import Usd, UsdGeom  # pylint: disable=import-error

    result = {"up_axis": "", "default_prim": "", "needs_default_material": False}
    stage = Usd.Stage.Open(path, load=Usd.Stage.LoadAll)
    if stage is None:
        return result

    if stage.HasAuthoredMetadata("upAxis"):
        result["up_axis"] = str(UsdGeom.GetStageUpAxis(stage))
    result["default_prim"] = stage.GetRootLayer().defaultPrim

    result["needs_default_material"] = _has_geometry(stage) and not _has_renderable_material(stage)

    return result


if __name__ == "__main__":
    try:
        print(json.dumps(_probe(sys.argv[1]) if len(sys.argv) > 1 else {}))
    except Exception:  # pylint: disable=broad-except
        print("{}")
