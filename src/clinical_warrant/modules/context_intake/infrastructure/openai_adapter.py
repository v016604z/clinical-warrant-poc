"""Reusable OpenAI Responses API adapter for structured JSON output."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Mapping


DEFAULT_MODEL = "gpt-6-luna"


class OpenAIAdapterError(RuntimeError):
    """An OpenAI request failed or returned no text output."""


@dataclass(frozen=True)
class OpenAIResponseMetadata:
    """Safe per-call metadata that excludes prompts, outputs, and credentials."""

    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: float
    error_type: str | None = None


class OpenAIResponsesAdapter:
    """Call the Responses API with strict JSON Schema output."""

    def __init__(
        self,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_output_tokens: int = 512,
        client: Any | None = None,
        on_response: Callable[[OpenAIResponseMetadata], None] | None = None,
    ) -> None:
        if client is None:
            from dotenv import load_dotenv

            load_dotenv(override=False)

        configured_timeout = self._configured_timeout(timeout)
        configured_retries = self._configured_retries(max_retries)
        if (
            isinstance(configured_timeout, bool)
            or not isinstance(configured_timeout, (int, float))
            or not math.isfinite(configured_timeout)
            or configured_timeout <= 0
        ):
            raise ValueError("timeout must be a finite positive number")
        if (
            isinstance(configured_retries, bool)
            or not isinstance(configured_retries, int)
            or configured_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if (
            isinstance(max_output_tokens, bool)
            or not isinstance(max_output_tokens, int)
            or max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be a positive integer")

        configured_model = model or os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
        self.model = configured_model
        self.timeout = float(configured_timeout)
        self.max_retries = configured_retries
        self.max_output_tokens = max_output_tokens
        self._on_response = on_response
        self._api_error_type: type[BaseException] | tuple[type[BaseException], ...] = ()

        if client is None:
            from openai import APIError, OpenAI

            self._api_error_type = APIError
            if not os.getenv("OPENAI_API_KEY", "").strip():
                raise OpenAIAdapterError(
                    "OPENAI_API_KEY is not set. Set it in .env or the process environment."
                )
            client = OpenAI(timeout=self.timeout, max_retries=self.max_retries)
        self._client = client

    def create_structured_response(
        self,
        *,
        input: str,
        schema_name: str,
        schema: Mapping[str, object],
        instructions: str | None = None,
    ) -> str:
        """Return the model's JSON text for the supplied strict JSON Schema."""
        request: dict[str, object] = {
            "model": self.model,
            "input": input,
            "store": False,
            "max_output_tokens": self.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": dict(schema),
                    "strict": True,
                }
            },
        }
        if instructions is not None:
            request["instructions"] = instructions

        started = perf_counter()
        try:
            response = self._client.responses.create(**request)
        except Exception as error:
            if not self._is_api_error(error):
                raise
            self._report(
                OpenAIResponseMetadata(
                    model=self.model,
                    input_tokens=None,
                    output_tokens=None,
                    total_tokens=None,
                    latency_ms=(perf_counter() - started) * 1000,
                    error_type=type(error).__name__,
                )
            )
            raise OpenAIAdapterError(
                f"OpenAI Responses API request failed ({type(error).__name__})."
            ) from error

        usage = getattr(response, "usage", None)
        metadata = OpenAIResponseMetadata(
            model=self.model,
            input_tokens=self._usage_value(usage, "input_tokens"),
            output_tokens=self._usage_value(usage, "output_tokens"),
            total_tokens=self._usage_value(usage, "total_tokens"),
            latency_ms=(perf_counter() - started) * 1000,
        )
        self._report(metadata)
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            raise OpenAIAdapterError("OpenAI Responses API returned no text output.")
        return output_text

    def _is_api_error(self, error: Exception) -> bool:
        if isinstance(error, (TimeoutError, ConnectionError)):
            return True
        if self._api_error_type and isinstance(error, self._api_error_type):
            return True
        return any(base.__name__ == "APIError" for base in type(error).__mro__)

    @staticmethod
    def _usage_value(usage: Any, name: str) -> int | None:
        value = getattr(usage, name, None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    def _report(self, metadata: OpenAIResponseMetadata) -> None:
        if self._on_response is not None:
            self._on_response(metadata)

    @staticmethod
    def _configured_timeout(value: float | None) -> float | str:
        raw = value if value is not None else os.getenv("OPENAI_TIMEOUT_SECONDS", "30")
        if isinstance(raw, str):
            try:
                return float(raw)
            except ValueError as error:
                raise ValueError("OPENAI_TIMEOUT_SECONDS must be a finite positive number") from error
        return raw

    @staticmethod
    def _configured_retries(value: int | None) -> int | str:
        raw = value if value is not None else os.getenv("OPENAI_MAX_RETRIES", "2")
        if isinstance(raw, str):
            try:
                return int(raw)
            except ValueError as error:
                raise ValueError("OPENAI_MAX_RETRIES must be a non-negative integer") from error
        return raw
