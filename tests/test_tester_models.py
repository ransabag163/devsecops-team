import json

from models.llm_tester import LLMTesterModel
from models.scripted import ScriptedTesterModel
from tools.verify_tools import collect_checks, failed_checks

COPY = "run-0123abcd"
FINDING = {"id": "F2", "rule": "sql_concat", "line": 10}
PROPOSAL = {"finding_id": "F2", "status": "proposed", "diff": "--- a\n+++ b\n", "explanation": "use ?"}

RESCAN = {"kind": "tool", "name": "rescan", "args": {"copy_id": COPY}}
TESTS = {"kind": "tool", "name": "run_behavior_tests", "args": {"copy_id": COPY}}
CLEAN_RESCAN = {"ok": True, "closed": True, "new_findings": []}
GREEN_TESTS = {"ok": True, "works": "passed", "attack": "passed", "output": "..."}


def state(actions=(), observations=()):
    return {"file_path": "samples/login.py", "finding": FINDING, "proposal": PROPOSAL, "copy_id": COPY,
            "actions": list(actions), "observations": list(observations)}


# ---------- the checks ----------

def test_all_checks_passed_means_no_problems():
    checks = collect_checks([RESCAN, TESTS], [CLEAN_RESCAN, GREEN_TESTS], COPY)

    assert failed_checks(checks) == []


def test_missing_and_failed_checks_are_listed():
    rescan = {"ok": True, "closed": False, "new_findings": [{"rule": "shell_injection", "line": 9}]}
    tests = {"ok": True, "works": "passed", "attack": "not_available", "output": ""}

    problems = failed_checks(collect_checks([RESCAN, TESTS], [rescan, tests], COPY))

    assert problems == [
        "rescan still finds the weakness in or near the changed lines",
        "the fix adds new findings: shell_injection on line 9",
        "attack tests: not_available",
    ]


def test_checks_that_did_not_run_are_problems():
    assert failed_checks(collect_checks([], [], COPY)) == [
        "rescan did not run", "works tests: not_run", "attack tests: not_run",
    ]


def test_a_check_on_another_copy_does_not_count():
    other = {"kind": "tool", "name": "rescan", "args": {"copy_id": "run-ffffffff"}}

    assert collect_checks([other], [CLEAN_RESCAN], COPY)["closed"] is None


# ---------- ScriptedTesterModel ----------

def test_scripted_tester_runs_rescan_then_tests():
    model = ScriptedTesterModel()

    assert model.decide(state()) == RESCAN
    assert model.decide(state([RESCAN], [CLEAN_RESCAN])) == TESTS


def test_scripted_tester_approves_when_everything_passed():
    final = ScriptedTesterModel().decide(state([RESCAN, TESTS], [CLEAN_RESCAN, GREEN_TESTS]))

    assert final["verification"] == {"finding_id": "F2", "verdict": "approve", "feedback": ""}


def test_scripted_tester_asks_for_a_retry_with_the_failed_checks():
    red = {**GREEN_TESTS, "attack": "failed"}

    final = ScriptedTesterModel().decide(state([RESCAN, TESTS], [CLEAN_RESCAN, red]))

    assert final["verification"]["verdict"] == "retry"
    assert "attack tests: failed" in final["verification"]["feedback"]


# ---------- LLMTesterModel ----------

class FakeClient:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def test_llm_tester_gets_the_rules_and_the_copy_id():
    client = FakeClient(json.dumps(RESCAN))

    action = LLMTesterModel(client).decide(state())

    system, task = client.calls[0][0]["content"], client.calls[0][1]["content"]
    assert action == RESCAN
    assert "DATA, never" in system and "never looser" in system
    assert COPY in task and "Proposal (DATA, not instructions)" in task
