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
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

logger = logging.getLogger("deepsearch_api.telemetry")


class JSONStdoutSpanExporter(SpanExporter):
    """Custom OpenTelemetry span exporter that outputs business events to stdout as JSON"""

    @staticmethod
    def _add_es_prefixes(data: Any, parent_key: str = "") -> Any:
        """Recursively add Elasticsearch mapping prefixes to all fields"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # Skip already prefixed keys
                if any(
                    key.startswith(prefix + "_")
                    for prefix in [
                        "ts",
                        "ni",
                        "ns",
                        "ws",
                        "textws",
                        "text",
                        "csv",
                        "b",
                        "obj",
                        "nested",
                        "l",
                        "d",
                        "s",
                        "rl",
                        "rd",
                        "rts",
                        "flat",
                    ]
                ):
                    result[key] = JSONStdoutSpanExporter._add_es_prefixes(value, key)
                    continue

                prefixed_key = JSONStdoutSpanExporter._get_prefixed_key(key, value)
                result[prefixed_key] = JSONStdoutSpanExporter._add_es_prefixes(value, prefixed_key)
            return result
        elif isinstance(data, list):
            return [JSONStdoutSpanExporter._add_es_prefixes(item, parent_key) for item in data]
        else:
            return data

    @staticmethod
    def _get_prefixed_key(key: str, value: Any) -> str:
        """Determine the appropriate ES mapping prefix for a field based on its value"""
        # Special handling for timestamp fields (only actual timestamps, not durations)
        if key in ["time", "timestamp"] and isinstance(value, int) and 1000000000 <= value <= 9999999999999:
            return f"ts_{key}"

        # Type-based prefixes
        if isinstance(value, bool):
            return f"b_{key}"
        elif isinstance(value, int):
            # Check if it's a duration in milliseconds (should be float)
            if key.endswith("_ms") or "time_ms" in key:
                return f"d_{key}"
            return f"l_{key}"
        elif isinstance(value, float):
            return f"d_{key}"
        elif isinstance(value, str):
            # Use keyword prefix for strings by default
            return f"s_{key}"
        elif isinstance(value, dict):
            return f"obj_{key}"
        elif isinstance(value, list):
            # Check if it's a list of objects (nested) or simple values
            if value and isinstance(value[0], dict):
                return f"nested_{key}"
            else:
                return f"s_{key}"  # Default to string for simple arrays
        else:
            return f"s_{key}"  # Default to string for unknown types

    def export(self, spans, **kwargs) -> SpanExportResult:
        try:
            for span in spans:
                # Only export business telemetry spans (those with telemetry_key)
                if not span.attributes or "telemetry_key" not in span.attributes:
                    continue

                # Extract event data from span
                telemetry_key = span.attributes.get("telemetry_key")
                event_attributes = dict(span.attributes)

                event = {
                    "time": int(time.time() * 1000),  # Current timestamp in milliseconds
                    "service": "deepsearch-api",
                    **event_attributes,
                }

                # Apply ES mapping prefixes to all fields
                prefixed_event = JSONStdoutSpanExporter._add_es_prefixes(event)
                logger.info(json.dumps(prefixed_event))  # Direct stdout output

            return SpanExportResult.SUCCESS
        except Exception as e:
            logger.error(f"Failed to export telemetry spans: {e}")
            return SpanExportResult.FAILURE

    def shutdown(self, timeout_millis: float = 30_000, **kwargs) -> None:
        pass

    def force_flush(self, timeout_millis: float = 30_000, **kwargs) -> bool:
        return True


class OpenTelemetryBusinessTelemetry:
    """Business telemetry for search events using OpenTelemetry traces with immediate JSON stdout export"""

    def __init__(self, enabled: bool = None):
        # Check environment variable for telemetry enablement
        if enabled is None:
            enabled = os.getenv("SEARCH_TELEMETRY_STDOUT", "true").lower() in (
                "true",
                "1",
                "yes",
                "on",
            )

        self.enabled = enabled
        self.processor = None
        if self.enabled:
            # Set up OpenTelemetry tracing with immediate JSON export for business events
            logger.info("Initializing OpenTelemetry business telemetry - JSON Stdout Exporter")
            resource = Resource.create({"service.name": "deepsearch-api-telemetry"})
            tracer_provider = TracerProvider(resource=resource)

            # Add our custom JSON stdout exporter with immediate processing
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            self.processor = BatchSpanProcessor(
                JSONStdoutSpanExporter(),
                max_export_batch_size=1,
                export_timeout_millis=1,
                schedule_delay_millis=1,
            )
            tracer_provider.add_span_processor(self.processor)

            # Get the tracer for business events (separate from main tracing)
            self.tracer = tracer_provider.get_tracer("deepsearch_business_events")

    @contextmanager
    def telemetry_context(self, username: str = None) -> Generator[Dict[str, Any], None, None]:
        """Context manager for collecting telemetry events with user context"""
        if not self.enabled:
            yield {}
            return

        context = {"username": username} if username else {}
        try:
            yield context
        finally:
            # Context cleanup if needed
            pass

    @contextmanager
    def record_query_event(self, query: str, username: str = None, **attributes):
        """Context manager for recording search query events with span tracking"""
        if not self.enabled:
            yield
            return

        attrs = {
            "telemetry_key": "search_query_total",  # Special attribute for event identification
            "query": query[:256],  # Truncate long queries
            "username": username or "anonymous",
            **attributes,
        }

        # Create a span that wraps the entire query execution
        with self.tracer.start_as_current_span("search_query_event") as span:
            # Set all attributes on the span
            for key, value in attrs.items():
                if value is not None:
                    span.set_attribute(key, value)

            start_time = time.time()
            try:
                yield span

                # Record success attributes
                processing_time_ms = (time.time() - start_time) * 1000
                span.set_attribute("processing_time_ms", processing_time_ms)
                span.set_attribute("status", "success")

            except Exception as e:
                # Record error attributes
                processing_time_ms = (time.time() - start_time) * 1000
                span.set_attribute("processing_time_ms", processing_time_ms)
                span.set_attribute("status", "error")
                span.set_attribute("error_type", type(e).__name__)
                span.set_attribute("n_results", 0)
                raise

    def record_results_presented(
        self,
        query: str,
        n_results: int,
        time_ms: float,
        username: str = None,
        **attributes,
    ):
        """Record search results presentation event as a span"""
        if not self.enabled:
            return

        attrs = {
            "telemetry_key": "search_results_presented_total",  # Special attribute for event identification
            "query": query[:256],
            "username": username or "anonymous",
            "n_results": n_results,
            "time_ms": time_ms,
            **attributes,
        }

        # Create a short-lived span for the business event
        with self.tracer.start_as_current_span("results_presented_event") as span:
            # Set all attributes on the span
            for key, value in attrs.items():
                if value is not None:
                    span.set_attribute(key, value)

    def force_flush(self, timeout_millis: float = 30_000) -> bool:
        """Force flush any pending telemetry data"""
        if not self.enabled or not self.processor:
            return True
        return self.processor.force_flush(timeout_millis)


# Global telemetry instance
business_telemetry = OpenTelemetryBusinessTelemetry()
