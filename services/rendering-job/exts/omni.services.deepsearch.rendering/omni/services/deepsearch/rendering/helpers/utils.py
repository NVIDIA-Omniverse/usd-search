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

# standard modules
import asyncio
import math
import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import carb

# third party modules
import numpy as np
import omni.client
import omni.kit.commands

# local / proprietary modules
import omni.usd
import toml
from PIL import Image
from pxr import Sdf, Usd, UsdGeom, UsdShade

from . import FailedCreatingStage, logger
from .log_utils import prepare_message, print_wrapper

bin_path = os.path.dirname(__file__)

# create a map of Kit events
event_map = {}
for _val in dir(omni.usd.StageEventType):
    if _val.isupper():
        event_map[int(getattr(omni.usd.StageEventType, _val))] = _val

prepare_message(
    msg="Avaliable stage events",
    item_list=[f"{k}: {v}" for k, v in event_map.items()],
    logger=logger.debug,
)


def get_2d_bbox_from_segmetation(segmentation):
    segmentation_mask = np.sum(segmentation, axis=0, keepdims=True) > 0
    ind = np.where(segmentation_mask[0] > 0)
    min_y, max_y = np.min(ind[0]), np.max(ind[0])
    min_x, max_x = np.min(ind[1]), np.max(ind[1])
    return (min_x, min_y, max_x, max_y)


async def get_auth_token_async(path: str) -> Dict[str, str]:
    """Get authentication token for a given omniverse path

    Args:
        path (str): path on an nucleus server.

    Raises:
        RuntimeWarning: in case omniverse server information and token was not retrieved

    Returns:
        Dict[str, str]: server information that includes token data.
    """
    try:
        result, server_info = await asyncio.wait_for(omni.client.get_server_info_async(path), timeout=20)
    except Exception as e:
        raise RuntimeWarning(str(e))

    if result != omni.client.Result.OK:
        raise RuntimeWarning(str(result))

    return dict(
        host=omni.client.break_url(path).host,
        username=server_info.username,
        auth_token=server_info.auth_token,
        server_info=server_info,
    )


def add_ref(target_prim: Usd.Typed, source_path: str, source_prim_path: Optional[str] = None):
    """Add reference to a USD object at the source path

    Args:
        target_prim (Usd.Typed): USD prim where the reference need to be created
        source_path (str): source path of the USD prim
        source_prim_path (Optional[str], optional): path to a prim within a USD stage. Defaults to None.
    """
    if source_prim_path:
        reference = Sdf.Reference(source_path, source_prim_path)
    else:
        reference = Sdf.Reference(source_path)

    references = target_prim.GetReferences()
    omni.kit.commands.execute(
        "AddReferenceCommand",
        stage=references.GetPrim().GetStage(),
        prim_path=references.GetPrim().GetPath(),
        reference=reference,
    )


