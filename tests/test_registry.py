import pytest

import config
from tools.registry import execute

ROOT = config.PROJECT_ROOT


def tool(name, args):
    return {"kind": "tool", "name": name, "args": args}


def test_allowed_call_runs_the_tool():
    result = execute("pen_tester", tool("analyze_code", {"file_path": "samples/clean.py"}), ROOT)

    assert result == {"ok": True, "findings": []}


def test_unknown_tool_is_blocked():
    result = execute("pen_tester", tool("delete_file", {"file_path": "samples/clean.py"}), ROOT)

    assert result == {"ok": False, "error": "unknown_tool"}


def test_tool_not_on_allowlist_is_blocked():
    result = execute("developer", tool("analyze_code", {"file_path": "samples/clean.py"}), ROOT)

    assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.parametrize("args", [
    {"file_path": "samples/clean.py", "mode": "write"},  # extra argument
    {"file_path": 42},                                   # wrong type
    {},                                                  # missing argument
    "samples/clean.py",                                  # not a dict
])
def test_bad_arguments_are_blocked(args):
    result = execute("pen_tester", tool("analyze_code", args), ROOT)

    assert result == {"ok": False, "error": "invalid_arguments"}


@pytest.mark.parametrize("path", ["../outside.py", str(ROOT.parent / "outside.py")])
def test_path_outside_project_is_blocked(path):
    result = execute("pen_tester", tool("analyze_code", {"file_path": path}), ROOT)

    assert result == {"ok": False, "error": "path_outside_project"}
