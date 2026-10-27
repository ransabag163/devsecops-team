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
        return status, text, None

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


# ---------- --fix ----------

def test_fix_prints_both_reports(capsys):
    assert main(["samples/login.py", "--fix"]) == 1
    output = json.loads(capsys.readouterr().out)

    assert output["findings_report"]["status"] == "findings"
    assert output["fix_report"]["status"] == "fixes"
    assert [p["status"] for p in output["fix_report"]["proposals"]] == ["proposed", "skipped", "skipped"]


def test_fix_does_not_change_the_original_file(capsys):
    import hashlib

    import config
    path = config.PROJECT_ROOT / "samples" / "login.py"
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    main(["samples/login.py", "--fix", "--trace"])

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_fix_on_an_input_error_does_not_run_the_developer(capsys):
    assert main(["samples/notes.txt", "--fix"]) == 2
    assert json.loads(capsys.readouterr().out)["fix_report"] is None


def test_fix_trace_has_both_agents(capsys):
    main(["samples/login.py", "--fix", "--trace"])
    trace = json.loads(capsys.readouterr().err)

    assert [entry["step"] for entry in trace["pen_tester"]] == [1, 2]
    assert [run["finding_id"] for run in trace["developer"]] == ["F1", "F2", "F3"]


def route_by_provider(groq_replies, gemini_replies):
    """A fake transport that answers per provider, so each agent gets its own replies."""
    queues = {"api.groq.com": list(groq_replies), "googleapis.com": list(gemini_replies)}

    def transport(url, headers, body, timeout):
        queue = next(q for host, q in queues.items() if host in url)
        return 200, json.dumps({"choices": [{"message": {"content": queue.pop(0)}}]}), None

    return transport


GEMINI_FAKE_KEY = "fake-gemini-key-456"


def llm_fix_replies(proposal_line=9):
    return [
        json.dumps({"kind": "tool", "name": "read_snippet",
                    "args": {"file_path": "samples/injection.py", "start_line": 1, "end_line": 9}}),
        json.dumps({"kind": "final", "text": "done", "proposal": {
            "finding_id": "F1", "status": "proposed", "start_line": proposal_line, "end_line": proposal_line,
            "replacement": '    os.execvp("ping", ["ping", "-c", "1", host])',
            "explanation": "run ping without a shell"}}),
    ]


def test_llm_fix_uses_both_providers_and_never_prints_keys(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_FAKE_KEY)
    use_transport(monkeypatch, route_by_provider(tool_then_final("real"), llm_fix_replies()))

    code = main(["samples/injection.py", "--fix", "--model", "llm", "--trace"])
    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert code == 1
    assert output["fix_report"]["proposals"][0]["status"] == "proposed"
    for key in (FAKE_KEY, GEMINI_FAKE_KEY):
        assert key not in captured.out
        assert key not in captured.err


def test_llm_fix_with_a_bad_proposal_exits_with_2(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.setenv("GEMINI_API_KEY", GEMINI_FAKE_KEY)
    # Line 40 is 31 lines from the finding on line 9, so the developer rejects it.
    use_transport(monkeypatch, route_by_provider(tool_then_final("real"), llm_fix_replies(proposal_line=40)))

    assert main(["samples/injection.py", "--fix", "--model", "llm"]) == 2
    assert "invalid_action" in json.loads(capsys.readouterr().out)["fix_report"]["error"]


def test_llm_fix_missing_gemini_key_exits_with_2(capsys, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", FAKE_KEY)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    use_transport(monkeypatch, route_by_provider(tool_then_final("real"), []))

    assert main(["samples/injection.py", "--fix", "--model", "llm"]) == 2
    fix_report = json.loads(capsys.readouterr().out)["fix_report"]
    assert fix_report["status"] == "input_error"
    assert fix_report["error"] == "missing_api_key"
