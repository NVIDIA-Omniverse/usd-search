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
from typing import Any, Dict, Optional, Union

from omni.client import PathEvent, StatusType

from ..data import EventMapping, PathType
from . import logger

# local / proprietary modules
from .exceptions import InvalidCommandException


def _get_status(input: Union[PathType, Dict[str, Any]]) -> Optional[str]:
    if isinstance(input, PathType):
        return input.status
    else:
        return input.get("status")


def status_ok(result: Union[PathType, Dict[str, Any]]) -> bool:
    """Checks if the status of the omniverse subscription is not ``OmniErrorType.kOmniErrorTypeOk``.

    Args:
        results: omniverse subscription
    """
    return _get_status(result) == StatusType.OK


def status_latest(result: Union[PathType, Dict[str, Any]]) -> bool:
    """Checks if the status of the omniverse subscription is not ``OmniErrorType.kOmniErrorTypeLatest``. Check :func:`status_ok` for arguments."""
    return _get_status(result) == StatusType.Latest


def status_done(result: Union[PathType, Dict[str, Any]]) -> bool:
    """Checks if the status of the omniverse subscription is not ``OmniErrorType.kOmniErrorTypeLatest``. Check :func:`status_ok` for arguments."""
    return _get_status(result) == StatusType.Done


def assert_on_invalid_command(result: Union[PathType, Dict[str, Any]]):
    if _get_status(result) == StatusType.InvalidCommand:
        raise InvalidCommandException(f"Command is not supported by the server: {result}")


def assert_on_bad_status(result: Union[PathType, Dict[str, Any]], msg: str = "Bad status"):
    """Raise an exception if :func:`status_ok` returns false for an omniverse subscription. Check :func:`status_ok` for arguments."""
    status = _get_status(result)
    if status == StatusType.ConnectionLost:
        raise ConnectionError("Omniverse connection lost")
    if status == StatusType.InvalidPath:
        raise FileNotFoundError(f"file not found in omniverse: {result}")
    if status == StatusType.InvalidCommand:
        raise InvalidCommandException(f"Command is not supported by the server: {result}")
    if not status_ok(result):
        raise Exception(f"{msg} {result.status}")


def get_event_mapping(item) -> Optional[EventMapping]:
    event: PathEvent = getattr(item, "event", None)
    if event is None:
        return None
    if event == PathEvent.ChangeAcl:
        return EventMapping.acl_change
    elif event == PathEvent.Delete:
        return EventMapping.delete
    elif event == PathEvent.Create:
        return EventMapping.create
    elif event == PathEvent.CheckpointsChanged:
        return EventMapping.checkpoints_changed
    else:
        logger.debug("Unknown event: %s", str(event))
        return EventMapping.unknown
