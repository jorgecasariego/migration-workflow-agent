"""Tests AnthropicLLM against a mocked HTTP transport (no network, no API key)."""

import json

import anthropic
import httpx2
import pytest

from app.config import Settings
from app.llm import AnthropicLLM, LLMError, LLMFatalError
from app.models import StepOutput


def _llm(status=200, stop="end_turn", text=None):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["headers"] = dict(req.headers)
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}})
        payload = text if text is not None else json.dumps({"code": "x = 1\n", "notes": "n"})
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [{"type": "text", "text": payload}],
                "stop_reason": stop,
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    llm = AnthropicLLM(Settings())
    llm.client = anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    return llm, seen


def test_request_uses_structured_output_schema():
    llm, seen = _llm()
    out = llm.structured(system="sys", prompt="p", schema=StepOutput)
    assert out == StepOutput(code="x = 1\n", notes="n")
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["required"] == ["code", "notes"]


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_bad_stop_reasons_are_recoverable_errors(stop):
    llm, _ = _llm(stop=stop)
    with pytest.raises(LLMError):
        llm.structured(system="s", prompt="p", schema=StepOutput)


def test_invalid_json_is_recoverable_error():
    llm, _ = _llm(text='{"code": 1}')
    with pytest.raises(LLMError):
        llm.structured(system="s", prompt="p", schema=StepOutput)


def test_auth_error_is_fatal():
    llm, _ = _llm(status=401)
    with pytest.raises(LLMFatalError):
        llm.structured(system="s", prompt="p", schema=StepOutput)


def test_server_error_is_recoverable():
    llm, _ = _llm(status=500)
    with pytest.raises(LLMError):
        llm.structured(system="s", prompt="p", schema=StepOutput)


def test_missing_credentials_is_fatal_with_clear_message(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", "/nonexistent")  # no `ant auth login` profile either
    llm = AnthropicLLM(Settings())
    llm.client = anthropic.Anthropic(
        max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(lambda r: None))
    )
    with pytest.raises(LLMFatalError, match="ANTHROPIC_API_KEY"):
        llm.structured(system="s", prompt="p", schema=StepOutput)
