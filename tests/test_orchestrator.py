import hashlib
import json

import pytest

import config
import deadline as deadline_module
from agents.developer import Developer
from agents.pen_tester import PenTester
from agents.tester import Tester
from deadline import Deadline
from main import main
from models.base import DecisionModel
from models.scripted import ScriptedDeveloperModel, ScriptedPenTesterModel, ScriptedTesterModel
from orchestrator import Orchestrator, draw_mermaid
from reports import PARTIAL_NOTE, render_markdown
from state import Verification
from tools.findings import merge_findings

SAMPLES = config.PROJECT_ROOT / "samples"

# Changes for F2 (sql_concat on line 10). BAD ones are valid proposals that do not fix the weakness.
GOOD_SQL = (9, 10, '    query = "SELECT * FROM users WHERE name = ?"\n'
                   "    return conn.execute(query, (username,)).fetchone()")
BAD_1 = (1, 1, '"""A login module."""')
BAD_2 = (1, 1, '"""The login module."""')
BAD_3 = (1, 1, '"""Login."""')


class FakePenTester(DecisionModel):
    """Calls analyze_code and run_bandit, then marks only the given rules as real."""

    def __init__(self, *real_rules):
        self.real_rules = real_rules

    def decide(self, state):
        tools = ["analyze_code", "run_bandit"]
        if len(state["observations"]) < 2:
            return {"kind": "tool", "name": tools[len(state["observations"])], "args": {"file_path": state["file_path"]}}
        merged = merge_findings(state["observations"][0]["findings"], state["observations"][1]["findings"])
        findings = [{"rule": f["rule"], "line": f["line"], "reason": "test",
                     "verdict": "real" if f["rule"] in self.real_rules else "false_positive"}
                    for f in merged]
        return {"kind": "final", "text": "done", "report": {"findings": findings}}


class FakeDeveloper(DecisionModel):
    """Proposes the next change of the list at each attempt, and remembers what it was given."""

    def __init__(self, *changes, on_decide=None):
        self.changes = list(changes)
        self.seen = []
        self.on_decide = on_decide

    def decide(self, state):
        self.seen.append({"feedback": state.get("feedback"), "previous": len(state.get("previous_proposals", []))})
        if self.on_decide:
            self.on_decide()
        start, end, replacement = self.changes.pop(0)
        return {"kind": "final", "text": "done", "proposal": {
            "finding_id": state["finding"]["id"], "status": "proposed", "start_line": start, "end_line": end,
            "replacement": replacement, "explanation": "test"}}


class FakeTester(DecisionModel):
    """Runs both checks, then gives the next (verdict, feedback) of the list."""

    def __init__(self, *verdicts):
        self.verdicts = list(verdicts)

    def decide(self, state):
        copy_id = state["copy_id"]
        if len(state["observations"]) == 0:
            return {"kind": "tool", "name": "rescan", "args": {"copy_id": copy_id}}
        if len(state["observations"]) == 1:
            return {"kind": "tool", "name": "run_behavior_tests", "args": {"copy_id": copy_id}}
        verdict, feedback = self.verdicts.pop(0)
        return {"kind": "final", "text": "done",
                "verification": {"finding_id": state["finding"]["id"], "verdict": verdict, "feedback": feedback}}


def review(pen, dev, tst, deadline=None, file_path="samples/login.py"):
    orchestrator = Orchestrator(PenTester(pen), Developer(dev), Tester(tst), deadline or Deadline(600))
    return orchestrator.review(file_path)["final_report"]


def card(report, card_id):
    return next(c for c in report["cards"] if c["id"] == card_id)


# ---------- the retry loop ----------

def test_retry_then_approve_takes_two_attempts_and_passes_the_feedback():
    dev = FakeDeveloper(BAD_1, GOOD_SQL)
    feedback = "attack tests: failed. Use a ? parameter."

    report = review(FakePenTester("sql_concat"), dev, FakeTester(("retry", feedback), ("approve", "")))
    f2 = card(report, "F2")

    assert (f2["status"], f2["attempts"]) == ("ready", 2)
    assert f2["failed_attempts"] == [{"number": 1, "feedback": feedback}]
    assert dev.seen == [{"feedback": None, "previous": 0}, {"feedback": feedback, "previous": 1}]
    assert f2["attack"] == {"before": "failed", "after": "passed"}
    assert f2["change"] == {"start_line": 9, "end_line": 10, "replacement": GOOD_SQL[2]}


def test_three_failed_attempts_need_a_human():
    tester = FakeTester(("retry", "a"), ("retry", "b"), ("retry", "c"))

    report = review(FakePenTester("sql_concat"), FakeDeveloper(BAD_1, BAD_2, BAD_3), tester)
    f2 = card(report, "F2")

    assert (f2["status"], f2["attempts"]) == ("needs_you", 3)
    assert [a["feedback"] for a in f2["failed_attempts"]] == ["a", "b", "c"]
    assert "3 ניסיונות נכשלו." in f2["look_here"]


