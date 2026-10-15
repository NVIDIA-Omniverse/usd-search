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

"""Process-wide metrics sink for plugins.

The sink is registered once per process — by the worker that owns the Prometheus
registry and the deployment labels — and read by whichever plugin instance
happens to be running. It deliberately does *not* live on a plugin instance:
``Plugins.get_plugin()`` builds a new plugin on every call, and the worker builds
one per batch, so a sink attached to the worker's own instance would never be
seen by the instance that actually processes items.
"""

from typing import Optional

from .models import PluginPhaseMetrics

_phase_metrics: Optional[PluginPhaseMetrics] = None


def set_phase_metrics(sink: Optional[PluginPhaseMetrics]) -> None:
    """Register (or clear, with ``None``) the sink every plugin reports to."""
    global _phase_metrics
    _phase_metrics = sink


def get_phase_metrics() -> Optional[PluginPhaseMetrics]:
    """The registered sink, or None when nothing is collecting."""
    return _phase_metrics
