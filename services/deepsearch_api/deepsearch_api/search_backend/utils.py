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

import base64
import json
import logging
import os
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

import orjson
from opensearchpy.serializer import JSONSerializer
from opentelemetry import trace

from .models_extra import TelemetryContext, TelemetryExtraFields

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

ORJSON_TRACING_ENABLED = os.getenv("ORJSON_TRACING_ENABLED", "false").lower() == "true"


class GuiApps(str, Enum):
    navigator = "navigator"
    usd_composer = "USD.Composer"


def parse_arg_input_and_or(input_str: str) -> list[list[str]]:
    return [or_group.split(",") for or_group in input_str.split(";")]


def extract_embeddings_from_hit(hit: Dict[str, Any]) -> Optional[List[float]]:
    return extract_embeddings_from_hit_source(hit.get("_source", {}))


def extract_embeddings_from_hit_source(source: Dict[str, Any]) -> Optional[List[float]]:
    """Extract Siglip2 embeddings from a search hit."""
    try:
        # Get embeddings from the _source
        siglip2_embeddings = source.get("siglip2-embedding", [])
        if not siglip2_embeddings or len(siglip2_embeddings) == 0:
            return None

        # Return the first embedding if multiple exist
        embedding_data = siglip2_embeddings[0]
        if isinstance(embedding_data, dict) and "embedding" in embedding_data:
            embedding = embedding_data["embedding"]
            if isinstance(embedding, list) and len(embedding) > 0:
                return embedding

        return None
    except Exception as e:
        logger.warning(f"Failed to extract embeddings from hit: {e}")
        return None


def get_default_telemetry_context(session_id: Optional[str] = None) -> TelemetryContext:
    if session_id is None:
        session_id = str(uuid.uuid4())
    return TelemetryContext(
        session_id=session_id,
        app_name="undefined",
        app_version="undefined",
        ui_name="undefined",
        ui_version="undefined",
    )


def get_telemetry_extra_fields(telemetry_context: TelemetryContext, token: str) -> TelemetryExtraFields:
    """Get extra telemetry information from telemetry context.

    Args:
        telemetry_context (TelemetryContext): telemetry context received from the client app
        token (str): user access token

    Returns:
        TelemetryExtraFields: additional telemetry fields
    """
    if telemetry_context.kit_version is None:
        kitVersion = telemetry_context.app_version
    else:
        kitVersion = telemetry_context.kit_version

    return TelemetryExtraFields(
        source=extract_telemetry_user_id_from_jwt(token),
        user_initiated=telemetry_context.app_name in list(GuiApps),
        deepsearch_session_id=telemetry_context.session_id,
        session_id=telemetry_context.session_id,
        appName=telemetry_context.app_name,
        appVersion=telemetry_context.app_version,
        uiName=telemetry_context.ui_name,
        uiVersion=telemetry_context.ui_version,
        app=f"{telemetry_context.app_name}_{telemetry_context.app_version}",
        kitVersion=kitVersion,
    )


def get_jwt_payload(token: str) -> dict:
    encoded_payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(encoded_payload + "=" * (4 - len(encoded_payload) % 4)))


def extract_telemetry_user_id_from_jwt(token: Optional[str]) -> str:
    if token is None:
        logger.warning("JWT token is not provided")
        return "unknown"

    try:
        payload = get_jwt_payload(token)
    except IndexError:
        logger.warning("Error parsing JWT")
        return "unknown"
    except Exception as exc_info:
        logger.exception("JWT payload exception", exc_info=exc_info)
        return "unknown"
    try:
        email = payload["profile"]["email"]
        if len(email) > 0:
            return email
        return f'{payload["profile"]["first_name"]}_{payload["profile"]["last_name"]}'
    except KeyError as exc_info:
        logger.exception("Error extracting user_id from JWT", exc_info=exc_info)
        return "unknown"


class OrjsonSerializer(JSONSerializer):
    def dumps(self, data):
        if ORJSON_TRACING_ENABLED:
            with tracer.start_as_current_span("orjson_serialize"):
                return orjson.dumps(data)
        else:
            return orjson.dumps(data)

    def loads(self, s):
        if ORJSON_TRACING_ENABLED:
            with tracer.start_as_current_span("orjson_deserialize"):
                return orjson.loads(s)
        else:
            return orjson.loads(s)
