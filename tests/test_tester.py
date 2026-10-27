import hashlib

import pytest

import config
from agents.tester import Tester
from models.base import DecisionModel
from models.llm_adapter import LLMError
from models.scripted import ScriptedTesterModel
from tools.workspace import copy_folder

LOGIN = config.PROJECT_ROOT / "samples" / "login.py"
FINDINGS_REPORT = {"file": "samples/login.py", "findings": [
    {"id": "F1", "rule": "hardcoded_secret", "line": 5, "verdict": "real"},
    {"id": "F2", "rule": "sql_concat", "line": 10, "verdict": "real"},
]}
GOOD_SQL = {"finding_id": "F2", "status": "proposed", "start_line": 9, "end_line": 10,
            "replacement": '    query = "SELECT * FROM users WHERE name = ?"\n'
                           "    return conn.execute(query, (username,)).fetchone()",
            "diff": "...", "explanation": "use a parameter"}
# Changes only the docstring, so the SQL attack still works.
BAD_SQL = {**GOOD_SQL, "start_line": 1, "end_line": 1, "replacement": '"""A login module."""'}
SKIPPED = {"finding_id": "F1", "status": "skipped", "explanation": "no small fix"}


def fix_report(*proposals):
    return {"file": "samples/login.py", "status": "fixes", "proposals": list(proposals), "error": None}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def work_dir(tmp_path, monkeypatch):
    path = tmp_path / ".work"
    monkeypatch.setattr(config, "WORK_DIR", path)
    return path


class PlanModel(DecisionModel):
    """Plays a fixed list of actions; "{copy}" in args becomes the run's copy_id."""

    def __init__(self, *actions):
        self.actions = list(actions)
        self.copy_ids = []

    def decide(self, state):
        self.copy_ids.append(state["copy_id"])
        action = self.actions.pop(0)
        if action.get("kind") == "tool":
            return {**action, "args": {k: state["copy_id"] if v == "{copy}" else v for k, v in action["args"].items()}}
        return action


RESCAN = {"kind": "tool", "name": "rescan", "args": {"copy_id": "{copy}"}}
TESTS = {"kind": "tool", "name": "run_behavior_tests", "args": {"copy_id": "{copy}"}}


def final(verdict, feedback="", finding_id="F2"):
    return {"kind": "final", "text": "done",
            "verification": {"finding_id": finding_id, "verdict": verdict, "feedback": feedback}}


def verify(model, *proposals, keep_work=False):
    return Tester(model).verify(FINDINGS_REPORT, fix_report(*proposals), keep_work=keep_work)


# ---------- the scripted tester with the real tools ----------

def test_good_fix_is_approved_with_the_checks_from_the_tools():
    run = verify(ScriptedTesterModel(), GOOD_SQL, SKIPPED)
    report = run["result"]

    assert run["status"] == "final"
    assert report["status"] == "verified"
    assert report["verifications"] == [{
        "finding_id": "F2", "closed": True, "new_findings": [], "works": "passed", "attack": "passed",
        "verdict": "approve", "feedback": "", "status": "final",
    }]


def test_bad_fix_gets_retry_with_feedback():
    verification = verify(ScriptedTesterModel(), BAD_SQL)["result"]["verifications"][0]

    assert verification["verdict"] == "retry"
    assert verification["closed"] is False and verification["attack"] == "failed"
    assert "attack tests: failed" in verification["feedback"]


def test_no_proposed_fixes_means_no_proposals():
    run = verify(ScriptedTesterModel(), SKIPPED)

    assert run["result"]["status"] == "no_proposals"
    assert run["runs"] == []


# ---------- what the application enforces ----------

def test_approve_while_a_check_failed_is_blocked_and_becomes_human():
    run = verify(PlanModel(RESCAN, TESTS, final("approve")), BAD_SQL)
    verification = run["result"]["verifications"][0]

    assert run["status"] == "invalid_action"
    assert verification["status"] == "invalid_action"
    assert verification["verdict"] == "human"
    assert "approve is not allowed" in verification["feedback"]
    assert "attack tests: failed" in verification["feedback"]


