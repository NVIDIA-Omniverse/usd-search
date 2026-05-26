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
import base64
import io
import logging
from typing import Callable, Optional

# third party modules
import backoff
from PIL import Image
from pydantic import BaseModel

# local / proprietary modules
from vision_endpoint.validation.validation_fields import (
    ValidationConfig,
    ValidationFields,
    get_validation_model,
)
from vision_endpoint.vlm import BaseVLM, VLMException, VLMService

logger = logging.getLogger(__name__)

_VLM_REGISTRY: dict[VLMService, Callable[[], BaseVLM]] = {}


def _register_vlm_factories() -> None:
    global _VLM_REGISTRY
    if _VLM_REGISTRY:
        return

    _VLM_REGISTRY = {
        VLMService.openai: lambda: __import__("vision_endpoint.vlm", fromlist=["OpenAIVLM"]).OpenAIVLM(),
        VLMService.anthropic: lambda: __import__("vision_endpoint.vlm", fromlist=["AnthropicVLM"]).AnthropicVLM(),
        VLMService.azure_openai: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["AzureOpenAIVLM"]
        ).AzureOpenAIVLM(),
        VLMService.mistralai: lambda: __import__("vision_endpoint.vlm", fromlist=["MistralAIVLM"]).MistralAIVLM(),
        VLMService.nim: lambda: __import__("vision_endpoint.vlm", fromlist=["NimVLM"]).NimVLM(),
        VLMService.google: lambda: __import__("vision_endpoint.vlm", fromlist=["GoogleVLM"]).GoogleVLM(),
        VLMService.qwen: lambda: __import__("vision_endpoint.vlm", fromlist=["QwenVLM"]).QwenVLM(),
        VLMService.qwen_alibaba: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["QwenAlibabaVLM"]
        ).QwenAlibabaVLM(),
        VLMService.inference_hub: lambda: __import__(
            "vision_endpoint.vlm", fromlist=["InferenceHubVLM"]
        ).InferenceHubVLM(),
    }


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
    """
    Validation class that uses a VLM service to validate whether an input query
    (text or image) matches a set of reference images of a 3D asset.
    """

    def __init__(
        self,
        config: Optional[ValidationConfig] = None,
    ):
        self._config = config or ValidationConfig()
        self._vlm: BaseVLM = self._create_vlm(self._config.vlm_service)
        self._validation_fields = ValidationFields(self._config)

    def _create_vlm(self, vlm_service: VLMService) -> BaseVLM:
        _register_vlm_factories()

        if vlm_service not in _VLM_REGISTRY:
            supported = ", ".join(s.value for s in _VLM_REGISTRY.keys())
            raise ValueError(f"Unsupported VLM service: {vlm_service}. Supported: {supported}")

        return _VLM_REGISTRY[vlm_service]()

    @property
    def config(self) -> ValidationConfig:
        return self._config

    @property
    def vlm_service(self) -> VLMService:
        return self._config.vlm_service

    @property
    def vlm(self) -> BaseVLM:
        return self._vlm

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

    @staticmethod
    def _is_base64(s: str) -> bool:
        """Check if a string is likely a base64-encoded image."""
        if not isinstance(s, str):
            return False
        # Base64 strings are typically long and contain only valid base64 characters
        # Also check for common base64 image prefixes
        if len(s) > 100:
            # Check if it starts with data URL prefix
            if s.startswith("data:image"):
                return True
            # Check if it looks like raw base64 (starts with common PNG/JPEG base64 prefixes)
            if s.startswith(("iVBOR", "/9j/", "R0lGO")):  # PNG, JPEG, GIF magic bytes in base64
                return True
            # Try to validate as base64
            try:
                # Check if string contains only valid base64 characters
                base64.b64decode(s[:100], validate=True)
                return True
            except Exception:
                return False
        return False

    @staticmethod
    def _base64_to_image(base64_string: str) -> Image.Image:
        """Convert a base64 string to PIL Image."""
        # Handle data URL format
        if base64_string.startswith("data:image"):
            # Extract base64 part after the comma
            base64_string = base64_string.split(",", 1)[1]
        image_data = base64.b64decode(base64_string)
        return Image.open(io.BytesIO(image_data))

    @staticmethod
    def _load_image(image_input: str | Image.Image) -> Image.Image:
        """Load an image from a file path, base64 string, or return the PIL Image directly."""
        if isinstance(image_input, Image.Image):
            return image_input
        if isinstance(image_input, str):
            # Check if it's a base64 string
            if Validation._is_base64(image_input):
                return Validation._base64_to_image(image_input)
            # Otherwise treat as file path
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

    def validate(
        self,
        query: str | Image.Image,
        reference_images: list[Image.Image | str],
        return_detailed: bool = False,
        asset_caption: Optional[str] = None,
    ) -> bool | BaseModel:
        """
        Validate if a query (text or image) matches reference images of a 3D asset.

        Args:
            query: Either a text description or an image (PIL Image or file path)
                   to validate against the reference images.
            reference_images: List of reference images (PIL Images or file paths)
                              showing different views of the same 3D asset.
            return_detailed: If True, returns full ValidationResult with confidence
                             and reasoning. If False, returns just the boolean match.
            asset_caption: Optional caption or description of the asset to provide
                          additional context to the VLM. This helps improve validation
                          accuracy by giving the model more information about what
                          the asset represents.

        Returns:
            bool or ValidationResult: Whether the query matches the reference images,
                                      optionally with detailed validation info.
        """
        if not reference_images:
            raise ValueError("At least one reference image must be provided")

        # Prepare reference images as base64
        base64_images = []
        for ref_img in reference_images:
            img = self._load_image(ref_img)
            base64_images.append(self._image_to_base64(img))

        # Prepare caption context
        caption_context = ""
        if asset_caption:
            if self._is_image_input(query):
                caption_context = USER_PROMPT_IMAGE_WITH_CAPTION.format(caption=asset_caption)
            else:
                caption_context = USER_PROMPT_TEXT_WITH_CAPTION.format(caption=asset_caption)

        # Determine query type and prepare prompt
        if self._is_image_input(query):
            # Image query - prepend query image to the list
            query_img = self._load_image(query)
            base64_images.insert(0, self._image_to_base64(query_img))
            user_prompt = USER_PROMPT_IMAGE.format(caption_context=caption_context)
        else:
            # Text query
            user_prompt = USER_PROMPT_TEXT.format(query=query, caption_context=caption_context)

        # Configure structured output for consistent JSON results
        self._vlm.with_structured_output(self.base_model)

        try:
            invoke_fn = self._vlm.invoke
            if self._config.max_tries > 0:
                invoke_fn = backoff.on_exception(
                    backoff.expo,
                    VLMException,
                    max_tries=self._config.max_tries,
                    logger=logger,
                )(invoke_fn)

            result = invoke_fn(
                prompt=user_prompt,
                system_prompt=self.system_prompt,
                base64_images=base64_images,
            )

            # Parse the result
            if isinstance(result, BaseModel):
                validation_result = result
            else:
                # Handle case where result is a message object
                validation_result = self.base_model.model_validate_json(result.content)

            logger.info(
                f"Validation complete: is_match={validation_result.is_match}, "
                f"confidence={validation_result.confidence:.2f}"
            )

            if return_detailed:
                return validation_result
            return validation_result.is_match

        except VLMException:
            raise
        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            raise

    async def avalidate(
        self,
        query: str | Image.Image,
        reference_images: list[Image.Image | str],
        return_detailed: bool = False,
        asset_caption: Optional[str] = None,
    ) -> bool | BaseModel:
        """
        Async version of validate.

        Args:
            query: Either a text description or an image (PIL Image or file path)
                   to validate against the reference images.
            reference_images: List of reference images (PIL Images or file paths)
                              showing different views of the same 3D asset.
            return_detailed: If True, returns full ValidationResult with confidence
                             and reasoning. If False, returns just the boolean match.
            asset_caption: Optional caption or description of the asset to provide
                          additional context to the VLM. This helps improve validation
                          accuracy by giving the model more information about what
                          the asset represents.

        Returns:
            bool or ValidationResult: Whether the query matches the reference images,
                                      optionally with detailed validation info.
        """
        if not reference_images:
            raise ValueError("At least one reference image must be provided")

        # Prepare reference images as base64
        base64_images = []
        for ref_img in reference_images:
            img = self._load_image(ref_img)
            base64_images.append(self._image_to_base64(img))

        # Prepare caption context
        caption_context = ""
        if asset_caption:
            if self._is_image_input(query):
                caption_context = USER_PROMPT_IMAGE_WITH_CAPTION.format(caption=asset_caption)
            else:
                caption_context = USER_PROMPT_TEXT_WITH_CAPTION.format(caption=asset_caption)

        # Determine query type and prepare prompt
        if self._is_image_input(query):
            # Image query - prepend query image to the list
            query_img = self._load_image(query)
            base64_images.insert(0, self._image_to_base64(query_img))
            user_prompt = USER_PROMPT_IMAGE.format(caption_context=caption_context)
        else:
            # Text query
            user_prompt = USER_PROMPT_TEXT.format(query=query, caption_context=caption_context)

        # Configure structured output for consistent JSON results
        self._vlm.with_structured_output(self.base_model)

        try:
            ainvoke_fn = self._vlm.ainvoke
            if self._config.max_tries > 0:
                ainvoke_fn = backoff.on_exception(
                    backoff.expo,
                    VLMException,
                    max_tries=self._config.max_tries,
                    logger=logger,
                )(ainvoke_fn)

            result = await ainvoke_fn(
                prompt=user_prompt,
                system_prompt=self.system_prompt,
                base64_images=base64_images,
            )

            # Parse the result
            if isinstance(result, BaseModel):
                validation_result = result
            else:
                # Handle case where result is a message object
                validation_result = self.base_model.model_validate_json(result.content)

            logger.info(
                f"Validation complete: is_match={validation_result.is_match}, "
                f"confidence={validation_result.confidence:.2f}"
            )

            if return_detailed:
                return validation_result
            return validation_result.is_match

        except VLMException:
            raise
        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            raise
