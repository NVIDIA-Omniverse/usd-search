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
import asyncio
import base64
import hashlib
import io
import logging
import math
import re
import threading
from typing import Any, Mapping, Optional, Sequence

# third party modules
import backoff
import orjson
from PIL import Image, ImageOps
from pydantic import BaseModel, ValidationError

# local / proprietary modules
from ..client import LLMClient, LLMConnectionConfig, _safe_validation_errors
from ..exceptions import (
    LLMBadRequestException,
    LLMException,
    LLMLengthException,
    ParsingException,
)
from .validation_fields import ValidationConfig, ValidationFields

logger = logging.getLogger(__name__)


def _is_permanent_llm_error(exc: Exception) -> bool:
    """Errors that are deterministic for a given config — retrying cannot help.

    A malformed/unsupported request (e.g. the model does not support ``logprobs``)
    or hitting the token limit will fail identically on every retry, so backoff
    should give up immediately instead of burning the retry budget.
    """
    return isinstance(exc, (LLMBadRequestException, LLMLengthException))


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


# The log-prob method's only prompt: this question is the whole user text, and no
# system prompt is sent unless logprob_domain_context opts the configured domain
# context in (docs/vlm-validation.md, "Log-prob prompt"). The generative method
# keeps its own long prompt (validation_prompt.txt).
LOGPROB_JUDGE_PROMPT_HEAD = 'You are a visual relevance judge for a 3D-asset search. Query: "{query}". '
LOGPROB_JUDGE_QUESTION = "Does the rendered asset match the query? Answer with exactly one word: Yes or No."
LOGPROB_JUDGE_PROMPT = LOGPROB_JUDGE_PROMPT_HEAD + LOGPROB_JUDGE_QUESTION
# Asset facts (logprob_asset_facts) sit between the query and the question of a TEXT query's judge prompt — the
# wording SimReady Central's validator was evaluated with (2026-10-07: nDCG@10 0.78 -> 0.92 on 67 labelled queries).
# Per fact: its prompt line, and whether a long value keeps its tail (a path's file names the asset); the length
# caps are config (logprob_asset_path_max_chars, logprob_asset_caption_max_chars).
ASSET_FACT_PROMPTS = {
    "path": ('The candidate asset\'s file is "{}". ', True),
    "vlm_metadata_caption": ('Catalog description: "{}". ', False),
}


def _fact_text(value: Optional[str], limit: int, keep_tail: bool = False) -> str:
    """One fact as prompt text: whitespace collapsed, double quotes made single, at most ``limit`` characters."""
    text = " ".join(str(value or "").split()).replace('"', "'")
    if len(text) > limit:
        text = text[-limit:] if keep_tail else text[:limit]
    return text


def _below_root(path: str, roots: Sequence[re.Pattern]) -> str:
    """The path after the first content root that matches (logprob_asset_path_roots), else the whole path."""
    for root in roots:
        m = root.search(path)
        if m:
            return path[m.end() :].lstrip("/")
    return path.lstrip("/")


def render_asset_facts(
    names: Optional[Sequence[str]],
    values: Mapping[str, Optional[str]],
    path_roots: Sequence[re.Pattern],
    max_chars: Mapping[str, int],
) -> str:
    """The prompt text of each listed fact that ``values`` carries, in prompt order; "" for none."""
    text = ""
    for name in names or ():
        value = str(values.get(name) or "").strip()
        if name == "path":
            value = _below_root(value, path_roots)
        template, keep_tail = ASSET_FACT_PROMPTS[name]
        fact = _fact_text(value, max_chars[name], keep_tail)
        if fact:
            text += template.format(fact)
    return text


