import hashlib

import pytest

import config
from tools.registry import execute
from tools.verify_tools import rescan, run_behavior_tests
from tools.workspace import copy_folder, create_copy, remove_copy

LOGIN = config.PROJECT_ROOT / "samples" / "login.py"
SECRET = {"rule": "hardcoded_secret", "line": 5}
SQL = {"rule": "sql_concat", "line": 10}

GOOD_SQL_FIX = {
    "start_line": 9, "end_line": 10,
    "replacement": '    query = "SELECT * FROM users WHERE name = ?"\n'
                   "    return conn.execute(query, (username,)).fetchone()",
}
# Moves the secret out of the code and adds a line above the other findings.
GOOD_SECRET_FIX = {"start_line": 5, "end_line": 5,
                   "replacement": 'import os\nDB_PASSWORD = os.environ.get("DB_PASSWORD", "")'}


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    path = tmp_path / ".work"
    monkeypatch.setattr(config, "WORK_DIR", path)
    return path


# ---------- patched copies ----------

def test_copy_is_made_inside_work_dir_and_the_original_is_unchanged(work_dir):
    before = file_hash(LOGIN)

    copy = create_copy("samples/login.py", SQL, GOOD_SQL_FIX)

    folder = copy_folder(copy["copy_id"])
    assert folder.parent == work_dir.resolve()
    assert folder.name.startswith("run-")
    assert "conn.execute(query, (username,))" in (folder / "login.py").read_text(encoding="utf-8")
    assert file_hash(LOGIN) == before


def test_a_bad_change_makes_no_copy(work_dir):
    copy = create_copy("samples/login.py", SQL, {"start_line": 9, "end_line": 9, "replacement": "    query = ("})

    assert copy == {"ok": False, "error": "syntax_error"}
    assert not work_dir.exists() or list(work_dir.iterdir()) == []


def test_remove_copy_deletes_only_its_run_folder(work_dir):
    copy_id = create_copy("samples/login.py", SQL, GOOD_SQL_FIX)["copy_id"]
    (work_dir / "keep.txt").write_text("not a run folder")

    for bad_id in ["../samples", "run-../../x", "keep.txt", "run-00000000", 42]:
        assert remove_copy(bad_id) is False

    assert remove_copy(copy_id) is True
    assert [p.name for p in work_dir.iterdir()] == ["keep.txt"]
    assert LOGIN.is_file()


# ---------- rescan ----------

def test_rescan_good_fix_is_closed_with_no_new_findings(work_dir):
    copy_id = create_copy("samples/login.py", SQL, GOOD_SQL_FIX)["copy_id"]

    assert rescan(copy_id) == {"ok": True, "closed": True, "new_findings": []}


def test_rescan_maps_moved_lines_so_old_findings_are_not_new(work_dir):
    copy_id = create_copy("samples/login.py", SECRET, GOOD_SECRET_FIX)["copy_id"]

    # sql_concat moved from 10 to 11 and shell_injection from 18 to 19: still the same findings.
    assert rescan(copy_id) == {"ok": True, "closed": True, "new_findings": []}


def test_rescan_a_change_that_keeps_the_weakness_is_not_closed(work_dir):
    keeps = {"start_line": 9, "end_line": 9,
             "replacement": "    query = \"SELECT name, role FROM users WHERE name = '\" + username + \"'\""}
    copy_id = create_copy("samples/login.py", SQL, keeps)["copy_id"]

    assert rescan(copy_id)["closed"] is False


def test_rescan_reports_a_weakness_the_fix_added(work_dir):
    adds = {"start_line": 9, "end_line": 10,
            "replacement": '    subprocess.run("echo " + username, shell=True)\n'
                           '    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()'}
    copy_id = create_copy("samples/login.py", SQL, adds)["copy_id"]

    result = rescan(copy_id)

    assert result["closed"] is True
    assert [(f["rule"], f["line"]) for f in result["new_findings"]] == [("shell_injection", 9)]


# ---------- run_behavior_tests ----------

def test_behavior_tests_pass_on_a_good_fix(work_dir):
    copy_id = create_copy("samples/login.py", SQL, GOOD_SQL_FIX)["copy_id"]

    result = run_behavior_tests(copy_id)

    assert (result["works"], result["attack"]) == ("passed", "passed")
    assert len(result["output"]) <= 2000


