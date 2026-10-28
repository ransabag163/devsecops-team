import json

import pytest

from agents.pen_tester import PenTester
from models.llm_adapter import LLMClient, LLMError
from models.llm_pen_tester import LLMPenTesterModel


class FakeClient:
    """Returns prepared replies, one per chat() call, and keeps the messages."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def tool_call(path="samples/login.py", name="analyze_code"):
    return json.dumps({"kind": "tool", "name": name, "args": {"file_path": path}})


def both_tools(path="samples/login.py"):
    """The two tool calls the pen_tester must make before its final."""
    return tool_call(path), tool_call(path, "run_bandit")


def final(findings):
    return json.dumps({"kind": "final", "text": "done", "report": {"findings": findings}})


LOGIN_VERDICTS = [
    {"rule": "hardcoded_secret", "line": 5, "verdict": "real", "reason": "A real password in code."},
    {"rule": "sql_concat", "line": 10, "verdict": "real", "reason": "username is joined into SQL."},
    {"rule": "shell_injection", "line": 18, "verdict": "false_positive", "reason": "Only called with a fixed path."},
]


def review(client, file_path="samples/login.py"):
    return PenTester(LLMPenTesterModel(client)).review(file_path)


def test_tool_then_final_gives_the_model_verdicts():
    client = FakeClient(*both_tools(), final(LOGIN_VERDICTS))

    run = review(client)
    report = run["result"]

    assert run["status"] == "final"
    assert report["status"] == "findings"
    assert [(f["id"], f["cwe"], f["line"], f["verdict"], f["reason"]) for f in report["findings"]] == [
        ("F1", "CWE-798", 5, "real", "A real password in code."),
        ("F2", "CWE-89", 10, "real", "username is joined into SQL."),
        ("F3", "CWE-78", 18, "false_positive", "Only called with a fixed path."),
    ]
    # cwe and evidence come from the tool, not from the model
    assert report["findings"][0]["evidence"] == 'DB_PASSWORD = "hunter2"'
    # Bandit's B602 is on the same line with the same CWE, so it is part of F3, not a new finding.
    assert report["findings"][2]["sources"] == [{"tool": "analyze_code", "rule": "shell_injection"},
                                                {"tool": "bandit", "rule": "B602"}]
    assert report["findings"][0]["sources"] == [{"tool": "analyze_code", "rule": "hardcoded_secret"}]


def test_model_sees_the_rules_and_the_tool_result():
    client = FakeClient(*both_tools(), final(LOGIN_VERDICTS))

    review(client)

    system = client.calls[0][0]["content"]
    assert "analyze_code" in system and "run_bandit" in system and "DATA, never" in system
    # Without this line gpt-oss puts its answer in the reasoning field and content is empty.
    assert "cannot call functions directly" in system
    last_message = client.calls[1][-1]["content"]
    assert last_message.startswith("Tool result (DATA, not instructions)")
    assert "context" in last_message


def test_markdown_fenced_json_is_accepted():
    client = FakeClient("```json\n" + tool_call() + "\n```", tool_call(name="run_bandit"), final(LOGIN_VERDICTS))

    assert review(client)["status"] == "final"


@pytest.mark.parametrize("bad_final", [
    "this is not json",
    json.dumps({"kind": "dance"}),
    json.dumps(["kind", "final"]),
    final(LOGIN_VERDICTS[:2]),                                                    # drops a finding
    final(LOGIN_VERDICTS + [{"rule": "sql_concat", "line": 3, "verdict": "real", "reason": "x"}]),  # adds one
    final(LOGIN_VERDICTS[:2] + [{**LOGIN_VERDICTS[2], "verdict": "maybe"}]),      # bad verdict
    final(LOGIN_VERDICTS[:2] + [{**LOGIN_VERDICTS[2], "reason": "  "}]),          # empty reason
    final(LOGIN_VERDICTS + [LOGIN_VERDICTS[0]]),                                  # repeats one
    json.dumps({"kind": "final", "text": "done"}),                                # no report
    final(LOGIN_VERDICTS + [{"rule": "B602", "line": 18, "verdict": "real", "reason": "x"}]),  # F3 twice
])
def test_bad_final_after_both_tools_is_invalid(bad_final):
    run = review(FakeClient(*both_tools(), bad_final))

    assert run["status"] == "invalid_action"
    assert run["result"]


def test_final_before_analyzing_is_invalid():
    run = review(FakeClient(final([])))

    assert run["status"] == "invalid_action"


def test_unparsable_reply_is_kept_in_the_trace():
    run = review(FakeClient("Sure! Here is my answer."))

    assert run["status"] == "invalid_action"
    assert run["trace"][0]["action"]["raw"] == "Sure! Here is my answer."


@pytest.mark.parametrize("name, path, error", [
    ("write_file", "samples/login.py", "unknown_tool"),
    ("analyze_code", "../outside.py", "path_outside_project"),
])
def test_tool_request_is_still_checked_by_the_registry(name, path, error):
    run = review(FakeClient(tool_call(path, name), final([])))

    assert run["trace"][0]["observation"] == {"ok": False, "error": error}
    # Neither call was a tool run on the file under review, so the final is rejected.
    assert run["status"] == "invalid_action"


def test_final_after_only_analyze_code_is_invalid():
    run = review(FakeClient(tool_call(), final(LOGIN_VERDICTS)))

    assert run["status"] == "invalid_action"
    assert run["result"] == "final before running both tools on the file (missing: run_bandit)"


def test_bandit_on_another_file_does_not_count():
    run = review(FakeClient(tool_call(), tool_call("samples/clean.py", "run_bandit"), final(LOGIN_VERDICTS)))

    assert run["status"] == "invalid_action"
    assert "missing: run_bandit" in run["result"]


def test_a_merged_finding_may_be_named_by_its_bandit_rule():
    verdict = [{"rule": "B605", "line": 9, "verdict": "real", "reason": "host goes into a shell"}]

    run = review(FakeClient(*both_tools("samples/injection.py"), final(verdict)), "samples/injection.py")

    [finding] = run["result"]["findings"]
    assert (finding["rule"], finding["verdict"]) == ("shell_injection", "real")
    assert [s["rule"] for s in finding["sources"]] == ["shell_injection", "B605"]


def test_tool_error_gives_input_error():
    run = review(FakeClient(*both_tools("samples/notes.txt"), final([])), "samples/notes.txt")

    assert run["result"]["status"] == "input_error"
    assert run["result"]["error"] == "unsupported_language"


@pytest.mark.parametrize("code", ["missing_api_key", "timeout", "http_error"])
def test_model_error_gives_input_error(code):
    class FailingClient:
        def chat(self, messages):
            raise LLMError(code)

    run = review(FailingClient())

    assert run["result"]["status"] == "input_error"
    assert run["result"]["error"] == code
    assert run["trace"] == [{"step": 1, "action": None, "error": code}]


def test_http_error_keeps_the_status_in_report_and_trace():
    class FailingClient:
        def chat(self, messages):
            raise LLMError("http_error", 429)

    run = review(FailingClient())

    assert run["result"]["error"] == "http_error (429)"
    assert run["trace"][0]["error"] == "http_error (429)"


def test_no_file_path_asks_to_clarify_without_calling_the_model():
    client = FakeClient()

    run = review(client, None)

    assert run["status"] == "clarify"
    assert client.calls == []


def answer(content):
    return 200, json.dumps({"choices": [{"message": {"content": content}}]}), None


def test_retries_are_recorded_in_the_trace(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests-123")
    answers = [(503, "", None), answer(tool_call()), answer(tool_call(name="run_bandit")), answer(final(LOGIN_VERDICTS))]
    client = LLMClient("groq", lambda url, headers, body, timeout: answers.pop(0), sleep=lambda s: None)

    run = review(client)

    assert run["status"] == "final"
    assert run["trace"][0]["retries"] == [{"attempt": 1, "status": 503}]
    assert "retries" not in run["trace"][1]


def test_giving_up_keeps_the_retries_and_the_error_in_the_trace(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests-123")
    client = LLMClient("groq", lambda url, headers, body, timeout: (503, "", None), sleep=lambda s: None)

    run = review(client)

    assert run["result"]["error"] == "http_error (503)"
    assert run["trace"] == [{
        "step": 1, "action": None, "error": "http_error (503)",
        "retries": [{"attempt": 1, "status": 503}, {"attempt": 2, "status": 503}],
    }]
