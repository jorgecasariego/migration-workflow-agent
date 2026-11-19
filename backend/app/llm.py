"""Thin LLM abstraction.

The orchestrator depends on the `LLMClient` protocol, so tests can substitute a fake
client while the application always uses the real Anthropic implementation.
"""

from __future__ import annotations

import logging
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """A recoverable LLM failure (bad output, refusal, transient API error)."""


class LLMFatalError(Exception):
    """A non-recoverable failure (auth, bad request). Retrying will not help."""


class LLMClient(Protocol):
    def structured(self, *, system: str, prompt: str, schema: type[T]) -> T: ...


class AnthropicLLM:
    """Calls Claude with structured outputs and validates the result with Pydantic."""

    def __init__(self, settings: Settings):
        self.settings = settings
        # The SDK retries 429/5xx/connection errors itself (max_retries).
        self.client = anthropic.Anthropic(timeout=settings.llm_request_timeout_s, max_retries=2)

    def structured(self, *, system: str, prompt: str, schema: type[T]) -> T:
        try:
            response = self.client.beta.messages.parse(
                model=self.settings.anthropic_model,
                max_tokens=self.settings.llm_max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                output_config={"effort": self.settings.llm_effort},
                # If a safety classifier declines, let the API retry on a fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
            raise LLMFatalError(f"Anthropic API rejected the request: {e.message}") from e
        except anthropic.BadRequestError as e:
            raise LLMFatalError(f"Bad request to Anthropic API: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Rate limited by Anthropic API") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Could not reach the Anthropic API (connection error or timeout)") from e
        except ValidationError as e:
            raise LLMError(f"Model output failed schema validation: {e.error_count()} error(s)") from e
        except TypeError as e:
            # The SDK raises TypeError at request time when no credentials can be resolved.
            if "authentication" in str(e).lower():
                raise LLMFatalError("No Anthropic credentials configured: set ANTHROPIC_API_KEY") from e
            raise

        log.info("LLM call ok request_id=%s stop=%s", getattr(response, "_request_id", None), response.stop_reason)

        if response.stop_reason == "refusal":
            raise LLMError("The model declined this request")
        if response.stop_reason == "max_tokens":
            raise LLMError("Model output was truncated (max_tokens reached)")

        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("Model returned no parsable structured output")
        # Defensive re-validation: guarantees we hold exactly the expected schema type.
        try:
            return schema.model_validate(parsed.model_dump() if isinstance(parsed, BaseModel) else parsed)
        except ValidationError as e:
            raise LLMError(f"Model output failed schema validation: {e.error_count()} error(s)") from e