def test_attack_fails_when_the_change_does_not_fix_it(work_dir):
    docstring_only = {"start_line": 1, "end_line": 1, "replacement": '"""A login module."""'}
    copy_id = create_copy("samples/login.py", SQL, docstring_only)["copy_id"]

    result = run_behavior_tests(copy_id)

    assert (result["works"], result["attack"]) == ("passed", "failed")


def test_only_the_attack_for_the_finding_rule_runs(work_dir):
    # The SQL fix leaves the secret and the shell weakness, but only sql_concat is attacked.
    copy_id = create_copy("samples/login.py", SQL, GOOD_SQL_FIX)["copy_id"]

    assert "1 passed" in run_behavior_tests(copy_id)["output"]


def test_no_behavior_tests_for_the_sample_is_not_available(work_dir):
    copy_id = create_copy("samples/clean.py", SQL, {"start_line": 1, "end_line": 1, "replacement": '"""x"""'})["copy_id"]

    result = run_behavior_tests(copy_id)

    assert (result["works"], result["attack"]) == ("not_available", "not_available")


def test_no_attack_test_for_the_rule_is_not_available(work_dir):
    fix = {"start_line": 9, "end_line": 9, "replacement": '    os.execvp("ping", ["ping", "-c", "1", host])'}
    copy_id = create_copy("samples/injection.py", {"rule": "sql_concat", "line": 9}, fix)["copy_id"]

    assert run_behavior_tests(copy_id)["attack"] == "not_available"


@pytest.fixture
def probe(tmp_path, monkeypatch, work_dir):
    """A tiny project with a sample called probe whose behavior tests we write ourselves."""
    root = tmp_path / "project"
    behavior = root / "behavior"
    behavior.mkdir(parents=True)
    (root / "probe.py").write_text("x = 1\n")
    for name in ("conftest.py", "behavior_helpers.py"):
        (behavior / name).write_text("")
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "BEHAVIOR_DIR", behavior)

    def make(works_body, attack_body="def test_attack_x():\n    pass\n"):
        (behavior / "test_probe_works.py").write_text(works_body)
        (behavior / "test_probe_attack.py").write_text(attack_body)
        return create_copy("probe.py", {"rule": "x", "line": 1}, {"start_line": 1, "end_line": 1, "replacement": "x = 2"})["copy_id"]

    return make


ENV_CHECK = '''\
import os

ALLOWED = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "SAMPLE_UNDER_TEST", "PYTHONDONTWRITEBYTECODE",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD"}


def test_environment_is_only_the_allowlist():
    assert "GROQ_API_KEY" not in os.environ
    assert "SOME_SERVICE_TOKEN" not in os.environ
    extra = {k for k in os.environ if k.upper() not in ALLOWED and not k.startswith("PYTEST_")}
    assert extra == set()
    assert os.environ["SAMPLE_UNDER_TEST"].endswith("probe.py")
    assert ".work" in os.environ["TEMP"]
'''