def get_scene_dims(
    asset_path: Optional[str] = None,
    prim_ignore_list: List[str] = ["Skeleton"],
    no_geometry_types: list = ["Scope", "Material", "Camera", "Shader"],
) -> dict:
    """Get scene dimensions

    Args:
        asset_path (Optional[str], optional): filter the scene content by an asset path. Defaults to None.
        prim_ignore_list (List[str], optional): ignore prims of certain types in the scene.
            Defaults to ["Skeleton"].
        no_geometry_types (list, optional): list of types that do not contain geometry information.
            Defaults to ["Scope", "Material", "Camera", "Shader"].

    Returns:
        dict: scene dimensions
    """
    # rescale to unit cube
    extents = []
    stage = omni.usd.get_context().get_stage()
    empty_status = True
    for prim in stage.Traverse():
        name = str(prim.GetPath())
        if asset_path is not None and name.find(asset_path) < 0:
            continue
        if str(prim.GetTypeName()) in prim_ignore_list:
            continue

        if str(prim.GetTypeName()) not in no_geometry_types:
            empty_status = False

        attributes = prim.GetPropertyNames()
        if "extent" not in attributes:
            continue
        extentAttr = prim.GetAttribute("extent")
        extent = np.array(extentAttr.Get(Usd.TimeCode(0.0)))
        try:
            if extent is None or str(extent) == "None":
                continue
            if extent[0][0] > float(1e38):
                continue
        except Exception as e:
            carb.log_info(extent)
            carb.log_error(f"extent comparison exception: {str(e)}")
            continue
        extents.append(extent)

    # if no extents were found - likely no geometry in the scene
    if len(extents) == 0:
        box_sz = np.array([1, 1, 1])
        center = np.array([0.5, 0.5, 0.5])
        if empty_status:
            status = "empty"
        else:
            status = "no_extents"
    else:
        try:
            bbox_max = np.max(np.array([e[1] for e in extents]), axis=0)
            bbox_min = np.min(np.array([e[0] for e in extents]), axis=0)
            box_sz = bbox_max - bbox_min
            center = (bbox_max + bbox_min) / 2
            status = "success"
        except Exception as e:
            carb.log_error(f"error calculating extents: {str(e)}")
            box_sz = np.array([1, 1, 1])
            center = np.array([0.5, 0.5, 0.5])
            status = f"error: {str(e)}"

    return {"box_sz": box_sz, "center": center, "status": status}


def create_prim(
    stage,
    path: str,
    prim_type: str,
    translation: Optional[tuple] = None,
    rotation: Optional[tuple] = None,
    scale: Optional[tuple] = None,
    ref: Optional[str] = None,
    paths_types_list: Optional[list] = None,
    material_binds: dict = {},
    mat_paths_types_list: list = [],
    attributes: dict = {},
    ignore_types: list = ["Camera", "Skeleton", "DomeLight", "DistantLight"],
    inactive_types: list = ["Skeleton"],
    **kwargs,
):
    """Create a prim, apply specified transforms, apply semantic label and
    set specified attributes.

    args:
        stage: USD Stage
        path (str): The path of the new prim.
        prim_type (str): Prim type name
        translation (tuple(float, float, float), optional): prim translation (applied last)
        rotation (tuple(float, float, float), optional): prim rotation in radians with rotation
            order ZYX.
        scale (tuple(float, float, float), optional): scaling factor in x, y, z.
        ref (str, optional): Path to the USD that this prim will reference.
        semantic_label (str, optional): Semantic label.
        attributes (dict, optional): Key-value pairs of prim attributes to set.
    """
    # remove prim if it exists
    stage.RemovePrim(path)
    # add new prim
    prim = stage.DefinePrim(path, prim_type)

    for k, v in attributes.items():
        if k == "fov":
            h_aperture = prim.GetAttribute("horizontalAperture").Get()
            focal_length = fov_to_focal_length(math.radians(v), h_aperture)
            k, v = "focalLength", focal_length
        prim.GetAttribute(k).Set(v)
    xform_api = UsdGeom.XformCommonAPI(prim)
    if ref:
        if paths_types_list is None:
            add_ref(prim, ref)
        else:
            # add USD items to the stage that need to be added to the root level
            for p, t in mat_paths_types_list:
                sub_prim = stage.DefinePrim(f"{p}", t)
                add_ref(sub_prim, ref, p)

            # loop for all subpath found in prim:
            # > create a new prim of the correct type
            # > add a reference to the object
            for p, t in paths_types_list:
                if t not in ignore_types:
                    sub_prim = stage.DefinePrim(f"{path}{p}", t)
                    add_ref(sub_prim, ref, p)

    for sub_prim in stage.Traverse():
        if str(sub_prim.GetPath()).find(path) < 0:
            continue
        if str(sub_prim.GetTypeName()) in inactive_types:
            sub_prim.SetActive(False)

    # update material binds
    material_binds = {f"{path}{k}": v for k, v in material_binds.items()}

    # fix materials that might be referenced outside scope
    fix_materials(stage, material_binds, path)

    if rotation:
        xform_api.SetRotate(rotation, UsdGeom.XformCommonAPI.RotationOrderZYX)
    if scale:
        xform_api.SetScale(scale)
    if translation:
        xform_api.SetTranslate(translation)
    return prim


