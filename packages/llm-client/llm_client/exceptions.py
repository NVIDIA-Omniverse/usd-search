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

"""Exceptions raised by the LLM client and its helper libraries."""


class LLMException(RuntimeError):
    """Raised when the underlying LLM/VLM call fails."""


class LLMLengthException(LLMException):
    """The model hit its completion token limit (finish_reason=length).

    Deterministic for a given prompt + max_tokens — retrying cannot succeed;
    raise the role's max_tokens or switch to a different model instead.
    """


class LLMBadRequestException(LLMException):
    """The provider rejected the request as malformed/unsupported (HTTP 4xx).

    Deterministic and permanent for a given config — retrying cannot succeed
    (e.g. the model does not support ``logprobs``, or an unsupported parameter
    was sent). Callers should surface a configuration error, not a transient
    "service unavailable". ``status_code`` carries the provider's HTTP status
    when known.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ParsingException(RuntimeError):
    """Raised when the model output cannot be parsed into the expected schema."""

    def __init__(
        self,
        message: str,
        *,
        validation_errors: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        # Safe, structured (field location, error type) pairs for a repair prompt.
        # The human-readable exception message must never be assumed prompt-safe.
        self.validation_errors = validation_errors
