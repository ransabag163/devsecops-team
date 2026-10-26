from models.scripted import ScriptedPenTesterModel

model = ScriptedPenTesterModel()


def test_no_file_path_asks_to_clarify():
    assert model.decide({"file_path": None, "observations": []})["kind"] == "clarify"


def test_first_step_calls_analyze_code():
    action = model.decide({"file_path": "samples/login.py", "observations": []})

    assert action == {"kind": "tool", "name": "analyze_code", "args": {"file_path": "samples/login.py"}}


def test_tool_error_gives_final_with_the_error():
    action = model.decide({"file_path": "x.txt", "observations": [{"ok": False, "error": "unsupported_language"}]})

    assert action["kind"] == "final"
    assert action["report"]["error"] == "unsupported_language"


def test_findings_are_marked_real():
    finding = {"rule": "sql_concat", "cwe": "CWE-89", "line": 3, "evidence": "cur.execute(q)"}
    action = model.decide({"file_path": "a.py", "observations": [{"ok": True, "findings": [finding]}]})

    assert action["report"]["findings"] == [{**finding, "verdict": "real", "reason": "rule match"}]
