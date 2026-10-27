import hashlib

import pytest

import config
from tools.patch_tools import make_diff, read_snippet

LOGIN = config.PROJECT_ROOT / "samples" / "login.py"


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_snippet_gives_numbered_lines():
    result = read_snippet(LOGIN, 8, 10)

    assert result["ok"] is True
    assert result["snippet"].splitlines() == [
        "8: def find_user(conn, username):",
        "9:     query = \"SELECT * FROM users WHERE name = '\" + username + \"'\"",
        "10:     return conn.execute(query).fetchone()",
    ]


def test_read_snippet_is_cut_to_the_file_and_to_60_lines(tmp_path):
    path = tmp_path / "long.py"
    path.write_text("x = 1\n" * 100)

    assert read_snippet(LOGIN, 15, 500)["end_line"] == 18
    assert read_snippet(path, 1, 100)["end_line"] == 60


@pytest.mark.parametrize("start, end", [(0, 3), (19, 20), (5, 4)])
def test_read_snippet_invalid_range(start, end):
    assert read_snippet(LOGIN, start, end) == {"ok": False, "error": "invalid_range"}


def test_make_diff_returns_a_unified_diff():
    result = make_diff(LOGIN, 5, 5, 'DB_PASSWORD = os.environ.get("DB_PASSWORD", "")')

    assert result["ok"] is True
    assert result["diff"].splitlines()[:2] == ["--- a/samples/login.py", "+++ b/samples/login.py"]
    assert '-DB_PASSWORD = "hunter2"' in result["diff"].splitlines()
    assert '+DB_PASSWORD = os.environ.get("DB_PASSWORD", "")' in result["diff"].splitlines()


def test_tools_never_change_the_file():
    before = file_hash(LOGIN)

    read_snippet(LOGIN, 1, 18)
    make_diff(LOGIN, 5, 5, 'DB_PASSWORD = "changed"')

    assert file_hash(LOGIN) == before


@pytest.mark.parametrize("start, end, replacement, error", [
    (0, 1, "x = 1", "invalid_range"),
    (5, 4, "x = 1", "invalid_range"),
    (5, 19, "x = 1", "invalid_range"),
    (1, 16, "x = 1", "change_too_large"),
    (5, 5, "\n".join(["x = 1"] * 31), "change_too_large"),
    (5, 5, "DB_PASSWORD = (", "syntax_error"),
    (5, 5, 'DB_PASSWORD = "hunter2"', "empty_change"),
])
def test_make_diff_errors(start, end, replacement, error):
    assert make_diff(LOGIN, start, end, replacement) == {"ok": False, "error": error}


def test_make_diff_checks_the_whole_patched_file(tmp_path):
    path = tmp_path / "app.py"
    path.write_text("def f():\n    return 1\n")

    # Valid on its own, but breaks the indentation of the function body.
    assert make_diff(path, 2, 2, "return 1")["error"] == "syntax_error"


def test_patch_tools_reject_non_python_and_missing_files():
    notes = config.PROJECT_ROOT / "samples" / "notes.txt"

    assert read_snippet(notes, 1, 1)["error"] == "unsupported_language"
    assert make_diff(LOGIN.with_name("missing.py"), 1, 1, "x")["error"] == "file_not_found"


# ---------- several changes at once (used by apply) ----------

def test_apply_changes_applies_all_from_the_bottom():
    from tools.patch_tools import apply_changes

    result = apply_changes(LOGIN, [
        (5, 5, 'import os\nDB_PASSWORD = os.environ.get("DB_PASSWORD", "")'),
        (18, 18, '    subprocess.run(["cp", "users.db", target])'),
    ])

    patched = [line.rstrip("\r\n") for line in result["patched"]]
    assert result["ok"] is True
    assert patched[4:6] == ["import os", 'DB_PASSWORD = os.environ.get("DB_PASSWORD", "")']
    assert patched[18] == '    subprocess.run(["cp", "users.db", target])'  # line 18 moved to 19


@pytest.mark.parametrize("changes", [
    [(9, 10, "    pass"), (10, 10, "    pass")],
    [(9, 10, "    pass"), (9, 9, "    pass")],
])
def test_apply_changes_refuses_overlapping_changes(changes):
    from tools.patch_tools import apply_changes

    assert apply_changes(LOGIN, changes) == {"ok": False, "error": "overlapping_changes"}
