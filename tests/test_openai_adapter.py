"""Offline adapter tests plus an explicitly enabled live API smoke test.

The live test is skipped unless RUN_OPENAI_API_SMOKE=1 is set. To run it in
PowerShell: set that variable, then run this file's test_openai_api_structured_output_smoke
test alone. The opt-in test makes a billable request and loads credentials from .env.
"""

import json
import os
import sys
from types import ModuleType

import pytest

from clinical_warrant.modules.context_intake.infrastructure.openai_adapter import (
    OpenAIAdapterError,
    OpenAIResponsesAdapter,
)


class FakeResponses:
    def __init__(self, output_text="{}"):
        self.output_text = output_text
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        usage = type("Usage", (), {
            "input_tokens": 7,
            "output_tokens": 3,
            "total_tokens": 10,
        })()
        return type("Response", (), {
            "output_text": self.output_text,
            "model": "test-model",
            "usage": usage,
        })()


class FakeClient:
    def __init__(self, output_text="{}"):
        self.responses = FakeResponses(output_text)


def test_adapter_wraps_api_error_without_exposing_request_data():
    class FailingResponses:
        def create(self, **_kwargs):
            raise TimeoutError("private request detail")

    client = type("Client", (), {"responses": FailingResponses()})()
    metadata = []
    adapter = OpenAIResponsesAdapter(client=client, on_response=metadata.append)

    with pytest.raises(OpenAIAdapterError, match="OpenAI Responses API request failed") as error:
        adapter.create_structured_response(
            input="private message", schema_name="test", schema={"type": "object"},
        )

    assert isinstance(error.value.__cause__, TimeoutError)
    assert "private request detail" not in str(error.value)
    assert metadata[0].error_type == "TimeoutError"
    assert metadata[0].latency_ms >= 0


def test_adapter_sends_strict_json_schema_and_returns_output_text(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    client = FakeClient('{"ok":true}')
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"], "additionalProperties": False}
    metadata = []
    adapter = OpenAIResponsesAdapter(client=client, on_response=metadata.append)

    result = adapter.create_structured_response(
        input="test input",
        schema_name="smoke_schema",
        schema=schema,
        instructions="Return the requested JSON.",
    )

    assert result == '{"ok":true}'
    assert client.responses.kwargs == {
        "model": "test-model",
        "input": "test input",
        "instructions": "Return the requested JSON.",
        "store": False,
        "max_output_tokens": 512,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "smoke_schema",
                "schema": schema,
                "strict": True,
            }
        },
    }
    assert metadata[0].model == "test-model"
    assert metadata[0].input_tokens == 7
    assert metadata[0].output_tokens == 3
    assert metadata[0].total_tokens == 10
    assert metadata[0].latency_ms >= 0
    assert metadata[0].error_type is None


def test_adapter_uses_explicit_model_instead_of_environment(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")
    client = FakeClient()

    OpenAIResponsesAdapter(model="explicit-model", client=client).create_structured_response(
        input="x", schema_name="test", schema={"type": "object"}
    )

    assert client.responses.kwargs["model"] == "explicit-model"


def _mock_sdk(monkeypatch):
    calls = {}
    dotenv = ModuleType("dotenv")
    dotenv.load_dotenv = lambda **_kwargs: None
    openai = ModuleType("openai")
    openai.APIError = type("APIError", (Exception,), {})

    def make_client(**kwargs):
        calls.update(kwargs)
        return FakeClient()

    openai.OpenAI = make_client
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)
    monkeypatch.setitem(sys.modules, "openai", openai)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    return calls


def test_adapter_uses_timeout_and_retry_defaults(monkeypatch):
    calls = _mock_sdk(monkeypatch)
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_MAX_RETRIES", raising=False)

    adapter = OpenAIResponsesAdapter()

    assert calls == {"timeout": 30.0, "max_retries": 2}
    assert adapter.timeout == 30.0
    assert adapter.max_retries == 2


def test_adapter_reads_timeout_and_retry_environment_and_honors_explicit_values(monkeypatch):
    calls = _mock_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "5")

    adapter = OpenAIResponsesAdapter()

    assert calls == {"timeout": 12.5, "max_retries": 5}
    assert adapter.timeout == 12.5
    assert adapter.max_retries == 5

    overridden = OpenAIResponsesAdapter(timeout=3, max_retries=1, client=FakeClient())
    assert overridden.timeout == 3.0
    assert overridden.max_retries == 1


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("OPENAI_TIMEOUT_SECONDS", "0", "timeout"),
        ("OPENAI_TIMEOUT_SECONDS", "nan", "timeout"),
        ("OPENAI_TIMEOUT_SECONDS", "not-a-number", "OPENAI_TIMEOUT_SECONDS"),
        ("OPENAI_MAX_RETRIES", "-1", "max_retries"),
        ("OPENAI_MAX_RETRIES", "1.5", "OPENAI_MAX_RETRIES"),
        ("OPENAI_MAX_RETRIES", "not-a-number", "OPENAI_MAX_RETRIES"),
    ],
)
def test_adapter_rejects_invalid_timeout_or_retry_environment(variable, value, message, monkeypatch):
    monkeypatch.setenv(variable, value)

    with pytest.raises(ValueError, match=message):
        OpenAIResponsesAdapter(client=FakeClient())


def test_missing_api_key_has_clear_error_without_starting_client(monkeypatch, tmp_path):
    calls = _mock_sdk(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    openai = sys.modules["openai"]
    openai.OpenAI = lambda **_kwargs: pytest.fail("client must not be constructed without a key")

    with pytest.raises(OpenAIAdapterError, match="OPENAI_API_KEY is not set"):
        OpenAIResponsesAdapter()
    assert calls == {}


@pytest.mark.skipif(
    os.environ.get("RUN_OPENAI_API_SMOKE") != "1",
    reason="set RUN_OPENAI_API_SMOKE=1 to make a billable OpenAI API request",
)
def test_openai_api_structured_output_smoke():
    from dotenv import load_dotenv

    load_dotenv(override=False)
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.fail("RUN_OPENAI_API_SMOKE=1 requires OPENAI_API_KEY in process environment or .env")

    metadata = []
    adapter = OpenAIResponsesAdapter(on_response=metadata.append)
    result = adapter.create_structured_response(
        input='Return the JSON object with "ok" set to true.',
        schema_name="openai_smoke_test",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        instructions="Return only the requested structured result.",
    )

    assert json.loads(result) == {"ok": True}
    assert len(metadata) == 1
    assert metadata[0].model == adapter.model
    assert isinstance(metadata[0].input_tokens, int) and metadata[0].input_tokens >= 0
    assert isinstance(metadata[0].output_tokens, int) and metadata[0].output_tokens >= 0
    assert isinstance(metadata[0].total_tokens, int) and metadata[0].total_tokens >= 0
    assert metadata[0].latency_ms >= 0