def fix_materials(stage: Usd.Typed, material_binds: Dict[str, str], path: str):
    """Fix references of the materials by prefixing the references with a path prefix.

    Args:
        stage (Usd.Typed): USD stage for which need to be updated
        material_binds (Dict[str, str]): dictionary that stores information about materials in the stage
        path (str): path, which should prefix all the material links
    """
    # fix materials
    for prim in stage.Traverse():
        prim_path = prim.GetPath()
        if str(prim_path) in material_binds:
            # update material binds
            for m in material_binds[str(prim_path)]:
                # add new target
                omni.kit.commands.execute(
                    "BindMaterialCommand",
                    prim_path=Sdf.Path(prim_path),
                    material_path=Sdf.Path(f"{path}{str(m)}"),
                    strength=UsdShade.Tokens.weakerThanDescendants,
                )


def fov_to_focal_length(fov: float, horizontal_aperture: float) -> float:
    """Convert Field of view to focal length."""
    focal_length = horizontal_aperture / math.tan(fov / 2.0) / 2.0
    return focal_length


async def wait_n_frames(app=None, n: int = 2):
    """Wait N frames for Kit updates to happen."""
    if n == 0:
        return
    if app is not None:
        for _ in range(n):
            await app.next_update_async()


def _compute_asset_bounding_box():
    """Compute the bounding box around the USD Stage."""
    stage = omni.usd.get_context().get_stage()
    bounding_box_cache = UsdGeom.BBoxCache(0, [UsdGeom.Tokens.default_, UsdGeom.Tokens.render], True)
    return bounding_box_cache.ComputeWorldBound(stage.GetPseudoRoot())


