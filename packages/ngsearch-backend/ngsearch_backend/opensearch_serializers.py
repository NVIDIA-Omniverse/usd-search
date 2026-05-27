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

from datetime import date, datetime
from decimal import Decimal

from opensearchpy.serializer import JSONSerializer
from opentelemetry import trace

INTEGER_TYPES = ()
FLOAT_TYPES = (Decimal,)
TIME_TYPES = (date, datetime)


tracer = trace.get_tracer(__name__)


class InstrumentedJSONSerializer(JSONSerializer):
    def loads(self, s):
        with tracer.start_as_current_span("json_deserialize"):
            return super().loads(s)

    def dumps(self, data):
        with tracer.start_as_current_span("json_serialize"):
            return super().dumps(data)
