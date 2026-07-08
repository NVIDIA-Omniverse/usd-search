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

"""LLM query parsing: turn free-text queries into the existing search
request params via an LLM-produced structured intermediate representation (IR).

The flow is parse-only: ``LLMParseExtractor`` calls the configured LLM provider
with a JSON-schema-constrained ``SearchIR`` output, and ``ir_to_request_params``
deterministically maps that IR onto ``DeepSearchSearchRequestV2`` fields. The
frontend merges the mapped params into its existing search request, so all
existing search plumbing (vector queries, RRF, VLM validation) is reused.

A single field registry (``fields.py``) is the source of truth for the IR field
enum, the grounding system prompt, the validator, and the mapper.
"""

from .config import LLMParseSettings
from .extractor import LLMParseExtractionError, LLMParseExtractor
from .fields import REGISTRY, IRFieldName, Operator
from .mapper import ir_to_request_params, map_ir
from .models import DroppedFilter, DroppedFilterReason, IRFilter, SearchIR

__all__ = [
    "LLMParseSettings",
    "LLMParseExtractor",
    "LLMParseExtractionError",
    "REGISTRY",
    "IRFieldName",
    "Operator",
    "ir_to_request_params",
    "map_ir",
    "IRFilter",
    "SearchIR",
    "DroppedFilter",
    "DroppedFilterReason",
]