def test_approve_without_running_the_checks_is_blocked():
    verification = verify(PlanModel(final("approve")), GOOD_SQL)["result"]["verifications"][0]

    assert verification["verdict"] == "human"
    assert "rescan did not run" in verification["feedback"]
    assert (verification["works"], verification["attack"]) == ("not_run", "not_run")


def test_approve_using_checks_of_another_copy_is_blocked():
    other = {"kind": "tool", "name": "rescan", "args": {"copy_id": "run-ffffffff"}}

    verification = verify(PlanModel(other, TESTS, final("approve")), GOOD_SQL)["result"]["verifications"][0]

    assert verification["verdict"] == "human"
    assert "rescan did not run" in verification["feedback"]  # the other copy's result is ignored


def test_the_model_may_be_stricter_than_the_checks():
    run = verify(PlanModel(RESCAN, TESTS, final("human", "the query style changed")), GOOD_SQL)

    assert run["status"] == "final"
    assert run["result"]["verifications"][0]["verdict"] == "human"


@pytest.mark.parametrize("bad_final, problem", [
    (final("retry", "   "), "retry needs feedback"),
    (final("ship it"), "bad verdict"),
    (final("approve", finding_id="F1"), "expected 'F2'"),
    ({"kind": "final", "text": "done"}, "no verification"),
])
def test_bad_finals_are_invalid_actions(bad_final, problem):
    run = verify(PlanModel(RESCAN, TESTS, bad_final), GOOD_SQL)
    verification = run["result"]["verifications"][0]

    assert run["status"] == "invalid_action"
    assert verification["verdict"] == "human"
    assert problem in verification["feedback"]


@pytest.mark.parametrize("name, args", [
    ("make_diff", {"file_path": "samples/login.py", "start_line": 1, "end_line": 1, "replacement": "x = 1"}),
    ("analyze_code", {"file_path": "samples/login.py"}),
])
def test_tester_asking_for_other_tools_is_not_allowed(name, args):
    asks = {"kind": "tool", "name": name, "args": args}

    run = verify(PlanModel(asks, final("human", "could not check")), GOOD_SQL)

    assert run["runs"][0]["trace"][0]["observation"] == {"ok": False, "error": "tool_not_allowed"}


def test_running_out_of_steps_is_budget_exhausted():
    run = verify(PlanModel(RESCAN, RESCAN, RESCAN, RESCAN), GOOD_SQL)

    assert run["status"] == "budget_exhausted"
    assert run["result"]["verifications"][0]["verdict"] == "human"


def test_model_error_gives_input_error():
    class FailingModel(DecisionModel):
        def decide(self, state):
            raise LLMError("http_error", 402)

    run = verify(FailingModel(), GOOD_SQL)

    assert run["result"]["status"] == "input_error"
    assert run["result"]["error"] == "http_error (402)"


# ---------- run folders and the original file ----------

def test_run_folders_are_inside_work_dir_and_removed_afterwards(work_dir):
    before = file_hash(LOGIN)
    model = PlanModel(RESCAN, TESTS, final("approve"))
    seen = []
    decide = model.decide
    model.decide = lambda state: seen.append(copy_folder(state["copy_id"])) or decide(state)

    verify(model, GOOD_SQL)

    assert seen and all(folder.parent == work_dir.resolve() for folder in seen)
    assert list(work_dir.iterdir()) == []
    assert file_hash(LOGIN) == before


def test_keep_work_keeps_the_run_folder(work_dir):
    run = verify(ScriptedTesterModel(), GOOD_SQL, keep_work=True)

    folder = work_dir / run["runs"][0]["copy_id"]
    assert (folder / "login.py").is_file() and (folder / "meta.json").is_file()
