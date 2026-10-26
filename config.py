"""Project-wide settings."""

import os
from pathlib import Path

# The folder that contains this file. Tools may only touch files inside it.
PROJECT_ROOT = Path(__file__).resolve().parent

# How many decisions an agent may make before we stop it.
MAX_STEPS = 4

# Files larger than this are not analyzed.
MAX_FILE_BYTES = 200_000

# Seconds to wait for a model API answer.
HTTP_TIMEOUT = 30

# OpenAI-compatible model providers. Keys and model names come from the environment.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
    },
}

# Which provider each agent uses. Later each agent may get its own.
AGENT_PROVIDER = {
    "pen_tester": "groq",
}


def load_env(path):
    """Copy KEY=VALUE lines from a .env file into os.environ.

    Values that are already set in the environment win. Values are never printed.
    """
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


load_env(PROJECT_ROOT / ".env")