def test_a_repeated_identical_proposal_is_rejected_by_the_application():
    dev = FakeDeveloper(BAD_1, BAD_1, GOOD_SQL)

    report = review(FakePenTester("sql_concat"), dev, FakeTester(("retry", "not fixed"), ("approve", "")))
    f2 = card(report, "F2")

    assert (f2["status"], f2["attempts"]) == ("ready", 3)
    assert "the same change as attempt 1" in f2["failed_attempts"][1]["feedback"]


def test_human_verdict_goes_straight_to_needs_you_with_the_note():
    report = review(FakePenTester("sql_concat"), FakeDeveloper(GOOD_SQL), FakeTester(("human", "check the style")))
    f2 = card(report, "F2")

    assert (f2["status"], f2["attempts"]) == ("needs_you", 1)
    assert "הערת ה־tester לאדם: check the style" in f2["look_here"]


# ---------- the deadline ----------

@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(deadline_module, "now", lambda: now[0])
    return now


def test_deadline_gives_a_partial_report_with_what_was_not_done(clock):
    def use_up_the_time():
        clock[0] += 1000

    dev = FakeDeveloper(GOOD_SQL, on_decide=use_up_the_time)
    run_deadline = Deadline(600)

    report = review(FakePenTester("sql_concat", "shell_injection"), dev, FakeTester(), run_deadline)

    assert report["status"] == "partial"
    assert report["stop_reason"] == "run deadline passed"
    assert report["not_done"] == ["F2", "F3"]
    assert report["cards"] == []
    assert run_deadline.hit is True


def test_review_command_with_no_time_exits_with_2(capsys, monkeypatch):
    monkeypatch.setattr(config, "REVIEW_DEADLINE_SECONDS", 0)

    code = main(["review", "samples/login.py"])
    output = json.loads(capsys.readouterr().out)

    assert code == 2
    assert output["stop_reason"] == "run deadline passed"
    assert output["not_done"] == ["all findings"]


# ---------- the cards ----------

def scripted_review():
    return review(ScriptedPenTesterModel(), ScriptedDeveloperModel(), ScriptedTesterModel())


def test_cards_put_needs_you_first_and_have_every_field():
    report = scripted_review()

    assert [(c["id"], c["status"]) for c in report["cards"]] == [
        ("F2", "needs_you"), ("F3", "needs_you"), ("F1", "ready")]
    f1 = card(report, "F1")
    assert set(f1) == {"id", "status", "cwe", "rule", "file", "line", "sources", "proof", "problem", "reason",
                       "attack", "change", "diff", "checks", "attempts", "failed_attempts", "look_here"}
    assert f1["proof"] == "attack test"
    assert card(report, "F3")["sources"] == [{"tool": "analyze_code", "rule": "shell_injection"},
                                             {"tool": "bandit", "rule": "B602"}]
    assert (f1["cwe"], f1["rule"], f1["file"], f1["line"]) == ("CWE-798", "hardcoded_secret", "samples/login.py", 5)
    assert f1["checks"] == {"closed": True, "new_findings": [], "works": "passed", "attack": "passed"}
    assert f1["diff"].startswith("--- a/samples/login.py")
    assert f1["problem"] and f1["look_here"] == []
    # The scripted developer skips sql_concat: the card says why, and no tests ran.
    f2 = card(report, "F2")
    assert f2["change"] is None and f2["checks"]["works"] == "not_run"
    assert any("לא הציע תיקון" in item for item in f2["look_here"])


def test_report_keeps_the_sha256_and_the_request_counts():
    report = scripted_review()

    assert report["sha256"] == hashlib.sha256((SAMPLES / "login.py").read_bytes()).hexdigest()
    assert report["model_requests"] == {"pen_tester": 0, "developer": 0, "tester": 0}
    assert report["status"] == "complete" and report["not_done"] == []


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def test_review_never_changes_samples_and_writes_both_report_files(capsys):
    before = snapshot(SAMPLES)

    code = main(["review", "samples/login.py"])
    output = json.loads(capsys.readouterr().out)

    assert code == 1
    assert snapshot(SAMPLES) == before
    assert output["report_files"]["json"].endswith(".json") and output["report_files"]["md"].endswith(".md")
    folder = config.REPORTS_DIR  # the tests' private reports folder (conftest.py)
    assert sorted(p.suffix for p in folder.iterdir()) == [".json", ".md"]
    md = next(folder.glob("*.md")).read_text(encoding="utf-8")
    assert md.index("צריך אותך") < md.index("מוכן להחלה")
    assert "--ids F1" in md