def test_subprocess_gets_no_keys_or_tokens(probe, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake-key-for-tests-123")
    monkeypatch.setenv("SOME_SERVICE_TOKEN", "fake-token-789")

    result = run_behavior_tests(probe(ENV_CHECK))

    assert result["works"] == "passed", result["output"]
    assert "fake-key-for-tests-123" not in result["output"]


def test_a_hanging_behavior_test_is_a_failed_timeout(probe, monkeypatch):
    monkeypatch.setattr(config, "BEHAVIOR_TIMEOUT", 1)

    result = run_behavior_tests(probe("import time\n\n\ndef test_hangs():\n    time.sleep(30)\n"))

    assert result["works"] == "failed"
    assert "timeout after 1s" in result["output"]


# ---------- registry ----------

def tool(name, args):
    return {"kind": "tool", "name": name, "args": args}


@pytest.mark.parametrize("name, args", [
    ("make_diff", {"file_path": "samples/login.py", "start_line": 1, "end_line": 1, "replacement": "x"}),
    ("analyze_code", {"file_path": "samples/login.py"}),
    ("read_snippet", {"file_path": "samples/login.py", "start_line": 1, "end_line": 2}),
])
def test_tester_may_not_use_other_agents_tools(name, args):
    assert execute("tester", tool(name, args), config.PROJECT_ROOT) == {"ok": False, "error": "tool_not_allowed"}


def test_other_agents_may_not_use_the_tester_tools():
    for agent in ("pen_tester", "developer"):
        result = execute(agent, tool("rescan", {"copy_id": "run-00000000"}), config.PROJECT_ROOT)
        assert result == {"ok": False, "error": "tool_not_allowed"}


@pytest.mark.parametrize("args, error", [
    ({"copy_id": 7}, "invalid_arguments"),
    ({"copy_id": "../samples"}, "unknown_copy"),
    ({"copy_id": "run-00000000"}, "unknown_copy"),
])
def test_tester_tools_check_the_copy_id(work_dir, args, error):
    for name in ("rescan", "run_behavior_tests"):
        assert execute("tester", tool(name, args), config.PROJECT_ROOT) == {"ok": False, "error": error}


def test_rescan_a_change_far_from_the_finding_is_not_closed(work_dir):
    docstring_only = {"start_line": 1, "end_line": 1, "replacement": '"""A login module."""'}
    copy_id = create_copy("samples/login.py", SQL, docstring_only)["copy_id"]

    assert rescan(copy_id) == {"ok": True, "closed": False, "new_findings": []}


# ---------- leftover run folders ----------

def make_folder(work_dir, name, age_seconds):
    import os
    import time

    folder = work_dir / name
    folder.mkdir(parents=True)
    old = time.time() - age_seconds
    os.utime(folder, (old, old))
    return folder


def test_only_old_run_folders_are_removed(work_dir):
    from tools.workspace import remove_stale_copies

    make_folder(work_dir, "run-0000aaaa", 2 * 3600)   # old run folder: removed
    make_folder(work_dir, "run-0000bbbb", 60)         # a run that may still be going: kept
    make_folder(work_dir, "notes", 2 * 3600)          # old, but not a run folder: kept
    make_folder(work_dir, "run-TOOLONG1", 2 * 3600)   # not a valid run id: kept

    assert remove_stale_copies() == ["run-0000aaaa"]
    assert sorted(p.name for p in work_dir.iterdir()) == ["notes", "run-0000bbbb", "run-TOOLONG1"]


def test_main_removes_old_run_folders_on_start(work_dir, capsys):
    from main import main

    make_folder(work_dir, "run-0000aaaa", 2 * 3600)

    main(["samples/clean.py"])

    assert list(work_dir.iterdir()) == []


def test_no_work_dir_is_fine(work_dir):
    from tools.workspace import remove_stale_copies

    assert remove_stale_copies() == []


# ---------- combined copies and the unchanged copy ----------

GOOD_SHELL_FIX = {"start_line": 18, "end_line": 18, "replacement": '    subprocess.run(["cp", "users.db", target])'}
SHELL = {"rule": "shell_injection", "line": 18}


def test_combined_copy_maps_lines_through_every_change(work_dir):
    from tools.workspace import create_combined_copy

    # The secret fix adds a line above the SQL fix, and both move the shell finding.
    copy_id = create_combined_copy("samples/login.py", [(SECRET, GOOD_SECRET_FIX), (SQL, GOOD_SQL_FIX)])["copy_id"]

    assert rescan(copy_id) == {"ok": True, "closed": True, "new_findings": []}


def test_combined_copy_is_not_closed_if_one_change_fails(work_dir):
    from tools.workspace import create_combined_copy

    docstring_only = {"start_line": 1, "end_line": 1, "replacement": '"""A login module."""'}
    copy_id = create_combined_copy("samples/login.py", [(SQL, docstring_only), (SHELL, GOOD_SHELL_FIX)])["copy_id"]

    assert rescan(copy_id)["closed"] is False


def test_combined_copy_runs_the_attacks_of_all_chosen_rules(work_dir):
    from tools.workspace import create_combined_copy

    copy_id = create_combined_copy("samples/login.py", [(SQL, GOOD_SQL_FIX), (SHELL, GOOD_SHELL_FIX)])["copy_id"]

    result = run_behavior_tests(copy_id)

    assert (result["works"], result["attack"]) == ("passed", "passed")
    assert "2 passed" in result["output"]  # sql_concat and shell_injection, not hardcoded_secret


def test_the_attack_fails_on_an_unchanged_copy_of_the_original(work_dir):
    from tools.workspace import create_original_copy

    copy_id = create_original_copy("samples/login.py", SQL)["copy_id"]
    folder = copy_folder(copy_id)

    assert (folder / "login.py").read_bytes() == LOGIN.read_bytes()
    assert run_behavior_tests(copy_id)["attack"] == "failed"
