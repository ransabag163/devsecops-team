import config
from agents.pen_tester import PenTester
from models.scripted import ScriptedPenTesterModel
from tools.findings import merge_findings, only_bandit, rule_names
from tools.registry import execute


def finding(rule, cwe, line, **extra):
    return {"rule": rule, "cwe": cwe, "line": line, "evidence": "x", "context": "x", **extra}


def test_the_same_line_and_cwe_is_one_finding_with_both_sources():
    merged = merge_findings([finding("shell_injection", "CWE-78", 18)],
                            [finding("B602", "CWE-78", 18, message="shell=True")])

    assert len(merged) == 1
    assert merged[0]["rule"] == "shell_injection"  # the rule that has an attack test
    assert merged[0]["sources"] == [{"tool": "analyze_code", "rule": "shell_injection"},
                                    {"tool": "bandit", "rule": "B602"}]
    assert merged[0]["message"] == "shell=True"
    assert rule_names(merged[0]) == {"shell_injection", "B602"}
    assert only_bandit(merged[0]) is False


def test_a_different_cwe_or_line_stays_a_separate_finding():
    merged = merge_findings([finding("sql_concat", "CWE-89", 10)],
                            [finding("B608", "CWE-78", 10), finding("B307", "CWE-89", 11)])

    assert [(f["rule"], f["line"]) for f in merged] == [("B608", 10), ("sql_concat", 10), ("B307", 11)]
    assert [only_bandit(f) for f in merged] == [True, False, True]


def test_no_findings_from_either_tool():
    assert merge_findings([], []) == []


def test_only_the_pen_tester_may_run_bandit():
    action = {"kind": "tool", "name": "run_bandit", "args": {"file_path": "samples/clean.py"}}

    assert execute("pen_tester", action, config.PROJECT_ROOT) == {"ok": True, "findings": []}
    for agent in ("developer", "tester"):
        assert execute(agent, action, config.PROJECT_ROOT) == {"ok": False, "error": "tool_not_allowed"}


def test_run_bandit_paths_must_stay_in_the_project():
    action = {"kind": "tool", "name": "run_bandit", "args": {"file_path": "../outside.py"}}

    assert execute("pen_tester", action, config.PROJECT_ROOT) == {"ok": False, "error": "path_outside_project"}


def test_every_finding_in_bandit_cases_is_bandit_only():
    report = PenTester(ScriptedPenTesterModel()).review("samples/bandit_cases.py")["result"]

    assert [f["rule"] for f in report["findings"]] == ["B307", "B301", "B506", "B324", "B501"]
    assert all(only_bandit(f) and f["message"] for f in report["findings"])