# Image-query form of the judge question: the query image is sent first.
LOGPROB_JUDGE_PROMPT_IMAGE_QUERY = (
    "You are a visual relevance judge for a 3D-asset search. The first image is the query image{caption_clause}; "
    "the remaining images are rendered views of one asset. Does the rendered asset match the query? "
    "Answer with exactly one word: Yes or No."
)
# On by default (logprob_image_text_query; false keeps the caption clause above): an image query
# WITH a text query and one asset view (the default view budget) asks with the text and the query
# image as the query, the other image the candidate. With the caption clause, the model judged the
# query image itself against the text and passed unrelated assets (docs/vlm-validation.md,
# "Log-prob prompt"). Several views keep the caption clause.
LOGPROB_JUDGE_PROMPT_IMAGE_TEXT_QUERY = (
    'You are a visual relevance judge for a 3D-asset search. Query: "{query}", together with the first image, '
    "which shows what the user is looking for. The other image shows a candidate asset. Does the candidate "
    "asset match the query? Answer with exactly one word: Yes or No."
)


# Distinct query images whose encoding is kept (see Validation._encode_query_image).
QUERY_IMAGE_MEMO_SIZE = 4


class _EncodedQueryImage:
    """One query image's encoding: set once by the thread that computes it, read by every verdict that asks."""

    __slots__ = ("done", "value")

    def __init__(self) -> None:
        self.done = threading.Event()
        self.value: Optional[str] = None


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
            extra_body=self._config.extra_body,
        )
        self._validation_fields = ValidationFields(self._config)
        # Encoded query images by input, most recent last (_encode_query_image); the lock guards the dict only.
        self._query_images: dict[str, _EncodedQueryImage] = {}
        self._query_images_lock = threading.Lock()
        # Lowercased token sets for the log-prob Yes/No scan (case-insensitive match).
        self._logprob_yes = {t.lower() for t in self._config.logprob_yes_tokens}
        self._logprob_no = {t.lower() for t in self._config.logprob_no_tokens}
        self._asset_path_roots = [re.compile(p) for p in self._config.logprob_asset_path_roots or []]
        self._asset_fact_max_chars = {
            "path": self._config.logprob_asset_path_max_chars,
            "vlm_metadata_caption": self._config.logprob_asset_caption_max_chars,
        }

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
    def verdict_model(self) -> type[BaseModel]:
        """Verdict shape every method returns: the yaml schema with ``similarity_score`` as a float 0-100."""
        return self._validation_fields.verdict_model

    @property
    def system_prompt(self) -> str:
        return self._validation_fields.prompt

    def config_identity(self) -> dict[str, Any]:
        """Everything that can change a validation verdict, as a stable dict.

        This is the grounding material for a persistent verdict cache key: any
        change to the model, its sampling params, the connection endpoint, the
        system/user prompts, or the output schema must change this dict so old
        verdicts are naturally invalidated. The ``api_key`` is deliberately
        excluded — it is a credential, not part of the verdict's identity.

        Note the rendered ``system_prompt`` already bakes in the domain context
        and the schema-derived field types/definitions; the raw output-schema
        fields are included as well so field constraints (e.g. numeric bounds)
        that never reach the prompt still participate in the identity.
        """
        identity: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
            "reasoning_effort": self._config.reasoning_effort,
            "max_tries": self._config.max_tries,
            "base_url": self._client.base_url,
            "validation_method": self._config.method,
            "system_prompt": self.system_prompt,
            "user_prompt_templates": [
                USER_PROMPT_TEXT,
                USER_PROMPT_IMAGE,
                USER_PROMPT_TEXT_WITH_CAPTION,
                USER_PROMPT_IMAGE_WITH_CAPTION,
            ],
            "output_schema": self._validation_fields.validation_fields,
        }
        # The model judges the pixels it is sent, so a resize changes verdicts. Recorded only
        # when on, so verdicts cached before the knob existed keep their fingerprint.
        if self._config.image_max_px > 0:
            identity["image_max_px"] = self._config.image_max_px
        # The log-prob method ignores the structured system_prompt/output_schema and
        # instead reads P(Yes)/P(No) from the one-word judge call, so its
        # verdict-changing inputs are the judge prompts + token/threshold config. Fold
        # them into the identity so a log-prob verdict never collides with a generative
        # one and any tuning knob invalidates cached verdicts. The judge prompts are
        # always recorded: verdicts cached under the earlier log-prob prompt (the
        # generative system prompt plus a one-word answer suffix) are never reused.
        if self._config.method == "logprob":
            identity["logprob"] = {
                "judge_prompts": [LOGPROB_JUDGE_PROMPT, LOGPROB_JUDGE_PROMPT_IMAGE_QUERY],
                "yes_tokens": sorted(t.lower() for t in self._config.logprob_yes_tokens),
                "no_tokens": sorted(t.lower() for t in self._config.logprob_no_tokens),
                "cover_min": self._config.logprob_cover_min,
                "top_logprobs": self._config.logprob_top_logprobs,
                "max_tokens": self._config.logprob_max_tokens,
                "abstain_as_no": self._config.logprob_abstain_as_no,
            }
            if self._config.logprob_asset_facts:
                identity["logprob"]["asset_facts"] = {
                    "facts": self._config.logprob_asset_facts,
                    "templates": [ASSET_FACT_PROMPTS[name][0] for name in self._config.logprob_asset_facts],
                }
            # The opt-in domain-context system prompt is recorded only when sent.
            domain_system_prompt = self._logprob_system_prompt()
            if domain_system_prompt is not None:
                identity["logprob"]["system_prompt"] = domain_system_prompt
            # The image + text question is recorded only when on: switched off, the identity (and the verdicts
            # cached under it) is the one from before the question existed.
            if self._config.logprob_image_text_query:
                identity["logprob"]["image_text_query_prompt"] = LOGPROB_JUDGE_PROMPT_IMAGE_TEXT_QUERY
        return identity

    def config_fingerprint(self) -> str:
        """Stable sha256 hex digest of :meth:`config_identity` — the config
        component of a validation cache key. Deterministic across processes and
        replicas for a fixed configuration (no host/random/pointer input)."""
        # orjson emits compact, deterministic bytes; OPT_SORT_KEYS makes the
        # digest independent of dict ordering. (bytes feed sha256 directly.)
        blob = orjson.dumps(self.config_identity(), option=orjson.OPT_SORT_KEYS)
        return hashlib.sha256(blob).hexdigest()

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
        """Load an image from a file path, base64 string, or return the PIL Image directly.

        Honors the EXIF orientation tag: the loaded image is re-encoded to PNG
        before it reaches the VLM (``_image_to_base64``), which strips EXIF —
        without the transpose a rotated query photo would be judged sideways
        (mirroring the embedding-side fix in this same flow). Pipeline-rendered
        thumbnails carry no orientation tag, so they pass through unchanged.
        """
        if isinstance(image_input, Image.Image):
            image = image_input
        elif isinstance(image_input, str):
            if self._is_base64(image_input):
                image = self._base64_to_image(image_input)
            else:
                image = Image.open(image_input)
        else:
            raise ValueError(f"Unsupported image input type: {type(image_input)}")
        return ImageOps.exif_transpose(image) or image

    def _fit(self, image: Image.Image) -> Image.Image:
        """Shrink ``image`` so its longest edge is at most ``config.image_max_px`` (in place unless its mode changes).

        No-op when the knob is 0 or the image already fits (never enlarged). The mode is
        changed only where the resize or the PNG re-encode needs it: palette and 1-bit
        images would otherwise resample with NEAREST, and CMYK/YCbCr cannot be saved as
        PNG. Everything else keeps its mode, so an alpha channel survives (flattening it
        would turn transparent regions into their stored colour and change the verdict).
        """
        max_px = self._config.image_max_px
        if max_px <= 0 or max(image.size) <= max_px:
            return image
        if image.mode in ("P", "PA"):
            image = image.convert("RGBA")
        elif image.mode == "1":
            image = image.convert("L")
        elif image.mode in ("CMYK", "YCbCr"):
            image = image.convert("RGB")
        image.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        return image

    def _encode_image(self, image_input: str | Image.Image) -> str:
        """Load, fit to ``image_max_px`` and base64-PNG-encode one image (query or reference)."""
        image = self._load_image(image_input)
        if image is image_input:
            # exif_transpose returns a copy on current Pillow; never resize a caller's image in place.
            image = image.copy()
        return self._image_to_base64(self._fit(image))

    def _encode_query_image(self, query: str | Image.Image) -> str:
        """:meth:`_encode_image` for a query image, computed once per distinct input.

        Every asset of a page is judged against the same query image, and encoding it is the costly
        part of preparing a verdict (~40-55 ms of CPU for a 1920-px upload: decode, fit, PNG encode).
        Concurrent callers wait for the first one's result. A failed encode is not kept: the waiters
        and the next call encode it themselves. A PIL image is encoded every time (it may change).
        """
        if not isinstance(query, str):
            return self._encode_image(query)
        with self._query_images_lock:
            entry = self._query_images.pop(query, None)
            computing = entry is None
            if computing:
                entry = _EncodedQueryImage()
            self._query_images[query] = entry
            while len(self._query_images) > QUERY_IMAGE_MEMO_SIZE:
                del self._query_images[next(iter(self._query_images))]
        if computing:
            try:
                entry.value = self._encode_image(query)
            except BaseException:
                with self._query_images_lock:
                    if self._query_images.get(query) is entry:
                        del self._query_images[query]
                raise
            finally:
                entry.done.set()
            return entry.value
        entry.done.wait()
        return entry.value if entry.value is not None else self._encode_image(query)

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

    def _encode_reference_images(self, reference_images) -> list[str]:
        """Load + base64-PNG-encode the asset views (the query image, if any, is added by the caller)."""
        if not reference_images:
            raise ValueError("At least one reference image must be provided")
        return [self._encode_image(ref_img) for ref_img in reference_images]

    def _build_images_and_prompt(self, query, reference_images, asset_caption):
        """Build the base64 image list + strict-match user prompt of the generative method.

        Does NOT touch structured output (:meth:`_prepare` / :meth:`avalidate` add that), so
        it is safe to run in a worker thread.
        """
        base64_images = self._encode_reference_images(reference_images)

        caption_context = ""
        if asset_caption:
            if self._is_image_input(query):
                caption_context = USER_PROMPT_IMAGE_WITH_CAPTION.format(caption=asset_caption)
            else:
                caption_context = USER_PROMPT_TEXT_WITH_CAPTION.format(caption=asset_caption)

        if self._is_image_input(query):
            base64_images.insert(0, self._encode_query_image(query))
            user_prompt = USER_PROMPT_IMAGE.format(caption_context=caption_context)
        else:
            user_prompt = USER_PROMPT_TEXT.format(query=query, caption_context=caption_context)

        return base64_images, user_prompt

    def _prepare(self, query, reference_images, asset_caption):
        """Generative prep: shared image/prompt build + constrain output to the schema."""
        base64_images, user_prompt = self._build_images_and_prompt(query, reference_images, asset_caption)
        self._client.with_structured_output(self.base_model)
        return base64_images, user_prompt

    def _logprob_system_prompt(self) -> Optional[str]:
        """System prompt for the logprob judge: the configured domain context alone, or ``None``.

        ``None`` unless ``logprob_domain_context`` opts in and the context is non-blank;
        the judge otherwise sends no system prompt."""
        if not self._config.logprob_domain_context:
            return None
        context = self._validation_fields.domain_context.strip()
        return context or None

    def _finalize(self, result, return_detailed):
        # The generated integer similarity_score becomes the verdict's float, as is. The
        # yaml puts no bound on it; the verdict bounds it to 0-100, and a value outside
        # is a per-hit parse failure (fail-open) like any other off-schema output.
        try:
            generated = result if isinstance(result, BaseModel) else self.base_model.model_validate_json(result.content)
            validation_result = self.verdict_model(**generated.model_dump())
        except ValidationError as e:
            safe_errors = _safe_validation_errors(e)
            summary = "; ".join(f"{location}: {error_type}" for location, error_type in safe_errors)
            raise ParsingException(
                f"Generated verdict failed schema validation: {summary}", validation_errors=safe_errors
            ) from e
        logger.info(
            f"Validation complete: is_match={validation_result.is_match}, "
            f"confidence={validation_result.confidence:.2f}"
        )
        if return_detailed:
            return validation_result
        return validation_result.is_match

    def asset_facts_text(self, asset_facts: Mapping[str, Optional[str]]) -> str:
        """The facts a TEXT query's logprob judge prompt carries for these values, or "" (none listed or given)."""
        if self._config.method != "logprob":
            return ""
        return render_asset_facts(
            self._config.logprob_asset_facts, asset_facts, self._asset_path_roots, self._asset_fact_max_chars
        )

    def _prepare_logprob(self, query, reference_images, asset_caption, asset_facts=None):
        """Images + user text for the logprob judge: the short judge question alone (an image
        query is sent first and, with a text query alongside it, named in the question). A text
        query carries the listed asset facts before the question (logprob_asset_facts)."""
        base64_images = self._encode_reference_images(reference_images)
        if self._is_image_input(query):
            base64_images.insert(0, self._encode_query_image(query))
            caption_clause = f' and the text query is "{asset_caption}"' if asset_caption else ""
            # == 2, not >= 2: the query image plus ONE asset view, the default view budget
            # (validation.max_images_per_validation: 1). The text and the query image form the query and
            # the view is the candidate; the question names a single candidate image ("The other image
            # shows a candidate asset"), and one view is the only case measured, as the engines measured
            # accept at most two images per prompt. Several views keep the caption clause until a plural
            # wording is measured.
            if asset_caption and len(base64_images) == 2 and self._config.logprob_image_text_query:
                return base64_images, LOGPROB_JUDGE_PROMPT_IMAGE_TEXT_QUERY.format(query=asset_caption)
            return base64_images, LOGPROB_JUDGE_PROMPT_IMAGE_QUERY.format(caption_clause=caption_clause)
        facts = self.asset_facts_text(asset_facts or {})
        if facts:
            return base64_images, LOGPROB_JUDGE_PROMPT_HEAD.format(query=query) + facts + LOGPROB_JUDGE_QUESTION
        return base64_images, LOGPROB_JUDGE_PROMPT.format(query=query)

    def _p_yes_from_logprobs(self, content) -> tuple[Optional[float], float]:
        """Read P(Yes) from the first token position carrying enough Yes/No mass.

        Scans positions (a model may emit a begin-of-answer token before the verdict)
        and, at the first one where combined Yes/No probability exceeds
        ``logprob_cover_min``, returns ``(p_yes, cover)`` with
        ``p_yes = P(Yes) / (P(Yes) + P(No))``. Returns ``(None, 0.0)`` when no position
        clears the floor — the model is genuinely uncertain (abstain)."""
        for pos in content or []:
            yes = no = 0.0
            for entry in pos.get("top_logprobs") or []:
                token = (entry.get("token") or "").strip().lower()
                try:
                    prob = math.exp(entry["logprob"])
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                if token in self._logprob_yes:
                    yes += prob
                elif token in self._logprob_no:
                    no += prob
            if yes + no > self._config.logprob_cover_min:
                return yes / (yes + no), yes + no
        return None, 0.0

    def _logprob_verdict(self, p_yes: Optional[float]) -> Optional[BaseModel]:
        """Map ``p_yes`` (or an abstain) onto the shared verdict schema.

        ``similarity_score = P(Yes) x 100``, unrounded.
        """
        if p_yes is None:
            if self._config.logprob_abstain_as_no:
                return self.verdict_model(
                    is_match=False,
                    confidence=0.0,
                    similarity_score=0.0,
                    reasoning="Abstained: Yes/No probability mass below cover_min; treated as no match.",
                )
            return None
        return self.verdict_model(
            is_match=p_yes > 0.5,
            confidence=round(p_yes, 4),
            similarity_score=p_yes * 100.0,
            reasoning=f"P(Yes)={p_yes:.4f} from first-token log-probs.",
        )

    async def _avalidate_logprob(
        self,
        query,
        reference_images,
        return_detailed: bool,
        asset_caption: Optional[str],
        asset_facts: Optional[Mapping[str, Optional[str]]] = None,
    ) -> bool | BaseModel | None:
        """Log-prob relevance judge: one forward pass, verdict read from P(Yes)/P(No)."""
        # Decode/resize/PNG-encode is CPU-bound (~20 ms per 1024-px image): keep it off the event loop.
        base64_images, user_prompt = await asyncio.to_thread(
            self._prepare_logprob, query, reference_images, asset_caption, asset_facts
        )

        ainvoke_fn = self._client.ainvoke_logprobs
        if self._config.max_tries > 0:
            ainvoke_fn = backoff.on_exception(
                backoff.expo,
                LLMException,
                max_tries=self._config.max_tries,
                giveup=_is_permanent_llm_error,
                logger=logger,
            )(ainvoke_fn)

        content = await ainvoke_fn(
            prompt=user_prompt,
            system_prompt=self._logprob_system_prompt(),
            base64_images=base64_images,
            top_logprobs=self._config.logprob_top_logprobs,
            max_tokens=self._config.logprob_max_tokens,
        )
        p_yes, _cover = self._p_yes_from_logprobs(content)
        verdict = self._logprob_verdict(p_yes)
        logger.info(
            "Log-prob validation complete: p_yes=%s -> %s",
            "abstain" if p_yes is None else f"{p_yes:.3f}",
            "no verdict" if verdict is None else f"is_match={verdict.is_match}",
        )
        if return_detailed:
            return verdict
        return None if verdict is None else verdict.is_match

    async def avalidate(
        self,
        query: str | Image.Image,
        reference_images: list[Image.Image | str],
        return_detailed: bool = False,
        asset_caption: Optional[str] = None,
        asset_facts: Optional[Mapping[str, Optional[str]]] = None,
    ) -> bool | BaseModel | None:
        """Validate if a query (text or image) matches reference images of a 3D asset.

        ``asset_facts`` are the asset's own facts by name (``path``, ``vlm_metadata_caption``): a TEXT
        query's logprob judge reads those ``logprob_asset_facts`` lists (else ignored).

        Returns ``None`` (no verdict) only in the log-prob method when it abstains
        and ``logprob_abstain_as_no`` is false; callers treat that as fail-open.
        Detailed results are :attr:`verdict_model` instances (the yaml schema with
        ``similarity_score`` as a float 0-100, the one relevance number).
        """
        if self._config.method == "logprob":
            return await self._avalidate_logprob(query, reference_images, return_detailed, asset_caption, asset_facts)

        # The image work of _prepare runs off the event loop; with_structured_output rebinds
        # the shared client's model, so it stays on the loop with every other client call.
        base64_images, user_prompt = await asyncio.to_thread(
            self._build_images_and_prompt, query, reference_images, asset_caption
        )
        self._client.with_structured_output(self.base_model)
        try:
            ainvoke_fn = self._client.ainvoke
            if self._config.max_tries > 0:
                ainvoke_fn = backoff.on_exception(
                    backoff.expo,
                    LLMException,
                    max_tries=self._config.max_tries,
                    giveup=_is_permanent_llm_error,
                    logger=logger,
                )(ainvoke_fn)

            result = await ainvoke_fn(prompt=user_prompt, system_prompt=self.system_prompt, base64_images=base64_images)
            return self._finalize(result, return_detailed)
        except LLMException:
            raise
        except Exception as e:
            logger.error(f"Validation failed: {e}", exc_info=True)
            raise
