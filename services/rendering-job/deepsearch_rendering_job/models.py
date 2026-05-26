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

import json
from enum import Enum
from typing import Dict, List, Optional, Union

from prometheus_client import Gauge
from pydantic import BaseModel, BaseSettings, Field, validator
from typing_extensions import TypedDict


class MainServiceSettings(BaseSettings):
    prom_metric_namespace: str = "usdsearch"
    prom_metric_subsystem: str = "rendering"


kit_process_memory_gauge: Gauge = Gauge(
    "kit_process_memory",
    "Memory usage of the kit process in MB",
    labelnames=["worker_id", "memory_limit"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
kit_process_pid_gauge: Gauge = Gauge(
    "kit_process_pid",
    "PID of the kit process",
    labelnames=["worker_id"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
kit_process_memory_gauge_percentage: Gauge = Gauge(
    "kit_process_memory_percentage",
    "Memory usage percentage of the kit process",
    labelnames=["worker_id", "memory_limit"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
kit_process_rendering_time_gauge: Gauge = Gauge(
    "kit_process_rendering_time",
    "Rendering time of the kit process",
    labelnames=["worker_id"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
kit_process_rendering_time_percentage_gauge: Gauge = Gauge(
    "kit_process_rendering_time_percentage",
    "Rendering time percentage of the kit process",
    labelnames=["worker_id"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
waiting_requests_gauge: Gauge = Gauge(
    "waiting_requests",
    "Number of waiting requests",
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)
response_status_gauge: Gauge = Gauge(
    "response_status",
    "Status of the response",
    labelnames=["status"],
    namespace=MainServiceSettings().prom_metric_namespace,
    subsystem=MainServiceSettings().prom_metric_subsystem,
)


class StatusType(str, Enum):
    FINISHED = "finished"
    EXCEPTION = "exception"


class ResponseType(TypedDict):
    status: StatusType


class KitSubprocessException(Exception):
    pass


class KitOutOfMemorySubprocessException(Exception):
    pass


class Authentication(BaseSettings):
    omni_user: str = ""
    omni_pass: str = ""
    aws_bucket: str = ""
    aws_region: str = ""
    aws_access_key: str = ""
    aws_access_key_id: str = ""
    aws_endpoint: str | None = None
    storage_api_url: str = Field(
        default="",
        description="URL of the storage API to use. If provided - all other storage settings are ignored inside Kit.",
    )
    storage_api_token: Optional[str] = Field(default=None, description="Token for the Storage API")
    # OpenID config
    storage_api_openid_client_id: Optional[str] = Field(
        default=None, description="Client ID for the Storage API OpenID"
    )
    storage_api_openid_client_secret: Optional[str] = Field(
        default=None, description="Client secret for the Storage API OpenID"
    )
    storage_api_openid_token_url: Optional[str] = Field(
        default=None, description="OpenID token URL for the Storage API OpenID"
    )
    storage_api_openid_scope: Optional[str] = Field(default=None, description="OpenID scope for the Storage API OpenID")
    storage_api_openid_grant_type: Optional[str] = Field(
        default="client_credentials",
        description="OpenID grant type for the Storage API OpenID",
    )
    storage_api_token_refresh_interval: Optional[int] = Field(
        default=1800,
        description="Token refresh interval for the Storage API OpenID (in seconds)",
    )


class RenderSettings(BaseModel):
    adjust_camera_multiplier: bool = Field(default=True, title="trigger to automatically adjust camera view")
    render_existing_views: bool = Field(default=True, title="trigger to automatically render existing camera views")
    filter_by_segmentation: bool = Field(default=False, title="If True, drop views where the semantic mask is empty")
    sensors: Optional[List[str]] = Field(default=None, title="List of required sensors")

    @validator("sensors", pre=True)
    def _parse_sensors(cls, value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [value]
        return value


class RenderingRequest(BaseSettings):
    url_list: List[str] = Field(description="List of URLs")
    mtl_name_dict: Optional[Dict[str, Optional[List[str]]]] = Field(
        default=None,
        title="MTL name that need to be rendered. (only relevant for MDL files)",
    )
    ws: Optional[str] = Field(default=None, title="Websocket endpoint, for results posting")
    http: Optional[str] = Field(default=None, title="HTTP endpoint, for results posting")
    redis: Optional[str] = Field(default=None, title="Redis endpoint, for results posting")
    local_path: Optional[str] = Field(default=None, title="Local path to the asset")
    width: Optional[int] = Field(default=None, title="Width of the thumbnail")
    height: Optional[int] = Field(default=None, title="Height of the thumbnail")
    mdl_template_url: Optional[str] = Field(
        default=None,
        title="Template URL that need to be rendered. Only relevant for MDL files",
    )
    mdl_stdin: Optional[str] = Field(
        default=None,
        title="STDIN that need to be rendered. Only relevant for MDL files",
    )
    render_settings: Optional[RenderSettings] = Field(default=None, title="Rendering settings passed to Kit")

    class Config:
        env_prefix = "rendering_request_"
        env_nested_delimiter = "__"


class RenderingServiceSettings(BaseSettings):
    host: str = "http://localhost"
    suffix: str = "deepsearch/rendering"
    wait_till_ready: bool = True
    start_kit_worker: bool = True
    kit_worker_log_level: str = "warn"  # available options: warn, info, Verbose
    port: int = 8223
    cache_location: str = "/cache"
    asset_rendering_timeout: float = 30 * 60  # 30 minutes
    extension_folder: str = "/exts"
    hssc_uri: Optional[str] = None
    enable_shader_cache_wrapper: bool = False
    kit_worker_memory_limit: int = -1  # unlimited

    class Config:
        env_prefix = "rendering_service_settings_"


class ConverterSettings(BaseSettings):
    bake_mdl_material: bool = False
    baking_scales: bool = False
    convert_fbx_to_y_up: bool = False
    convert_fbx_to_z_up: bool = False
    convert_stage_up_y: bool = False
    convert_stage_up_z: bool = False
    create_world_as_default_root_prim: bool = True
    disabling_instancing: bool = False
    embed_mdl_in_usd: bool = True
    embed_textures: bool = True
    export_hidden_props: bool = False
    export_mdl_gltf_extension: bool = False
    export_preview_surface: bool = False
    export_separate_gltf: bool = False
    ignore_animations: bool = False
    ignore_camera: bool = False
    ignore_flip_rotations: bool = False
    ignore_light: bool = False
    ignore_materials: bool = False
    ignore_pivots: bool = False
    ignore_unbound_bones: bool = False
    keep_all_materials: bool = False
    merge_all_meshes: bool = False
    single_mesh: bool = False
    smooth_normals: bool = True
    support_point_instancer: bool = False
    use_double_precision_to_usd_transform_op: bool = False
    use_meter_as_world_unit: bool = False


class ConverterServiceSettings(BaseSettings):
    host: str = "http://localhost"
    suffix: str = "convert/asset/process"
    port: int = 8223
    asset_conversion_timeout: int = 15 * 60  # 15 minutes
    converter_settings: ConverterSettings = ConverterSettings()

    class Config:
        env_prefix = "conversion_service_settings_"


class ConversionJobStatus(str, Enum):
    ok = "ok"
    error = "error"
    conversion_error = "conversion_error"
    skipped = "skipped"


class RenderingStatus(str, Enum):
    load_error = "load_error"
    success = "success"
    render_error = "render_error"
    empty_scene = "empty_scene"
    error = "error"
    timeout = "timeout"
    invalid_mtl_names = "invalid_mtl_names"
    process_limit_reached = "process_limit_reached"
    unsupported_media_type = "unsupported_media_type"
    out_of_memory = "out_of_memory"


class ConversionJobInfo(BaseModel):
    source_path: str
    output_path: Optional[str] = None
    status: Union[str, ConversionJobStatus]
    error: Optional[str] = None


class KitWorkerSettings(BaseSettings):
    n_workers: int = 1
    batch_size: int = 1
    n_allowed_waiting_requests: int = Field(default=-1, title="maximum number of waiting requests. -1 means unlimited")
    kit_extra_args: Optional[List[str]] = Field(default=None, title="Extra arguments to pass to Kit")

    class Config:
        env_prefix = "kit_worker_settings_"
