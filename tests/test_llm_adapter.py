import json

import pytest

from models.llm_adapter import LLMClient, LLMError

FAKE_KEY = "fake-key-for-tests-123"


def answer(content):
    return json.dumps({"choices": [{"message": {"content": content}}]})


class FakeTransport:
    def __init__(self, status=200, text=answer("hi"), error=None):
        self.status, self.text, self.error = status, text, error
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(body)})
        if self.error:
            raise self.error
        return self.status, self.text


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.delenv("GROQ_MODEL", raising=False)


def test_chat_sends_an_openai_style_request(key):
    transport = FakeTransport()

    reply = LLMClient("groq", transport).chat([{"role": "user", "content": "hello"}])

    call = transport.calls[0]
    assert reply == "hi"
    assert call["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert call["body"]["temperature"] == 0
    assert call["body"]["messages"] == [{"role": "user", "content": "hello"}]


def test_gemini_url_and_key_are_joined_correctly(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    transport = FakeTransport()

    LLMClient("gemini", transport).chat([])

    call = transport.calls[0]
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    assert call["body"]["model"] == "gemini-3.1-flash-lite"


def test_every_agent_has_a_default_model():
    import config
    from models.llm_adapter import DEFAULT_MODELS

    for provider in config.AGENT_PROVIDER.values():
        assert provider in DEFAULT_MODELS


def test_model_env_overrides_the_default(key, monkeypatch):
    monkeypatch.setenv("GROQ_MODEL", "some-other-model")
    transport = FakeTransport()

    LLMClient("groq", transport).chat([])

    assert transport.calls[0]["body"]["model"] == "some-other-model"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    transport = FakeTransport()

    with pytest.raises(LLMError) as error:
        LLMClient("groq", transport).chat([])

    assert error.value.code == "missing_api_key"
    assert transport.calls == []


@pytest.mark.parametrize("transport, code", [
    (FakeTransport(status=401, text="bad key " + FAKE_KEY), "http_error"),
    (FakeTransport(error=TimeoutError()), "timeout"),
    (FakeTransport(text="not json"), "bad_response"),
    (FakeTransport(text=json.dumps({"choices": []})), "bad_response"),
    (FakeTransport(text=answer(None)), "bad_response"),
])
def test_errors_have_a_clear_code_and_no_key(key, transport, code):
    with pytest.raises(LLMError) as error:
        LLMClient("groq", transport).chat([])

    assert error.value.code == code
    assert FAKE_KEY not in str(error.value)


def test_http_error_keeps_only_the_status(key):
    with pytest.raises(LLMError) as error:
        LLMClient("groq", FakeTransport(status=429, text="slow down")).chat([])

    assert str(error.value) == "http_error (429)"
