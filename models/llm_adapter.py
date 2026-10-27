"""A small client for OpenAI-compatible chat APIs (Groq and others).

The transport (the function that really sends HTTP) can be replaced, so tests
use a fake one and never call the real API. Errors carry only a short code,
never the API key or the answer body.

Retries are an application rule, not the model's choice: only a timeout or a
temporary server status is retried, at most twice.
"""

import json
import os
import socket
import time
import urllib.error
import urllib.request

import config

# Used when the provider's model_env variable is not set.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
    # The bigger Flash models timed out or returned 503 when tested; flash-lite answered in ~1.5s.
    "gemini": "gemini-3.1-flash-lite",
    # A free model from a third family (NVIDIA Nemotron), so the tester does not share the developer's blind spots.
    "openrouter": "nvidia/nemotron-3-super-120b-a12b:free",
}

# Statuses that may pass if we wait (rate limit, server trouble). 400/401/403/404 never do.
RETRY_STATUSES = {429, 500, 502, 503, 504}
# Seconds to wait before retry 1 and retry 2.
RETRY_WAITS = (2, 6)
# A Retry-After header is followed, but never longer than this.
MAX_RETRY_AFTER = 20


class LLMError(Exception):
    """A model call failed. code is one of:
    missing_api_key, http_error, timeout, bad_response."""

    def __init__(self, code, status=None):
        self.code = code
        self.status = status
        super().__init__(f"{code} ({status})" if status else code)


def urllib_transport(url, headers, body, timeout):
    """Send one POST request. Returns (status, text, retry_after). Raises TimeoutError.

    retry_after is the raw Retry-After header of an error answer, or None.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8"), None
    except urllib.error.HTTPError as e:
        return e.code, "", e.headers.get("Retry-After")
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError() from None
        return 0, "", None


def real_sleep(seconds):
    time.sleep(seconds)


def retry_wait(retry, retry_after):
    """Seconds to wait before retry number `retry` (1 or 2)."""
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        # No header, or a date instead of seconds: use our own wait.
        return RETRY_WAITS[retry - 1]
    return min(max(seconds, 0), MAX_RETRY_AFTER)


class LLMClient:
    def __init__(self, provider, transport=None, timeout=config.HTTP_TIMEOUT, sleep=None, clock=None):
        self.provider = provider
        self.spec = config.PROVIDERS[provider]
        self.transport = transport or urllib_transport
        self.timeout = timeout
        # sleep and clock can be replaced, so tests never really wait.
        self.sleep = sleep or real_sleep
        self.clock = clock or time.monotonic
        self.min_interval = config.MIN_REQUEST_INTERVAL.get(provider, 0.0)
        self.last_request_end = None
        # The retries of the last chat() call: [{"attempt": 1, "status": 503}, ...]
        self.retries = []

    @property
    def model(self):
        return os.environ.get(self.spec["model_env"]) or DEFAULT_MODELS[self.provider]

    def chat(self, messages):
        """Send the messages and return the answer text."""
        self.retries = []
        key = os.environ.get(self.spec["key_env"])
        if not key:
            raise LLMError("missing_api_key")

        url = self.spec["base_url"] + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "devsecops-team/1.0",
        }
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }).encode("utf-8")

        text = self.send_with_retries(url, headers, body)
        try:
            content = json.loads(text)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("bad_response") from None
        if not isinstance(content, str):
            raise LLMError("bad_response")
        return content

    def send_with_retries(self, url, headers, body):
        """Send the request, retrying a timeout or a temporary status at most twice.
        Returns the answer text, or raises the LLMError of the last attempt."""
        for attempt in range(1, len(RETRY_WAITS) + 2):
            self.wait_for_gap()
            retry_after = None
            try:
                status, text, retry_after = self.transport(url, headers, body, self.timeout)
                error = None if status == 200 else LLMError("http_error", status)
            except TimeoutError:
                error = LLMError("timeout")
            self.last_request_end = self.clock()

            if error is None:
                return text
            can_retry = error.code == "timeout" or error.status in RETRY_STATUSES
            if not can_retry or attempt > len(RETRY_WAITS):
                raise error
            self.retries.append({"attempt": attempt, "status": error.status or error.code})
            self.sleep(retry_wait(attempt, retry_after))

    def wait_for_gap(self):
        """Keep at least min_interval seconds between two requests of this client."""
        if self.last_request_end is None or not self.min_interval:
            return
        waited = self.clock() - self.last_request_end
        if waited < self.min_interval:
            self.sleep(self.min_interval - waited)
