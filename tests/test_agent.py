import pytest

from agents.base_agent import BaseAgent
from agents.pen_tester import PenTester
from models.base import DecisionModel
from models.scripted import ScriptedPenTesterModel


def review(file_path):
    return PenTester(ScriptedPenTesterModel()).review(file_path)


class AlwaysToolModel(DecisionModel):
    def decide(self, state):
        return {"kind": "tool", "name": "analyze_code", "args": {"file_path": "samples/clean.py"}}


class UnknownKindModel(DecisionModel):
    def decide(self, state):
        return {"kind": "dance"}


# ---------- the pen tester on the samples ----------

def test_login_gives_the_three_expected_findings():
    run = review("samples/login.py")
    report = run["result"]

    assert run["status"] == "final"
    assert report["status"] == "findings"
    assert [(f["id"], f["cwe"], f["line"]) for f in report["findings"]] == [
        ("F1", "CWE-798", 5),
        ("F2", "CWE-89", 10),
        ("F3", "CWE-78", 18),
    ]
    assert all(f["verdict"] == "real" and f["reason"] == "rule match" for f in report["findings"])


def test_safe_query_is_not_reported():
    lines = [f["line"] for f in review("samples/login.py")["result"]["findings"]]

    assert 14 not in lines


def test_clean_gives_no_findings():
    assert review("samples/clean.py")["result"]["status"] == "no_findings"


def test_notes_gives_unsupported_language():
    report = review("samples/notes.txt")["result"]

    assert report["status"] == "input_error"
    assert report["error"] == "unsupported_language"


def test_missing_file_gives_file_not_found():
    report = review("samples/missing.py")["result"]

    assert report["status"] == "input_error"
    assert report["error"] == "file_not_found"


def test_injection_comment_does_not_hide_the_finding():
    report = review("samples/injection.py")["result"]

    assert report["status"] == "findings"
    assert [(f["cwe"], f["line"]) for f in report["findings"]] == [("CWE-78", 9)]


# ---------- the loop enforces the rules ----------

def test_trace_records_each_step():
    trace = review("samples/login.py")["trace"]

    assert [entry["step"] for entry in trace] == [1, 2]
    assert trace[0]["action"]["kind"] == "tool"
    assert trace[0]["observation"]["ok"] is True
    assert trace[1]["action"]["kind"] == "final"
    assert "observation" not in trace[1]


def test_model_that_always_calls_the_tool_runs_out_of_budget():
    run = BaseAgent("pen_tester", AlwaysToolModel(), max_steps=4).run({"file_path": "x", "observations": []})

    assert run["status"] == "budget_exhausted"
    assert len(run["trace"]) == 4


def test_unknown_action_kind_is_invalid():
    run = BaseAgent("pen_tester", UnknownKindModel()).run({"file_path": "x", "observations": []})

    assert run["status"] == "invalid_action"
    assert "observation" not in run["trace"][0]


def test_no_file_path_asks_to_clarify_without_calling_a_tool():
    run = review(None)

    assert run["status"] == "clarify"
    assert all("observation" not in entry for entry in run["trace"])


def test_tool_not_on_allowlist_is_blocked_inside_the_loop():
    run = BaseAgent("developer", AlwaysToolModel(), max_steps=1).run({"file_path": "x", "observations": []})

    assert run["trace"][0]["observation"] == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.parametrize("max_steps", [0, -1, "4", 2.5, True])
def test_max_steps_must_be_a_positive_int(max_steps):
    agent = PenTester(ScriptedPenTesterModel(), max_steps=max_steps)

    with pytest.raises(ValueError):
        agent.review("samples/login.py")
