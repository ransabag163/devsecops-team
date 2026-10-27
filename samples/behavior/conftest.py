"""Shared fixtures for the behavior tests.

The module under test is loaded from the path in SAMPLE_UNDER_TEST, so the same
tests run on an original sample and on a patched copy made by the tester.
No test ever starts a real process: every way to start one is replaced by a
recorder before the module is loaded.
"""

import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

SUBPROCESS_NAMES = ("run", "call", "check_call", "check_output", "Popen", "getoutput", "getstatusoutput")
OS_NAMES = ("system", "popen", "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp",
            "execvpe", "spawnl", "spawnle", "spawnv", "spawnve", "startfile")


class FakeCompleted:
    returncode = 0
    stdout = ""
    stderr = ""


@pytest.fixture
def commands(monkeypatch):
    """Every attempt to start a process, recorded instead of run."""
    calls = []

    def recorder(via):
        def record(*args, **kwargs):
            calls.append({"via": via, "args": args, "kwargs": kwargs})
            return 0 if via.startswith("os.") else FakeCompleted()
        return record

    for name in SUBPROCESS_NAMES:
        monkeypatch.setattr(subprocess, name, recorder(f"subprocess.{name}"))
    for name in OS_NAMES:
        if hasattr(os, name):
            monkeypatch.setattr(os, name, recorder(f"os.{name}"))
    return calls


@pytest.fixture
def sample(commands):
    """The module under test. Loaded after the recorders are in place."""
    path = Path(os.environ["SAMPLE_UNDER_TEST"])
    spec = importlib.util.spec_from_file_location("sample_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sample_source():
    return Path(os.environ["SAMPLE_UNDER_TEST"]).read_text(encoding="utf-8")