def get_stage_bounds(
    ref_up_axis: str = "Z",
) -> Tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Compute bounding box of the current stage.

    Args:
        ref_up_axis (str, optional): _description_. Defaults to "Z".

    Returns:
        Tuple[np.ndarray, float, np.ndarray, np.ndarray]: bounding box information
    """
    _bounding_box_cache = _compute_asset_bounding_box()
    center = _bounding_box_cache.ComputeCentroid()
    _range = _bounding_box_cache.ComputeAlignedRange()
    box_sz = np.array(_range.GetSize())

    scale = 1 / (max(box_sz) + 1e-6)

    if ref_up_axis == "Y":
        translate = np.asarray((-center[0], -center[1] + box_sz[1] / 2, -center[2]))
    else:
        translate = np.asarray((-center[0], -center[1], -center[2] + box_sz[2] / 2))

    return translate, scale, box_sz, center


def get_prim_bounds(prim: Usd.Typed, ref_up_axis: str = "Z") -> Tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    """Estimate the bounding box of a prim

    Args:
        prim (Usd.Typed): prim in the USD scene
        ref_up_axis (str, optional): Up axis of this scene. Defaults to "Z".

    Returns:
        Tuple[np.ndarray, float, np.ndarray, np.ndarray]: _description_
    """
    # compute BBox of the object
    bounds_world = UsdGeom.Imageable(prim).ComputeLocalBound(0, "default")
    center = bounds_world.ComputeCentroid()

    # bounding box
    bbox = bounds_world.GetBox()
    box_sz = np.array(bbox.GetSize())
    # check that the bounding box is valid
    if box_sz is None or any(box_sz < -1 * float(1e38)):
        scene_dims = get_scene_dims(str(prim.GetPath()))
        box_sz = scene_dims["box_sz"]
        center = scene_dims["center"]

    scale = 1 / (max(box_sz) + 1e-6)

    if ref_up_axis == "Y":
        translate = np.asarray((-center[0], -center[1] + box_sz[1] / 2, -center[2]))
    else:
        translate = np.asarray((-center[0], -center[1], -center[2] + box_sz[2] / 2))

    return translate, scale, box_sz, center


class async_loading_wrapper:
    def __init__(
        self,
        mode="event",  # can be "event" or "editor"
        enabled: bool = True,
        status: dict = {},
        syncloads: bool = True,
        n_events: int = 2,
        sub=None,
        **kwargs,
    ):
        self.timeout = kwargs.get("timeout", float(os.getenv("RENDERING_TIMEOUT", "600")))
        self.enabled = enabled
        self.status = status
        self.syncloads = syncloads
        self.n_events = n_events
        self.mode = mode

    def get_status(self):
        """Get the status of the renderer to see if anything is loading"""
        context = omni.usd.get_context()
        return context.get_stage_loading_status()

    def is_loading(self):
        """convenience function to see if any files are being loaded"""
        _, files_loaded, total_files = self.get_status()
        logger.debug(f" loading [{files_loaded}/ {total_files}]")
        # return files_loaded < total_files
        return total_files > 0

    async def __aenter__(self):
        self.loading_start = time.time()
        self.queue = asyncio.Queue()

        async def task():
            while True:
                event = await stage_event_compat()
                await self.queue.put(event)

        self.event_listen_task = asyncio.create_task(task())
        return self

    async def __aexit__(self, *args, **kwargs):
        if self.enabled:
            if self.mode == "event":
                assets_loaded_count = 0
                required_assets_loaded = 1
                if not self.syncloads:
                    required_assets_loaded = int(self.n_events)

                if required_assets_loaded == 0:
                    logger.debug("Not waiting for ASSETS LOADED at all, stage load complete.")
                    self.status["loaded"] = True
                    self.status["load_time"] = time.time() - self.loading_start
                else:
                    logger.debug(f"Waiting for {required_assets_loaded} ASSETS LOADED event(s)")

                    self.status["loaded"] = False
                    while time.time() - self.loading_start < self.timeout:
                        event = await self.queue.get()

                        # TODO: compare to actual enum value when Kit fixes its return types
                        if event == int(omni.usd.StageEventType.ASSETS_LOADED):
                            assets_loaded_count += 1
                            carb.log_info(f"Received ASSETS_LOADED #{assets_loaded_count}")
                            # The user can specify how many assets_loaded to wait for in async mode
                            if assets_loaded_count < required_assets_loaded:
                                continue
                            logger.debug(f"Met threshold of {required_assets_loaded}, all assets loaded")
                            self.status["loaded"] = True
                            break
                        # error that something went wrong
                        elif event == int(omni.usd.StageEventType.OPEN_FAILED):
                            logger.debug("Received OPEN_FAILED")
                            self.status["error"] = "Received OPEN_FAILED"
                            break
                        elif event == int(omni.usd.StageEventType.ASSETS_LOAD_ABORTED):
                            logger.debug("Received ASSETS_LOAD_ABORTED")
                            self.status["error"] = "Received ASSETS_LOAD_ABORTED"
                            break
                        elif event == int(omni.usd.StageEventType.CLOSING):
                            logger.debug("Received CLOSING")
                            self.status["error"] = "Received CLOSING"
                            continue
                        elif event == int(omni.usd.StageEventType.CLOSED):
                            logger.debug("Received CLOSED")
                            self.status["error"] = "Received CLOSED"
                            continue

                self.status["load_time"] = time.time() - self.loading_start
                carb.log_info(f"event-based loading done in {self.status['load_time']}s (timeout: {self.timeout:.2f}s)")
            elif self.mode == "editor":
                # log the beginning of waiting for omni event
                logger.debug("Waiting for Omni Editor to finish loading:")
                await asyncio.sleep(1)
                bg = time.time()
                while self.is_loading() and time.time() - bg < self.timeout:
                    await asyncio.sleep(1)

                # log that asset is loaded
                carb.log_info(f"editor-based loading done in {time.time() - bg:.2f}s (timeout: {self.timeout:.2f}s)")
                self.status["loaded"] = not self.is_loading()
            else:
                raise ValueError(f"Unknown mode: '{self.mode}'")

            # task
            try:
                self.event_listen_task.cancel()
            except asyncio.CancelledError:
                pass
        else:
            self.status["loaded"] = True

        # make sure all the materials are loaded
        await asyncio.sleep(0.2)


def set_active_camera(camera: Usd.Typed):
    """Set active camera in Kit.

    Args:
        camera: reference to an object in a USD stage
    """
    # pass
    path = str(camera.GetPath())
    viewport_window = omni.kit.viewport_legacy.get_default_viewport_window()
    if get_prim_exists(path):
        viewport_window.set_active_camera(path)
    else:
        carb.log_warn(f"Object at '{path}' does not exist")


def get_prim_exists(path: str) -> bool:
    """Check if the prim at a certain path exists"""
    usd_context = omni.usd.get_context()
    stage = usd_context.get_stage()
    prim = stage.GetPrimAtPath(path)
    return not (str(prim) == "invalid null prim")


def get_stage_content() -> Tuple[List[Tuple[str, str]], Dict[str, List[Any]], Dict[str, str]]:
    """Get stage content.

    Returns:
        tuple: list of tuples of root paths and types in the stage
    """
    # get current omniverse stage
    stage = omni.usd.get_context().get_stage()

    subpaths = []
    types = {}

    material_binds = {}
    for prim in stage.Traverse():

        # detect if material have bindings and if they refer to the root of the project add them to the dictionary
        if prim.HasRelationship("material:binding"):
            rel = prim.GetRelationship("material:binding")
            material_binds[str(prim.GetPath())] = [t for t in rel.GetTargets() if str(t).startswith("/")]

        name = str(prim.GetPath())
        types[name] = str(prim.GetTypeName())
        subpaths.append(f"/{name.split('/')[1]}")

    subpaths = list(set(subpaths))

    # get corresponding types
    res = [(p, types[p]) for p in subpaths]

    return res, material_binds, types


def create_domelight_texture(shade: int):
    """Create Dome Light texture in a writable temp directory.

    Args:
        shade (int): shading level of the dome light
    """
    tex_dir = os.path.join(tempfile.gettempdir(), "deepsearch_textures")
    os.makedirs(tex_dir, exist_ok=True)
    tex_path = os.path.join(tex_dir, "grey.jpg")

    if not os.path.exists(tex_path):
        img = Image.fromarray(np.ones((10, 10, 3), dtype=np.uint8) * shade)
        img.save(tex_path)


async def close_stage(app):
    context = omni.usd.get_context()
    # close stage stage
    with print_wrapper("closing stage", logger=logger.debug, print_after=False):
        await context.close_stage_async()

    # update Kit
    with print_wrapper("waiting for stage closing (sleep)", logger=logger.debug, print_after=False):
        await wait_n_frames(app, n=60)
        await asyncio.sleep(5)
    return omni.usd.get_context()


async def recreate_stage(app, n_tries: int = 5, timeout: Optional[float] = None):
    # close stage
    context = await close_stage(app)
    # create a new one
    counter = 0
    while counter < n_tries:
        try:
            with print_wrapper("creating stage", logger=logger.debug, print_after=False):
                await asyncio.wait_for(context.new_stage_async(), timeout=timeout)
            break
        except asyncio.TimeoutError:
            counter += 1
            if counter >= n_tries:
                carb.log_error(f"FAILED creating a new stage ({n_tries} tries, timeout: {timeout})")
                raise FailedCreatingStage()

    # update Kit
    await wait_n_frames(app, n=10)
    # get stage
    with print_wrapper("getting stage", logger=logger.debug, print_after=False):
        return context.get_stage()


async def camera_fit_to_prim(
    camera: Usd.Typed,
    focus_prim: Usd.Typed,
    bbox_size: Optional[Union[Tuple[float, float, float], np.ndarray]] = None,
    distance_multiplier: float = 1.2,
):
    """Move camera rig to centroid elevation and set camera distance so to fit `focus_prim`."""
    if bbox_size is None:
        # compute translation
        _, _, bbox_size, _ = get_prim_bounds(focus_prim)

    const = -1 * float(1e38)
    if bbox_size[0] < const or bbox_size[1] < const or bbox_size[2] < const:
        bbox_size = np.array([1, 1, 1])

    prim_bounds_radius: float = np.sqrt(np.sum((bbox_size / 2) ** 2))
    # Calculate distance to move camera from asset
    distance = abs(prim_bounds_radius * 2)
    distance *= distance_multiplier  # Scale factor of distance from object centroid to camera
    UsdGeom.Xformable(camera).ClearXformOpOrder()
    UsdGeom.Xformable(camera).AddTranslateOp().Set((0.0, 0.0, distance))


@asynccontextmanager
async def camera_fit_to_prim_wrapper(app, *args, **kwargs):
    async def task():
        while True:
            await camera_fit_to_prim(*args, **kwargs)
            await app.next_update_async()

    loop = asyncio.get_event_loop()
    t = loop.create_task(task())

    try:
        yield
    finally:
        t.cancel()
        # await for task cancellation
        try:
            await t
        except asyncio.CancelledError:
            pass
        except Exception as e:
            carb.log_warning(f"camera fit context exception: {str(e)}")
            # logger.debug("camera fit to prim task is cancelled")


def get_config(logger: Callable = logger.debug, light_type: str = "dome") -> dict:
    """Get the config for Omniverse Kit.

    Args:
        logger (callable, optional): logging function. Defaults to logger.debug.
        light_type (str, optional): type of lighting in the scene. Defaults to "dome".
        render_existing_views (bool, optional): If ``True`` - render existing views. Defaults to ``False``.

    Raises:
        ValueError: when light type is not known

    Returns:
        dict: configuration dictionary
    """
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    config = toml.load(f"{bin_path}/../../../../../config/scene_config.toml")
    config["assets_root_dir"] = "."

    # disable all light sources
    for prim in config["prims"]:
        if prim["prim_type"] in ["DomeLight", "SphereLight"]:
            prim["enabled"] = False

    # set the light given the light_type
    if light_type == "dome":
        tex_dir = os.path.join(tempfile.gettempdir(), "deepsearch_textures")
        for it in range(len(config["prims"])):
            if config["prims"][it]["prim_type"] == "DomeLight":
                config["prims"][it]["enabled"] = True
                config["prims"][it]["attributes"]["inputs:texture:file"] = os.path.join(tex_dir, "grey.jpg")
                break
    elif light_type == "sphere":
        for it in range(len(config["prims"])):
            if config["prims"][it]["prim_type"] == "SphereLight":
                config["prims"][it]["enabled"] = True
                break
    else:
        raise ValueError(f"Unknow light type: {light_type}")

    # log some information
    logger("Scene:")
    for p in config["prims"]:
        prepare_message(
            msg=f"{p['path']}",
            item_list=[f"{k}: {v}" for k, v in p.items() if k != "path"],
            logger=logger,
        )

    # return updated config
    return config


async def stage_event_compat() -> int:
    """Calls `kit.stage_event` in a compatible way between versions"""
    # at some point in 2020.3 the APIs changed again
    usd_context = omni.usd.get_context()
    logger.debug("Waiting for an event")
    if hasattr(usd_context, "next_stage_event_async"):
        stage_event_fn = omni.usd.get_context().next_stage_event_async
    else:
        stage_event_fn = omni.kit.asyncapi.stage_event

    result = await stage_event_fn()
    # Old behaviour
    if isinstance(result, int):
        logger.debug(f"stage_event() -> {event_map[result]}")
        return result

    # New behaviour somewhere in 2020.3
    event, _ = result
    event = int(event)
    try:
        logger.debug(f"stage_event() -> ({event_map[event]}, {_})")
    except KeyError:
        logger.debug(f"stage_event() -> ({event} (unknown type), {_})")
    except Exception as e:
        carb.log_error(str(e))
        logger.debug(f"stage_event() -> ({event}, {_})")

    return event
