from models.scripted import ScriptedPenTesterModel

model = ScriptedPenTesterModel()


def test_no_file_path_asks_to_clarify():
    assert model.decide({"file_path": None, "observations": []})["kind"] == "clarify"


def test_first_step_calls_analyze_code():
    action = model.decide({"file_path": "samples/login.py", "observations": []})

    assert action == {"kind": "tool", "name": "analyze_code", "args": {"file_path": "samples/login.py"}}


def test_second_step_calls_run_bandit():
    action = model.decide({"file_path": "samples/login.py", "observations": [{"ok": True, "findings": []}]})

    assert action == {"kind": "tool", "name": "run_bandit", "args": {"file_path": "samples/login.py"}}


def test_tool_error_gives_final_with_the_error():
    failed = {"ok": False, "error": "unsupported_language"}
    action = model.decide({"file_path": "x.txt", "observations": [failed, failed]})

    assert action["kind"] == "final"
    assert action["report"]["error"] == "unsupported_language"


def test_merged_findings_are_marked_real():
    code = {"rule": "shell_injection", "cwe": "CWE-78", "line": 3, "evidence": "os.system(x)"}
    same_line = {"rule": "B605", "cwe": "CWE-78", "line": 3, "evidence": "os.system(x)", "message": "shell"}
    bandit_only = {"rule": "B307", "cwe": "CWE-78", "line": 7, "evidence": "eval(x)", "message": "eval"}
    observations = [{"ok": True, "findings": [code]}, {"ok": True, "findings": [same_line, bandit_only]}]

    action = model.decide({"file_path": "a.py", "observations": observations})

    assert action["report"]["findings"] == [
        {"rule": "shell_injection", "line": 3, "verdict": "real", "reason": "rule match"},
        {"rule": "B307", "line": 7, "verdict": "real", "reason": "rule match"},
    ]
