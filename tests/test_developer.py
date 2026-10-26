import hashlib

import pytest

import config
from agents.developer import Developer
from models.base import DecisionModel
from models.scripted import ScriptedDeveloperModel

LOGIN = "samples/login.py"


def finding(fid, rule, line, verdict="real"):
    return {"id": fid, "cwe": "CWE-x", "rule": rule, "line": line, "evidence": "...",
            "verdict": verdict, "reason": "test"}


def report(*findings):
    return {"file": LOGIN, "status": "findings", "findings": list(findings), "error": None}


SECRET = finding("F1", "hardcoded_secret", 5)
SQL = finding("F2", "sql_concat", 10)
SHELL = finding("F3", "shell_injection", 18)


class PlanModel(DecisionModel):
    """Plays a fixed list of actions per finding id, and records what it saw."""

    def __init__(self, plans):
        self.plans = plans
        self.seen = []

    def decide(self, state):
        fid = state["finding"]["id"]
        if not state["observations"]:  # first step for this finding
            self.seen.append(fid)
        return self.plans[fid][len(state["observations"])]


def read(start=1, end=10):
    return {"kind": "tool", "name": "read_snippet",
            "args": {"file_path": LOGIN, "start_line": start, "end_line": end}}


def diff(start, end, replacement):
    return {"kind": "tool", "name": "make_diff",
            "args": {"file_path": LOGIN, "start_line": start, "end_line": end, "replacement": replacement}}


def proposed(fid, start, end, replacement, **extra):
    return {"kind": "final", "text": "done", "proposal": {
        "finding_id": fid, "status": "proposed", "start_line": start, "end_line": end,
        "replacement": replacement, "explanation": "use a parameter", **extra}}


def skipped(fid, explanation):
    return {"kind": "final", "text": "done",
            "proposal": {"finding_id": fid, "status": "skipped", "explanation": explanation}}


SQL_FIX = '    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()'


def fix(model, *findings):
    return Developer(model).fix(report(*findings))


# ---------- the scripted developer ----------

def test_scripted_fixes_the_secret_and_skips_the_rest():
    run = fix(ScriptedDeveloperModel(), SECRET, SQL, SHELL)
    proposals = run["result"]["proposals"]

    assert run["status"] == "final"
    assert run["result"]["status"] == "fixes"
    assert [(p["finding_id"], p["status"]) for p in proposals] == [
        ("F1", "proposed"), ("F2", "skipped"), ("F3", "skipped")]
    diff_lines = proposals[0]["diff"].splitlines()
    assert "+import os" in diff_lines
    assert '-DB_PASSWORD = "hunter2"' in diff_lines
    assert '+DB_PASSWORD = os.environ.get("DB_PASSWORD", "")' in diff_lines
    assert all(p["explanation"] for p in proposals[1:])


def test_scripted_uses_one_line_when_os_is_already_imported(tmp_path):
    (tmp_path / "app.py").write_text('import os\n\napi_key = "abc"\n')
    developer = Developer(ScriptedDeveloperModel(), project_root=tmp_path)

    result = developer.fix({"file": "app.py", "findings": [finding("F1", "hardcoded_secret", 3)]})["result"]

    assert result["proposals"][0]["start_line"] == 3
    assert result["proposals"][0]["replacement"] == 'api_key = os.environ.get("API_KEY", "")'


# ---------- a valid LLM-style flow ----------

def test_read_then_diff_then_final_proposed():
    model = PlanModel({"F2": [read(8, 10), diff(10, 10, SQL_FIX), proposed("F2", 10, 10, SQL_FIX, diff="evil")]})

    run = fix(model, SQL)
    proposal = run["result"]["proposals"][0]

    assert run["status"] == "final"
    assert proposal["status"] == "proposed"
    assert proposal["diff"] != "evil"  # the app made the diff itself
    assert "+" + SQL_FIX in proposal["diff"].splitlines()


def test_each_proposal_is_a_separate_diff_against_the_original():
    model = PlanModel({
        "F1": [proposed("F1", 5, 5, 'DB_PASSWORD = ""')],
        "F2": [proposed("F2", 10, 10, SQL_FIX)],
    })

    proposals = fix(model, SECRET, SQL)["result"]["proposals"]

    assert 'DB_PASSWORD = ""' not in proposals[1]["diff"]
    assert '-    return conn.execute(query).fetchone()' in proposals[1]["diff"].splitlines()


# ---------- the application rejects bad proposals ----------

@pytest.mark.parametrize("bad_final, problem", [
    (proposed("F2", 22, 22, "x = 1"), "lines from the finding"),
    (proposed("F2", 10, 10, "    return conn.execute(("), "syntax_error"),
    (proposed("F2", 1, 16, "x = 1"), "change_too_large"),
    (proposed("F2", 10, 10, "    return conn.execute(query).fetchone()"), "empty_change"),
    (proposed("F9", 10, 10, SQL_FIX), "expected 'F2'"),
    (proposed("F2", "10", 10, SQL_FIX), "int start_line"),
    (skipped("F2", "   "), "needs an explanation"),
    ({"kind": "final", "text": "done", "proposal": {"finding_id": "F2", "status": "maybe", "explanation": "x"}},
     "bad proposal status"),
    ({"kind": "final", "text": "done"}, "no proposal"),
])
def test_bad_proposal_is_invalid_action(bad_final, problem):
    run = fix(PlanModel({"F2": [bad_final]}), SQL)

    assert run["status"] == "invalid_action"
    assert run["runs"][0]["status"] == "invalid_action"
    assert run["result"]["proposals"] == []
    assert problem in run["result"]["error"]


def test_one_bad_finding_does_not_stop_the_others():
    model = PlanModel({"F1": [skipped("F1", "")], "F2": [proposed("F2", 10, 10, SQL_FIX)]})

    run = fix(model, SECRET, SQL)

    assert run["status"] == "invalid_action"
    assert run["result"]["status"] == "fixes"
    assert [p["finding_id"] for p in run["result"]["proposals"]] == ["F2"]
    assert run["result"]["error"].startswith("F1: invalid_action")


def test_developer_cannot_call_analyze_code():
    model = PlanModel({"F2": [{"kind": "tool", "name": "analyze_code", "args": {"file_path": LOGIN}},
                              skipped("F2", "could not analyze")]})

    run = fix(model, SQL)

    assert run["runs"][0]["trace"][0]["observation"] == {"ok": False, "error": "tool_not_allowed"}


def test_budget_is_fresh_for_each_finding():
    reads = [read()] * 4
    model = PlanModel({"F1": reads + [skipped("F1", "done")], "F2": reads + [skipped("F2", "done")]})

    run = fix(model, SECRET, SQL)

    assert run["status"] == "final"
    assert [len(r["trace"]) for r in run["runs"]] == [5, 5]


# ---------- what reaches the developer ----------

def test_false_positive_findings_never_reach_the_developer():
    model = PlanModel({"F2": [skipped("F2", "not now")]})

    fix(model, finding("F1", "hardcoded_secret", 5, verdict="false_positive"), SQL)

    assert model.seen == ["F2"]


def test_no_real_findings_gives_no_fixes():
    run = fix(PlanModel({}), finding("F1", "hardcoded_secret", 5, verdict="false_positive"))

    assert run["result"] == {"file": LOGIN, "status": "no_fixes", "proposals": [], "error": None}


def test_developer_does_not_change_the_file():
    path = config.PROJECT_ROOT / LOGIN
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    fix(ScriptedDeveloperModel(), SECRET, SQL, SHELL)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