def test_review_of_a_clean_file_has_no_cards_and_exits_with_0(capsys):
    assert main(["review", "samples/clean.py"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "no_findings"


def test_review_trace_prints_graph_nodes_and_agent_steps(capsys):
    main(["review", "samples/login.py", "--trace"])
    err = capsys.readouterr().err

    live = [json.loads(line[len("[trace] "):]) for line in err.splitlines() if line.startswith("[trace] ")]
    nodes = [event["graph"] for event in live if "graph" in event]
    assert nodes[:4] == ["scan", "next_finding", "develop", "verify"] and nodes[-1] == "report"
    assert any(event.get("agent") == "tester" for event in live)


def test_the_graph_drawing_has_every_node():
    orchestrator = Orchestrator(PenTester(ScriptedPenTesterModel()), Developer(ScriptedDeveloperModel()),
                                Tester(ScriptedTesterModel()), Deadline(600))
    drawing = draw_mermaid(orchestrator)

    for node in ("scan", "next_finding", "develop", "verify", "report"):
        assert f"{node}({node})" in drawing
    assert "retry, attempts left" in drawing


# ---------- findings that only Bandit reported ----------

CALC = "def calc(text):\n    return eval(text)\n"
CALC_WORKS = """\
import importlib.util
import os


def load():
    spec = importlib.util.spec_from_file_location("calc", os.environ["SAMPLE_UNDER_TEST"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calc_reads_a_number():
    assert load().calc("2") == 2
"""
INT_FIX = (2, 2, "    return int(text)")  # Bandit stops reporting B307 and the works test passes


@pytest.fixture
def calc_project(tmp_path, monkeypatch):
    """A temporary project: calc.py, whose only finding is Bandit's B307 (eval), and a works test, no attack test."""
    root = tmp_path / "project"
    behavior = root / "behavior"
    behavior.mkdir(parents=True)
    (root / "calc.py").write_text(CALC, encoding="utf-8")
    (behavior / "test_calc_works.py").write_text(CALC_WORKS, encoding="utf-8")
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "BEHAVIOR_DIR", behavior)
    return root


def review_calc(root, dev, tester):
    orchestrator = Orchestrator(PenTester(FakePenTester("B307"), project_root=root),
                                Developer(dev, project_root=root), tester, Deadline(600))
    return orchestrator.review("calc.py")["final_report"]


def test_a_bandit_only_finding_is_checked_but_always_needs_you(calc_project):
    tester = Tester(FakeTester(("human", "no attack test")), project_root=calc_project)

    report = review_calc(calc_project, FakeDeveloper(INT_FIX), tester)
    [f1] = report["cards"]

    assert (f1["rule"], f1["status"], f1["attempts"]) == ("B307", "needs_you", 1)
    assert f1["sources"] == [{"tool": "bandit", "rule": "B307"}]
    assert f1["proof"] == "partial proof: no attack test"
    # rescan (with Bandit) says it is closed and the works test passed, but no attack test could run.
    assert f1["checks"] == {"closed": True, "new_findings": [], "works": "passed", "attack": "not_available"}
    assert f1["attack"] == {"before": "not_available", "after": "not_available"}
    assert f1["look_here"][0] == PARTIAL_NOTE
    assert f1["change"] == {"start_line": 2, "end_line": 2, "replacement": "    return int(text)"}
    md = render_markdown(report)
    assert "partial proof: no attack test" in md and "bandit (B307)" in md


def test_a_bandit_only_finding_gets_one_attempt_and_no_retry(calc_project):
    dev = FakeDeveloper(INT_FIX, INT_FIX)
    tester = Tester(FakeTester(("retry", "use int"), ("approve", "")), project_root=calc_project)

    [f1] = review_calc(calc_project, dev, tester)["cards"]

    assert (f1["status"], f1["attempts"]) == ("needs_you", 1)
    assert len(dev.seen) == 1
    assert f1["failed_attempts"] == [{"number": 1, "feedback": "use int"}]
    assert "הניסיון היחיד נכשל." in f1["look_here"]


class ApprovingTester:
    """Says approve with every check passed, to show the orchestrator itself never makes a Bandit-only card ready."""
    model = ScriptedTesterModel()

    def verify_one(self, file_path, finding, proposal, keep_work=False):
        verification = Verification(finding["id"], True, [], "passed", "passed", "approve", "", "final")
        return {"status": "final", "verification": verification, "run": None}


def test_even_an_approve_does_not_make_a_bandit_only_card_ready(calc_project):
    [f1] = review_calc(calc_project, FakeDeveloper(INT_FIX), ApprovingTester())["cards"]

    assert f1["status"] == "needs_you"
