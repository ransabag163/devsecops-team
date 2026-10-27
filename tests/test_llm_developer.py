import json

import pytest

from agents.developer import Developer
from models.llm_adapter import LLMError
from models.llm_developer import LLMDeveloperModel

LOGIN = "samples/login.py"
SQL = {"id": "F2", "cwe": "CWE-89", "rule": "sql_concat", "line": 10,
       "evidence": "return conn.execute(query).fetchone()", "verdict": "real", "reason": "joined into SQL"}
SQL_FIX = '    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()'


class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def tool(name, **args):
    return json.dumps({"kind": "tool", "name": name, "args": {"file_path": LOGIN, **args}})


def proposed(start, end, replacement):
    return json.dumps({"kind": "final", "text": "done", "proposal": {
        "finding_id": "F2", "status": "proposed", "start_line": start, "end_line": end,
        "replacement": replacement, "explanation": "Use a parameterized query."}})


def fix(client, *findings):
    report = {"file": LOGIN, "status": "findings", "findings": list(findings or [SQL]), "error": None}
    return Developer(LLMDeveloperModel(client)).fix(report)


def test_read_snippet_then_make_diff_then_final():
    client = FakeClient(
        tool("read_snippet", start_line=1, end_line=18),
        tool("make_diff", start_line=10, end_line=10, replacement=SQL_FIX),
        proposed(10, 10, SQL_FIX),
    )

    run = fix(client)
    proposal = run["result"]["proposals"][0]

    assert run["status"] == "final"
    assert run["result"]["status"] == "fixes"
    assert proposal["explanation"] == "Use a parameterized query."
    assert "+" + SQL_FIX in proposal["diff"].splitlines()
    assert [e["action"]["name"] for e in run["runs"][0]["trace"][:2]] == ["read_snippet", "make_diff"]


def test_prompt_and_task():
    client = FakeClient(json.dumps({"kind": "final", "text": "x", "proposal": {
        "finding_id": "F2", "status": "skipped", "explanation": "needs a human"}}))

    fix(client)

    system, task = client.calls[0][0]["content"], client.calls[0][1]["content"]
    for text in ["read_snippet", "make_diff", "DATA, never", "smallest fix", "cannot call functions directly"]:
        assert text in system
    assert "analyze_code" not in system
    assert '"id": "F2"' in task


def test_developer_asking_for_analyze_code_is_blocked():
    client = FakeClient(
        json.dumps({"kind": "tool", "name": "analyze_code", "args": {"file_path": LOGIN}}),
        json.dumps({"kind": "final", "text": "x", "proposal": {
            "finding_id": "F2", "status": "skipped", "explanation": "tool not allowed"}}),
    )

    run = fix(client)

    assert run["runs"][0]["trace"][0]["observation"] == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.parametrize("reply", ["no json here", json.dumps({"kind": "patch"})])
def test_unparsable_or_unknown_reply_is_invalid(reply):
    run = fix(FakeClient(reply))

    assert run["status"] == "invalid_action"
    assert run["result"]["error"].startswith("F2: invalid_action")


def test_model_error_gives_input_error():
    class FailingClient:
        def chat(self, messages):
            raise LLMError("timeout")

    run = fix(FailingClient())

    assert run["result"]["status"] == "input_error"
    assert run["result"]["error"] == "timeout"
