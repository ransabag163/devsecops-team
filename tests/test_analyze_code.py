import hashlib

import pytest

import config
from tools.analyze_code import analyze_code

SAMPLES = config.PROJECT_ROOT / "samples"


def cwe_and_line(result):
    return {(f["cwe"], f["line"]) for f in result["findings"]}


def test_login_has_exactly_the_three_expected_findings():
    result = analyze_code(SAMPLES / "login.py")

    assert result["ok"] is True
    assert len(result["findings"]) == 3
    assert cwe_and_line(result) == {("CWE-798", 5), ("CWE-89", 10), ("CWE-78", 18)}


def test_safe_parameterized_query_is_not_reported():
    result = analyze_code(SAMPLES / "login.py")

    assert 14 not in {f["line"] for f in result["findings"]}


def test_clean_file_has_no_findings():
    assert analyze_code(SAMPLES / "clean.py") == {"ok": True, "findings": []}


def test_prompt_injection_comment_does_not_hide_the_finding():
    result = analyze_code(SAMPLES / "injection.py")

    assert cwe_and_line(result) == {("CWE-78", 9)}


def test_finding_has_rule_and_evidence():
    finding = analyze_code(SAMPLES / "injection.py")["findings"][0]

    assert finding["rule"] == "shell_injection"
    assert finding["evidence"] == 'os.system("ping -c 1 " + host)'


def test_not_python_is_unsupported():
    assert analyze_code(SAMPLES / "notes.txt") == {"ok": False, "error": "unsupported_language"}


def test_missing_file_is_not_found():
    assert analyze_code(SAMPLES / "missing.py") == {"ok": False, "error": "file_not_found"}


def test_broken_python_is_syntax_error(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n")

    assert analyze_code(bad) == {"ok": False, "error": "syntax_error"}


def test_big_file_is_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_BYTES", 10)
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 10)

    assert analyze_code(big) == {"ok": False, "error": "file_too_large"}


def test_analyze_does_not_change_the_file():
    path = SAMPLES / "login.py"
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    analyze_code(path)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("code", [
    'cur.execute(f"SELECT * FROM t WHERE id = {uid}")',
    'cur.execute("DELETE FROM t WHERE id = %s" % uid)',
    'cur.execute("UPDATE t SET a = {}".format(a))',
    'q = "INSERT INTO t VALUES (" + v + ")"\ncur.execute(q)',
])
def test_every_way_of_building_sql_is_found(tmp_path, code):
    path = tmp_path / "db.py"
    path.write_text(code + "\n")

    rules = [f["rule"] for f in analyze_code(path)["findings"]]

    assert rules == ["sql_concat"]


@pytest.mark.parametrize("code, expected", [
    ('API_KEY = "abc"', ["hardcoded_secret"]),
    ('self.Token = "abc"', ["hardcoded_secret"]),
    ('password = ""', []),
    ('subprocess.call(cmd, shell=True)', ["shell_injection"]),
    ('subprocess.call("ls -l", shell=True)', []),
    ('subprocess.call(cmd)', []),
    ('os.system("ls")', []),
])
def test_secret_and_shell_rules(tmp_path, code, expected):
    path = tmp_path / "app.py"
    path.write_text("import os, subprocess\n" + code + "\n")

    rules = [f["rule"] for f in analyze_code(path)["findings"]]

    assert rules == expected
