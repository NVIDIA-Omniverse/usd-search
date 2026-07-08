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

import asyncio
import os
import time
from dataclasses import dataclass

# standard imports
from typing import Any, Callable, Dict, List, Optional, TypedDict

import psutil

# third party modules
from prometheus_client import Gauge, Info, Summary, start_http_server
from prometheus_client.core import REGISTRY, GaugeMetricFamily

__all__ = ["Gauge", "Info"]


class CallbackCollector:
    def __init__(
        self,
        name,
        metrics: dict,
        description: Optional[str] = None,
        labels: dict = {"omni_instance": "localhost", "omni_service": "test_app"},
    ):
        self.name = name
        self.description = description if description else self.name
        self.labels = labels
        self.metrics = metrics

    def collect(self):
        g = GaugeMetricFamily(
            self.name,
            self.description,
            labels=["metric_name"] + list(self.labels.keys()),
        )
        for m, f in self.metrics.items():
            g.add_metric([m] + [str(v) for _, v in self.labels.items()], f())
        yield g


@dataclass
class Metric:
    name: str
    type: str
    method: str
    hook: Callable


class InfoMetric(Metric):
    def __init__(self, name: str, hook: callable):
        super().__init__(name, "Info", "info", hook)


class GaugeMetric(Metric):
    def __init__(self, name: str, hook: callable = lambda: False):
        super().__init__(name, "Gauge", "set", hook)


class PromMetrics:
    def __init__(
        self,
        metrics: Optional[List[Metric]] = None,
        labels: Optional[Dict[str, str]] = None,
    ):
        self.metrics: Dict[str, Any] = {}
        self.decorators = {}
        self.hooks = {}
        if labels is None:
            self.labels: Dict[str, str] = {}
        else:
            self.labels = labels

        if metrics is not None:
            for m in metrics:
                self.register_metric(m)

        # timing metric
        self.time_metrics = Summary(
            "omnideepsearch_metrics_computation_duration_seconds",
            "Metrics computation duration",
            labelnames=list(self.labels.keys()),
        )
        # add labels to time metrics
        if len(self.labels) > 0:
            self.time_metrics = self.time_metrics.labels(**self.labels)

    def register_metric(self, *metrics: Metric) -> None:
        for metric in metrics:
            self.metrics[metric.name] = metric
            self.decorators[metric.name] = eval(metric.type)(
                metric.name, metric.name, labelnames=list(self.labels.keys())
            )
            self.hooks[metric.name] = metric.hook

    def keys(self):
        return self.hooks.keys()

    def __call__(self, item, *args, **kwargs):
        if len(self.labels) > 0:
            mod = self.decorators[item].labels(**self.labels)
        else:
            mod = self.decorators[item]

        return getattr(mod, self.metrics[item].method)(self.hooks[item](*args, **kwargs))


class CacheMetricsPublisher:
    """Publisher class that computes and exposes prometheus metrics.

    Args:
        metrics (PromMetrics): metrics class that stored various prometheus metrics classes and their hooks.
        timeout (float, optional): Timeout, which which metrics will be recomputed if using the default :py:func:`run` method. Defaults to ``1``.
        port (int, optional): port, at which prometheus metrics will be published. Defaults to ``8000``.
        host (str, optional): host where prometheus http server will be served. Defaults to ``0.0.0.0``.
    """

    def __init__(
        self,
        metrics: PromMetrics = None,
        collectors: list = [],
        timeout: float = 1,
        port: int = 8000,
        host: str = "0.0.0.0",
    ):
        self.timeout = timeout
        self.port = port
        self.host = host
        self.metrics = metrics
        self.collectors = collectors

    def get_metrics(self):
        """Compute all metrics specified in :py:mod:``metrics`` attribute."""
        with self.metrics.time_metrics.time():
            for item in self.metrics.keys():
                self.metrics(item)

    def start_server(self):
        """Start prometheus http server."""
        # start server
        start_http_server(self.port, self.host)
        # register custom collectors
        for c in self.collectors:
            REGISTRY.register(c)

    def run(self):
        """Start prometheus server and recompute the metrics in a loop with certain frequency."""
        # start prometheus server
        self.start_server()
        # run infinite loop
        while True:
            self.get_metrics()
            time.sleep(self.timeout)


