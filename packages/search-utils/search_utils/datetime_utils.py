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

import logging
import os
import re

# standard modules
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Union

from dateutil.relativedelta import relativedelta

# local/proprietary modules
from search_utils.log_utils import set_simple_logger

datetime_utils_logger = logging.getLogger(__name__)


def print_diff(
    diff: relativedelta,
    msg: str = "",
    logger: Callable[[Any], None] = datetime_utils_logger.info,
) -> None:
    """Pretty print the difference between the times

    Args:
        diff: different between time stamps in the dateutil format
        str msg: message that will be shown
        logger: logger that prints information to the screen
    """
    diff_print = " ".join(
        [
            f"{diff.years:d} year(s)" if diff.years > 0 else "",
            f"{diff.months:d} month(s)" if diff.months > 0 else "",
            f"{diff.days:d} day(s)" if diff.days > 0 else "",
            f"{diff.hours:d} hour(s)" if diff.hours > 0 else "",
            f"{diff.minutes:d} minute(s)" if diff.minutes > 0 else "",
            f"{diff.seconds:d} second(s)" if diff.seconds > 0 else "",
        ]
    ).strip(" ")
    diff_print = re.sub(" +", " ", diff_print)

    logger(" in ".join([msg, diff_print]))


def printf_diff_from_timestamp(start: float, finish: float, **kwargs) -> None:
    """Compute and print the difference between the timestep."""
    # get timings in the proper format
    st = datetime.fromtimestamp(start)
    fn = datetime.fromtimestamp(finish)
    # print the difference
    print_diff(relativedelta(fn, st), **kwargs)


def date_to_timestamp(dt: Union[str, int, datetime], format: str = "%Y-%m-%d %H:%M:%S.%f") -> float:
    """Convert date from string format to timestamp.

    Args:
        s: input time in the string, datetime or int formats
        str format: format of the input time
    """
    if isinstance(dt, str):
        dt = datetime.strptime(dt, format)
    elif isinstance(dt, int):
        dt = datetime.fromtimestamp(dt)
    elif isinstance(dt, datetime):
        pass
    else:
        raise ValueError(f"Unsupported date format: {type(dt)}")
    return dt.timestamp()
    # return time.mktime(dt.timetuple())


def date_from_timestamp(
    timestamp: float,
    format: str = "%Y-%m-%d %H:%M:%S.%f",
    tz: Optional[timezone] = None,
) -> str:
    """Convert timestamp to human readable format.

    Args:
        timestamp: timestamp that needs to be converted
        str format: format of the input time
    """
    return datetime.fromtimestamp(timestamp, tz=tz).strftime(format)[:-3]
