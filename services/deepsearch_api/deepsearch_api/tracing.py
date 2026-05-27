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

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.grpc import (
    GrpcAioInstrumentorClient,
    GrpcInstrumentorClient,
)
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import (
    OTELResourceDetector,
    Resource,
    get_aggregated_resources,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

logger = logging.getLogger(__name__)

resource = get_aggregated_resources(
    [OTELResourceDetector()],
    Resource(
        attributes={
            "service.name": "deepsearch-rest-api",
            "host.name": os.uname()[1],
        }
    ),
)
provider = TracerProvider(resource=resource)

if os.getenv("OTEL_TRACES_EXPORTER", "false").lower() == "true":
    logger.info("Enabling OpenTelemetry traces exporter")
    processor = BatchSpanProcessor(OTLPSpanExporter())
    provider.add_span_processor(processor)

if os.getenv("OTEL_TRACING_STDOUT", "false").lower() == "true":
    logger.info("Enabling OpenTelemetry traces exporter to stdout")
    processor = BatchSpanProcessor(ConsoleSpanExporter())
    provider.add_span_processor(processor)

trace.set_tracer_provider(provider)

tracer = trace.get_tracer(__name__)

# Enable instrumentation for aiohttp clients
AioHttpClientInstrumentor().instrument(tracer_provider=provider)

# Enable instrumentation for httpx clients
HTTPXClientInstrumentor().instrument(tracer_provider=provider)

# Enable instrumentation for grpc clients
grpc_client_instrumentor = GrpcInstrumentorClient()
grpc_client_instrumentor.instrument()
grpcaio_client_instrumentor = GrpcAioInstrumentorClient()
grpcaio_client_instrumentor.instrument()
