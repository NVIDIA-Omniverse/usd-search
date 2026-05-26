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
from typing import Any, Optional

# third party modules
import numpy as np
import tritonclient.grpc as grpcclient
from tritonclient.grpc import service_pb2
from tritonclient.utils import np_to_triton_dtype, serialize_byte_tensor

# local / proprietary modules
from .interface import TritonClientException


def set_infer_input_data(infer_input: grpcclient.InferInput, input_tensor: np.ndarray) -> None:
    """Set tensor data on InferInput without using the broken set_data_from_numpy method.

    This works around a protobuf 5.x incompatibility where parameters.pop(key, default)
    is no longer supported.
    """
    dtype = np_to_triton_dtype(input_tensor.dtype)
    if infer_input._input.datatype != dtype:
        raise TritonClientException(
            f"got unexpected datatype {dtype} from numpy array, expected {infer_input._input.datatype}"
        )

    valid_shape = True
    if len(infer_input._input.shape) != len(input_tensor.shape):
        valid_shape = False
    else:
        for i in range(len(infer_input._input.shape)):
            if infer_input._input.shape[i] != input_tensor.shape[i]:
                valid_shape = False
    if not valid_shape:
        raise TritonClientException(
            f"got unexpected numpy array shape [{str(input_tensor.shape)[1:-1]}], "
            f"expected [{str(list(infer_input._input.shape))[1:-1]}]"
        )

    # Clear shared memory params safely (without using .pop(key, default))
    for key in [
        "shared_memory_region",
        "shared_memory_byte_size",
        "shared_memory_offset",
    ]:
        if key in infer_input._input.parameters:
            del infer_input._input.parameters[key]

    if infer_input._input.datatype == "BYTES":
        serialized_output = serialize_byte_tensor(input_tensor)
        if serialized_output.size > 0:
            infer_input._raw_content = serialized_output.item()
        else:
            infer_input._raw_content = b""
    else:
        infer_input._raw_content = input_tensor.tobytes()


def get_inference_request(
    model_name: str,
    inputs: list[grpcclient.InferInput],
    model_version: str,
    request_id: str,
    outputs: list[grpcclient.InferRequestedOutput],
    sequence_id: int,
    sequence_start: bool,
    sequence_end: bool,
    priority: int,
    timeout: Optional[float],
    parameters: Optional[dict[str, Any]],
) -> service_pb2.ModelInferRequest:
    request = service_pb2.ModelInferRequest()
    request.model_name = model_name
    request.model_version = model_version
    if request_id != "":
        request.id = request_id
    for infer_input in inputs:
        request.inputs.extend([infer_input._get_tensor()])
        if infer_input._get_content() is not None:
            request.raw_input_contents.extend([infer_input._get_content()])
    if outputs is not None:
        for infer_output in outputs:
            request.outputs.extend([infer_output._get_tensor()])
    if sequence_id != 0 and sequence_id != "":
        if isinstance(sequence_id, str):
            request.parameters["sequence_id"].string_param = sequence_id
        else:
            request.parameters["sequence_id"].int64_param = sequence_id
        request.parameters["sequence_start"].bool_param = sequence_start
        request.parameters["sequence_end"].bool_param = sequence_end
    if priority != 0:
        request.parameters["priority"].uint64_param = priority
    if timeout is not None:
        request.parameters["timeout"].int64_param = timeout

    if parameters:
        for key, value in parameters.items():
            if (
                key == "sequence_id"
                or key == "sequence_start"
                or key == "sequence_end"
                or key == "priority"
                or key == "binary_data_output"
            ):
                raise TritonClientException(f'Parameter "{key}" is a reserved parameter and cannot be specified.')
            else:
                if isinstance(value, str):
                    request.parameters[key].string_param = value
                elif isinstance(value, bool):
                    request.parameters[key].bool_param = value
                elif isinstance(value, int):
                    request.parameters[key].int64_param = value
                elif isinstance(value, float):
                    request.parameters[key].double_param = value
                else:
                    raise TritonClientException(
                        f'The parameter datatype "{type(value)}" for key "{key}" is not supported.'
                    )

    return request
