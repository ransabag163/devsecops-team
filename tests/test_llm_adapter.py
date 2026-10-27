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
        return self.status, self.text, None


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


# ---------- retries (an application rule) and the request gap ----------

class SequenceTransport:
    """Answers each call with the next item: (status, text, retry_after) or an exception."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, url, headers, body, timeout):
        self.calls += 1
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class FakeSleep:
    def __init__(self):
        self.waits = []

    def __call__(self, seconds):
        self.waits.append(seconds)


OK = (200, answer("hi"), None)


def test_retry_then_success(key):
    transport, sleep = SequenceTransport((503, "", None), OK), FakeSleep()
    client = LLMClient("groq", transport, sleep=sleep)

    assert client.chat([]) == "hi"
    assert transport.calls == 2
    assert sleep.waits == [2]
    assert client.retries == [{"attempt": 1, "status": 503}]


def test_timeout_and_429_are_retried_with_growing_waits(key):
    transport, sleep = SequenceTransport(TimeoutError(), (429, "", None), OK), FakeSleep()
    client = LLMClient("groq", transport, sleep=sleep)

    assert client.chat([]) == "hi"
    assert sleep.waits == [2, 6]
    assert client.retries == [{"attempt": 1, "status": "timeout"}, {"attempt": 2, "status": 429}]


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(key, status):
    transport, sleep = SequenceTransport((status, "", None), OK), FakeSleep()
    client = LLMClient("groq", transport, sleep=sleep)

    with pytest.raises(LLMError) as error:
        client.chat([])

    assert str(error.value) == f"http_error ({status})"
    assert transport.calls == 1
    assert sleep.waits == []
    assert client.retries == []


@pytest.mark.parametrize("failure, message", [
    ((503, "", None), "http_error (503)"),
    (TimeoutError(), "timeout"),
])
def test_gives_up_after_two_retries_with_the_same_error(key, failure, message):
    transport, sleep = SequenceTransport(failure, failure, failure, OK), FakeSleep()
    client = LLMClient("groq", transport, sleep=sleep)

    with pytest.raises(LLMError) as error:
        client.chat([])

    assert str(error.value) == message
    assert transport.calls == 3
    assert sleep.waits == [2, 6]
    assert [r["attempt"] for r in client.retries] == [1, 2]


@pytest.mark.parametrize("retry_after, wait", [
    ("10", 10.0),
    ("60", 20),                              # capped
    ("Wed, 21 Oct 2026 07:28:00 GMT", 2),    # a date, not seconds: our own wait
])
def test_retry_after_header(key, retry_after, wait):
    sleep = FakeSleep()
    client = LLMClient("groq", SequenceTransport((429, "", retry_after), OK), sleep=sleep)

    client.chat([])

    assert sleep.waits == [wait]


def test_gemini_keeps_a_gap_between_requests(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    now = [100.0]
    sleep = FakeSleep()
    client = LLMClient("gemini", SequenceTransport(OK, OK), sleep=sleep, clock=lambda: now[0])

    client.chat([])
    now[0] += 1.5
    client.chat([])

    assert sleep.waits == [2.5]  # 4 seconds gap, 1.5 already passed


def test_groq_has_no_gap(key):
    sleep = FakeSleep()
    client = LLMClient("groq", SequenceTransport(OK, OK), sleep=sleep)

    client.chat([])
    client.chat([])

    assert sleep.waits == []


def test_openrouter_url_and_default_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    transport = FakeTransport()

    LLMClient("openrouter", transport).chat([])

    call = transport.calls[0]
    assert call["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert call["body"]["model"].endswith(":free")
