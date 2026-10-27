"""main.py apply. It only ever writes to a copy of login.py inside a temporary project's .work/."""

import hashlib
import json

import pytest

import config
from main import main

LOGIN = config.PROJECT_ROOT / "samples" / "login.py"
TARGET = ".work/target/login.py"

SECRET_FIX = {"start_line": 5, "end_line": 5, "replacement": 'import os\nDB_PASSWORD = os.environ.get("DB_PASSWORD", "")'}
SQL_FIX = {"start_line": 9, "end_line": 10, "replacement": '    query = "SELECT * FROM users WHERE name = ?"\n'
                                                            "    return conn.execute(query, (username,)).fetchone()"}
SHELL_FIX = {"start_line": 18, "end_line": 18, "replacement": '    subprocess.run(["cp", "users.db", target])'}
OVERLAPS_SQL = {"start_line": 10, "end_line": 10,
                "replacement": '    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()'}
DOES_NOT_FIX = {"start_line": 1, "end_line": 1, "replacement": '"""A login module."""'}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_card(card_id, rule, line, status, change):
    return {"id": card_id, "status": status, "rule": rule, "line": line, "change": change}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A temporary project root whose only Python file is a copy of login.py inside .work/."""
    root = tmp_path / "project"
    target = root / TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes(LOGIN.read_bytes())
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "WORK_DIR", root / ".work")

    report = {"file": TARGET, "sha256": sha256(target), "cards": [
        make_card("F1", "hardcoded_secret", 5, "ready", SECRET_FIX),
        make_card("F2", "sql_concat", 10, "ready", SQL_FIX),
        make_card("F3", "shell_injection", 18, "needs_you", SHELL_FIX),
        make_card("F4", "sql_concat", 10, "ready", OVERLAPS_SQL),
        make_card("F5", "sql_concat", 10, "ready", DOES_NOT_FIX),
    ]}
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return {"root": root, "target": target, "report": str(report_path)}


def apply(project, ids):
    return main(["apply", project["report"], "--ids", ids])


@pytest.mark.parametrize("ids, reason", [
    ("F3", "F3 is not ready (status needs_you)"),
    ("F9", "F9 is not in the report"),
    ("F2,F4", "F2 and F4 change overlapping lines"),
    ("F5", "the combined copy failed its checks"),
])
def test_apply_refuses_and_writes_nothing(project, capsys, ids, reason):
    before = sha256(project["target"])

    assert apply(project, ids) == 3
    assert reason in capsys.readouterr().out
    assert sha256(project["target"]) == before


def test_apply_refuses_when_the_file_changed_since_the_review(project, capsys):
    project["target"].write_text("x = 1\n", encoding="utf-8")

    assert apply(project, "F1") == 3
    assert "the file changed since the review" in capsys.readouterr().out
    assert project["target"].read_text(encoding="utf-8") == "x = 1\n"


def test_a_failing_combined_check_names_the_problem(project, capsys):
    apply(project, "F1,F5")

    out = capsys.readouterr().out
    assert "rescan still finds the weakness" in out and "attack tests: failed" in out


def test_apply_writes_only_the_chosen_file_and_prints_the_diff(project, capsys):
    others_before = {p: sha256(p) for p in project["root"].rglob("*") if p.is_file() and p != project["target"]}
    samples_before = sha256(LOGIN)

    code = apply(project, "F2,F1")
    out = capsys.readouterr().out

    text = project["target"].read_text(encoding="utf-8")
    assert code == 0
    assert 'os.environ.get("DB_PASSWORD", "")' in text and "WHERE name = ?" in text
    assert "hunter2" not in text
    assert "+import os" in out and "applied F1, F2 to .work/target/login.py. Nothing was committed." in out
    others_after = {p: sha256(p) for p in project["root"].rglob("*") if p.is_file() and p != project["target"]}
    assert others_after == others_before  # no other file written, and the combined copy was removed
    assert sha256(LOGIN) == samples_before


def test_apply_refuses_a_file_outside_the_project(project, tmp_path, capsys):
    report = json.loads(open(project["report"], encoding="utf-8").read())
    report["file"] = "../outside.py"
    (tmp_path / "outside.py").write_text("x = 1\n")
    path = tmp_path / "outside.json"
    path.write_text(json.dumps(report), encoding="utf-8")

    assert main(["apply", str(path), "--ids", "F1"]) == 3
    assert "not a file inside the project" in capsys.readouterr().out
    assert (tmp_path / "outside.py").read_text() == "x = 1\n"


def test_apply_refuses_an_unreadable_report(project, tmp_path, capsys):
    assert main(["apply", str(tmp_path / "missing.json"), "--ids", "F1"]) == 3
    assert "cannot read the report" in capsys.readouterr().out
