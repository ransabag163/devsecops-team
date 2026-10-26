import json

import pytest

import models.llm_adapter
from main import main

FAKE_KEY = "fake-key-for-tests-123"


@pytest.mark.parametrize("file_path, code, status", [
    ("samples/clean.py", 0, "no_findings"),
    ("samples/login.py", 1, "findings"),
    ("samples/notes.txt", 2, "input_error"),
    ("samples/missing.py", 2, "input_error"),
])
def test_exit_code_matches_the_report(capsys, file_path, code, status):
    assert main([file_path]) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_no_file_path_is_an_input_error(capsys):
    assert main([]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "clarify"


def test_trace_flag_prints_the_trace(capsys):
    main(["samples/login.py", "--trace"])
    captured = capsys.readouterr()

    assert json.loads(captured.out)["file"] == "samples/login.py"
    assert [entry["step"] for entry in json.loads(captured.err)] == [1, 2]


# ---------- --model llm, always with a fake transport ----------

def fake_transport(*contents, status=200):
    """A transport that answers with the given model replies, in order."""
    replies = list(contents)

    def transport(url, headers, body, timeout):
        text = json.dumps({"choices": [{"message": {"content": replies.pop(0)}}]}) if replies else ""
        return status, text

    return transport


def use_transport(monkeypatch, transport):
    monkeypatch.setattr(models.llm_adapter, "urllib_transport", transport)


def tool_then_final(verdict):
    return (
        json.dumps({"kind": "tool", "name": "analyze_code", "args": {"file_path": "samples/injection.py"}}),
        json.dumps({"kind": "final", "text": "done", "report": {"findings": [
            {"rule": "shell_injection", "line": 9, "verdict": verdict, "reason": "checked the context"},
        ]}}),
    )


@pytest.mark.parametrize("verdict, code", [("real", 1), ("false_positive", 0)])
def test_llm_exit_code_counts_only_real_findings(capsys, monkeypatch, verdict, code):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    use_transport(monkeypatch, fake_transport(*tool_then_final(verdict)))

    assert main(["samples/injection.py", "--model", "llm"]) == code
    report = json.loads(capsys.readouterr().out)
    assert report["findings"][0]["verdict"] == verdict  # false_positive stays in the report


def test_llm_missing_key_is_an_input_error(capsys, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert main(["samples/login.py", "--model", "llm", "--trace"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "input_error"
    assert report["error"] == "missing_api_key"


@pytest.mark.parametrize("transport", [
    fake_transport(*tool_then_final("real")),
    fake_transport(status=401),
    fake_transport("not json at all"),
])
def test_api_key_never_appears_in_the_output(capsys, monkeypatch, transport):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    use_transport(monkeypatch, transport)

    main(["samples/injection.py", "--model", "llm", "--trace"])
    captured = capsys.readouterr()

    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err


def test_llm_invalid_action_exits_with_2(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    use_transport(monkeypatch, fake_transport("not json at all"))

    assert main(["samples/login.py", "--model", "llm"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_action"
