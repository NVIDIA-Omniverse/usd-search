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

"""VLM search-result validation (the VISION-validation role).

Decides whether a text/image query matches a set of reference images of an asset,
using one shared Inference Hub connection and the model from ``ValidationConfig``.
"""

# standard modules
import base64
import io
import logging
from typing import Optional

# third party modules
import backoff
from PIL import Image
from pydantic import BaseModel

# local / proprietary modules
from ..client import LLMClient, LLMConnectionConfig
from ..exceptions import LLMException
from .validation_fields import ValidationConfig, ValidationFields

logger = logging.getLogger(__name__)


USER_PROMPT_TEXT = """TEXT QUERY: {query}

The reference images showing different views of the 3D asset are attached. Analyze them carefully and determine if the text query matches this asset.
{caption_context}"""

USER_PROMPT_IMAGE = """The FIRST image is the QUERY image to validate.
The REMAINING images are REFERENCE images showing different views of the 3D asset.

Analyze all images and determine if the query image depicts the same 3D asset as shown in the reference images.
{caption_context}"""

USER_PROMPT_TEXT_WITH_CAPTION = """

ADDITIONAL CONTEXT:
The asset has been previously analyzed and described as: "{caption}"

Use this description to help validate if the query matches the asset, but prioritize what you see in the images."""

USER_PROMPT_IMAGE_WITH_CAPTION = """

ADDITIONAL CONTEXT:
The user searched using both a query image AND the text query: "{caption}"

The text query takes STRICT PRIORITY over the image. If the text specifies attributes like color, material, or type, the reference asset MUST match those attributes to be considered a match. A geometrically similar asset that contradicts the text query's attributes is NOT a match."""


class Validation:
    """Validate whether a text/image query matches reference images of a 3D asset."""

    def __init__(
        self,
        config: Optional[ValidationConfig] = None,
        connection: Optional[LLMConnectionConfig] = None,
    ):
        self._config = config or ValidationConfig()
        self._client = LLMClient(
            model=self._config.model,
            connection=connection,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
            reasoning_effort=self._config.reasoning_effort,
        )
        self._validation_fields = ValidationFields(self._config)

    @property
    def config(self) -> ValidationConfig:
        return self._config

    @property
    def model(self) -> str:
        return self._client.model

    @property
    def client(self) -> LLMClient:
        return self._client

    @property
    def validation_fields(self) -> ValidationFields:
        return self._validation_fields

    @property
    def base_model(self) -> type[BaseModel]:
        return self._validation_fields.base_model

    @property
    def system_prompt(self) -> str:
        return self._validation_fields.prompt

    @staticmethod
    def _image_to_base64(image: Image.Image, format: str = "PNG") -> str:
        """Convert a PIL Image to base64 string."""
        buffer = io.BytesIO()
        image.save(buffer, format=format)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")

    def _is_base64(self, s: str) -> bool:
        """Check if a string is likely a base64-encoded image.

        Strings shorter than ``config.min_base64_detect_len`` are assumed to be
        plain text, not image payloads (tunable via
        ``USDSEARCH_VISION_VALIDATION_MIN_BASE64_DETECT_LEN``).
        """
        if not isinstance(s, str):
            return False
        min_len = self._config.min_base64_detect_len
        if len(s) > min_len:
            if s.startswith("data:image"):
                return True
            if s.startswith(("iVBOR", "/9j/", "R0lGO")):  # PNG, JPEG, GIF magic bytes in base64
                return True
            try:
                base64.b64decode(s[:min_len], validate=True)
                return True
            except Exception:
                return False
        return False

    @staticmethod
    def _base64_to_image(base64_string: str) -> Image.Image:
        """Convert a base64 string to PIL Image."""
        if base64_string.startswith("data:image"):
            base64_string = base64_string.split(",", 1)[1]
        image_data = base64.b64decode(base64_string)
        return Image.open(io.BytesIO(image_data))

    def _load_image(self, image_input: str | Image.Image) -> Image.Image:
        """Load an image from a file path, base64 string, or return the PIL Image directly."""
        if isinstance(image_input, Image.Image):
            return image_input
        if isinstance(image_input, str):
            if self._is_base64(image_input):
                return self._base64_to_image(image_input)
            return Image.open(image_input)
        raise ValueError(f"Unsupported image input type: {type(image_input)}")

    def _is_image_path(self, query: str) -> bool:
        """Check if a string is likely an image file path."""
        if not isinstance(query, str):
            return False
        return query.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"))

    def _is_image_input(self, query: str | Image.Image) -> bool:
        """Check if query is an image (PIL Image, file path, or base64 string)."""
        if isinstance(query, Image.Image):
            return True
        if isinstance(query, str):
            return self._is_image_path(query) or self._is_base64(query)
        return False

    def _prepare(self, query, reference_images, asset_caption):
        """Shared prep: build base64 image list + the user prompt for validate/avalidate."""
        if not reference_images:
            raise ValueError("At least one reference image must be provided")

        base64_images = []
        for ref_img in reference_images:
            img = self._load_image(ref_img)
            base64_images.append(self._image_to_base64(img))

        caption_context = ""
        if asset_caption:
            if self._is_image_input(query):
                caption_context = USER_PROMPT_IMAGE_WITH_CAPTION.format(caption=asset_caption)
            else:
                caption_context = USER_PROMPT_TEXT_WITH_CAPTION.format(caption=asset_caption)

        if self._is_image_input(query):
            query_img = self._load_image(query)
            base64_images.insert(0, self._image_to_base64(query_img))
            user_prompt = USER_PROMPT_IMAGE.format(caption_context=caption_context)
        else:
            user_prompt = USER_PROMPT_TEXT.format(query=query, caption_context=caption_context)

        self._client.with_structured_output(self.base_model)
        return base64_images, user_prompt

    def _finalize(self, result, return_detailed):
        if isinstance(result, BaseModel):
            validation_result = result
        else:
            validation_result = self.base_model.model_validate_json(result.content)
        logger.info(
            f"Validation complete: is_match={validation_result.is_match}, "
            f"confidence={validation_result.confidence:.2f}"
        )
        if return_detailed:
            return validation_result
        return validation_result.is_match

    async def avalidate(
        self,
        query: str | Image.Image,
        reference_images: list[Image.Image | str],
        return_detailed: bool = False,
        asset_caption: Optional[str] = None,
    ) -> bool | BaseModel:
        """Validate if a query (text or image) matches reference images of a 3D asset."""
        base64_images, user_prompt = self._prepare(query, reference_images, asset_caption)
        try:
            ainvoke_fn = self._client.ainvoke
            if self._config.max_tries > 0:
                ainvoke_fn = backoff.on_exception(
                    backoff.expo,
                    LLMException,
                    max_tries=self._config.max_tries,
                    logger=logger,
                )(ainvoke_fn)

            result = await ainvoke_fn(prompt=user_prompt, system_prompt=self.system_prompt, base64_images=base64_images)
            return self._finalize(result, return_detailed)
        except LLMException:
            raise
        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            raise
