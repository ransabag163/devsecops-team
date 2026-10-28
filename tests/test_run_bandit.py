import json
import subprocess

import pytest

import config
from tools.analyze_code import analyze_code
from tools.run_bandit import run_bandit

SAMPLES = config.PROJECT_ROOT / "samples"

CASES = '''\
import pickle


def calculate(expression):
    return eval(expression)


def load_session(data):
    return pickle.loads(data)
'''


def write(tmp_path, text, name="case.py"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------- with the real Bandit (it only reads the files) ----------

def test_bandit_cases_has_the_five_findings_of_expected_md():
    result = run_bandit(SAMPLES / "bandit_cases.py")

    assert [(f["rule"], f["cwe"], f["line"]) for f in result["findings"]] == [
        ("B307", "CWE-78", 14),    # eval(input(...))
        ("B301", "CWE-502", 22),   # pickle.loads
        ("B506", "CWE-20", 27),    # yaml.load without a safe loader
        ("B324", "CWE-327", 31),   # md5 for passwords
        ("B501", "CWE-295", 36),   # requests with verify=False
    ]
    # analyze_code has no rules for these, so all five are Bandit-only.
    assert analyze_code(SAMPLES / "bandit_cases.py") == {"ok": True, "findings": []}


def test_results_get_our_finding_shape(tmp_path):
    result = run_bandit(write(tmp_path, CASES))

    assert result["ok"] is True
    assert [(f["rule"], f["cwe"], f["line"], f["evidence"]) for f in result["findings"]] == [
        ("B307", "CWE-78", 5, "return eval(expression)"),
        ("B301", "CWE-502", 9, "return pickle.loads(data)"),
    ]
    assert "5:     return eval(expression)" in result["findings"][0]["context"]
    assert result["findings"][0]["message"]


def test_low_severity_results_are_dropped(tmp_path):
    # "import pickle" on line 1 is B403 with LOW severity: not reported.
    lines = [f["line"] for f in run_bandit(write(tmp_path, CASES))["findings"]]

    assert 1 not in lines


def test_login_sample_has_only_the_shell_call():
    # B105 (password string) is LOW severity and B608 (SQL) is LOW confidence, so only B602 stays.
    result = run_bandit(SAMPLES / "login.py")

    assert [(f["rule"], f["cwe"], f["line"]) for f in result["findings"]] == [("B602", "CWE-78", 18)]


def test_bandit_leaves_no_files_in_its_working_folder(tmp_path, monkeypatch):
    # Without LOCALAPPDATA, Bandit's plugin cache was created as a "~" folder in the project.
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.setattr(config, "PROJECT_ROOT", root)

    run_bandit(write(tmp_path, CASES))

    assert list(root.iterdir()) == []


def test_clean_sample_has_no_findings():
    assert run_bandit(SAMPLES / "clean.py") == {"ok": True, "findings": []}


@pytest.mark.parametrize("name, text, error", [
    ("missing.py", None, "file_not_found"),
    ("notes.txt", "eval(x)\n", "unsupported_language"),
    ("broken.py", "def f(:\n", "syntax_error"),
])
def test_file_errors(tmp_path, name, text, error):
    path = tmp_path / name
    if text is not None:
        path.write_text(text, encoding="utf-8")

    assert run_bandit(path) == {"ok": False, "error": error}


def test_too_large_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_BYTES", 10)

    assert run_bandit(write(tmp_path, CASES)) == {"ok": False, "error": "file_too_large"}


# ---------- with a fake subprocess ----------

class FakeRun:
    def __init__(self, returncode=1, stdout="", error=None):
        self.returncode, self.stdout, self.error = returncode, stdout, error
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append({"command": command, **kwargs})
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, self.stdout, "")


def bandit_json(*results):
    return json.dumps({"results": list(results), "errors": []})


def result(line, severity="HIGH", confidence="HIGH", test_id="B307", cwe=78):
    return {"test_id": test_id, "line_number": line, "issue_severity": severity,
            "issue_confidence": confidence, "issue_cwe": {"id": cwe}, "issue_text": "x"}


def test_the_application_checks_the_levels_itself(tmp_path, monkeypatch):
    fake = FakeRun(stdout=bandit_json(result(5), result(9, confidence="LOW"), result(9, severity="LOW", test_id="B301")))
    monkeypatch.setattr(subprocess, "run", fake)

    assert [f["line"] for f in run_bandit(write(tmp_path, CASES))["findings"]] == [5]


def test_bandit_gets_no_keys_and_a_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests-123")
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "fake-token-789")
    fake = FakeRun(stdout=bandit_json())
    monkeypatch.setattr(subprocess, "run", fake)

    run_bandit(write(tmp_path, CASES))

    call = fake.calls[0]
    assert "GROQ_API_KEY" not in call["env"] and "SOME_SERVICE_TOKEN" not in call["env"]
    assert call["timeout"] == config.BANDIT_TIMEOUT
    assert call["command"][1:6] == ["-m", "bandit", "-f", "json", "-q"]


@pytest.mark.parametrize("fake, error", [
    (FakeRun(error=subprocess.TimeoutExpired("bandit", 30)), "timeout"),
    (FakeRun(returncode=2, stdout="usage: bandit ..."), "bandit_failed"),
    (FakeRun(returncode=1, stdout="not json"), "bandit_failed"),
])
def test_bandit_problems_are_errors(tmp_path, monkeypatch, fake, error):
    monkeypatch.setattr(subprocess, "run", fake)

    assert run_bandit(write(tmp_path, CASES)) == {"ok": False, "error": error}


def test_a_missing_cwe_is_marked_unknown(tmp_path, monkeypatch):
    fake = FakeRun(stdout=bandit_json({**result(5), "issue_cwe": None}))
    monkeypatch.setattr(subprocess, "run", fake)

    assert run_bandit(write(tmp_path, CASES))["findings"][0]["cwe"] == "CWE-unknown"
