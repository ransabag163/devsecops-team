"""A small client for OpenAI-compatible chat APIs (Groq and others).

The transport (the function that really sends HTTP) can be replaced, so tests
use a fake one and never call the real API. Errors carry only a short code,
never the API key or the answer body.
"""

import json
import os
import socket
import urllib.error
import urllib.request

import config

# Used when the provider's model_env variable is not set.
DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-120b",
}


class LLMError(Exception):
    """A model call failed. code is one of:
    missing_api_key, http_error, timeout, bad_response."""

    def __init__(self, code, status=None):
        self.code = code
        self.status = status
        super().__init__(f"{code} ({status})" if status else code)


def urllib_transport(url, headers, body, timeout):
    """Send one POST request. Returns (status, text). Raises TimeoutError."""
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except urllib.error.URLError as e:
        if isinstance(e.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError() from None
        return 0, ""


class LLMClient:
    def __init__(self, provider, transport=None, timeout=config.HTTP_TIMEOUT):
        self.provider = provider
        self.spec = config.PROVIDERS[provider]
        self.transport = transport or urllib_transport
        self.timeout = timeout

    @property
    def model(self):
        return os.environ.get(self.spec["model_env"]) or DEFAULT_MODELS[self.provider]

    def chat(self, messages):
        """Send the messages and return the answer text."""
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

        try:
            status, text = self.transport(url, headers, body, self.timeout)
        except TimeoutError:
            raise LLMError("timeout") from None
        if status != 200:
            raise LLMError("http_error", status)

        try:
            content = json.loads(text)["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError("bad_response") from None
        if not isinstance(content, str):
            raise LLMError("bad_response")
        return content