class GenericPublisher(CacheMetricsPublisher):
    """Prometheus publisher class for the inference task."""

    def __init__(
        self,
        *args,
        labels: dict = {"omni_instance": "localhost", "omni_service": "test_app"},
        collectors: list = [],
        **kwargs,
    ):
        self.labels = labels
        collectors = [self.prepare_collector(c) for c in collectors]
        metrics = PromMetrics([], labels=labels)
        super().__init__(*args, metrics=metrics, collectors=collectors, **kwargs)

    def prepare_collector(self, collector):
        collector.labels.update(self.labels)
        return collector

    def init_metric(self, m: Metric, labels_dict: dict = {}):
        """Initialize a metric

        Args:
            m (Metric): Metric that need to be added
            labels_dict (dict, optional): Dictionary of labels that will overwrite the default labels in the class. Defaults to ``{}``.

        Returns:
            initialized prometheus metric
        """

        m_lbl_dict = {**self.labels}
        m_lbl_dict.update(labels_dict)

        prom_metric = eval(m.type)(m.name, m.name, labelnames=list(m_lbl_dict.keys()))
        # add labels to time metrics
        if len(m_lbl_dict) > 0:
            prom_metric = prom_metric.labels(**m_lbl_dict)
        return prom_metric


class ProcessMetrics(TypedDict):
    process_memory_info: Gauge
    process_cpu_times: Gauge
    process_cpu_percent: Gauge
    process_status: Info
    process_num_threads: Gauge


class ProcessMetricsCollector:
    """Collect system metrics"""

    def __init__(self, prom_labels: Optional[Dict[str, str]] = None, timeout: float = 5) -> None:
        if prom_labels is None:
            self.prom_labels = {}
        else:
            self.prom_labels = prom_labels

        self._timeout = timeout

        self._pid = os.getpid()
        self._process = psutil.Process(self._pid)

        # define metrics
        self._metrics: ProcessMetrics = self.init_prom_metrics()

    def init_prom_metrics(self) -> ProcessMetrics:
        prom_labels = list(self.prom_labels.keys())
        return dict(
            process_memory_info=Gauge(
                "omni_service_process_memory_info",
                "Process Memory information",
                ["type"] + prom_labels,
            ),
            process_cpu_times=Gauge(
                "omni_service_process_cpu_times",
                "Process CPU utilization total time",
                ["type"] + prom_labels,
            ),
            process_cpu_percent=Gauge(
                "omni_service_process_cpu_percent",
                "Process CPU utilization in percent",
                prom_labels,
            ),
            process_status=Info("omni_service_process_status", "Process Status", prom_labels),
            process_num_threads=Gauge(
                "omni_service_process_num_threads",
                "Process number of threads",
                prom_labels,
            ),
        )

    def get_memory_metrics(self) -> None:
        with self._process.oneshot():
            self._metrics["process_cpu_times"].labels(type="user", **self.prom_labels).set(
                self._process.cpu_times().user
            )
            self._metrics["process_cpu_times"].labels(type="system", **self.prom_labels).set(
                self._process.cpu_times().system
            )
            self._metrics["process_cpu_percent"].labels(**self.prom_labels).set(self._process.cpu_percent())
            self._metrics["process_status"].labels(**self.prom_labels).info({"status": self._process.status()})
            self._metrics["process_num_threads"].labels(**self.prom_labels).set(self._process.num_threads())
            mem = self._process.memory_full_info()
            for name, value in mem._asdict().items():
                self._metrics["process_memory_info"].labels(type=name, **self.prom_labels).set(value)

    async def collect_metrics(self) -> None:
        while True:
            self.get_memory_metrics()
            await asyncio.sleep(self._timeout)
