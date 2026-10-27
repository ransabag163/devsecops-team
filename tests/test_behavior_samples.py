"""The behavior tests in samples/behavior must tell a weak sample from a good fix."""

import os
import subprocess
import sys

import pytest

import config

LOGIN_FIXED = '''\
import os
import subprocess

DB_PASSWORD = os.environ.get("DB_PASSWORD", "")


def find_user(conn, username):
    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()


def find_user_safe(conn, username):
    return conn.execute("SELECT * FROM users WHERE name = ?", (username,)).fetchone()


def backup_db(target):
    subprocess.run(["cp", "users.db", target])
'''

INJECTION_FIXED = {
    "subprocess": 'import subprocess\n\n\ndef ping(host):\n    subprocess.run(["ping", "-c", "1", host])\n',
    "execvp": 'import os\n\n\ndef ping(host):\n    os.execvp("ping", ["ping", "-c", "1", host])\n',
}


def run_behavior(sample_path, kind, name, rule=None):
    """Run one behavior test file on a sample. Returns the pytest exit code."""
    test_file = config.BEHAVIOR_DIR / f"test_{name}_{kind}.py"
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(test_file)]
    if rule:
        command += ["-k", rule]
    env = {**os.environ, "SAMPLE_UNDER_TEST": str(sample_path), "PYTHONDONTWRITEBYTECODE": "1",
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    return subprocess.run(command, env=env, capture_output=True, timeout=60).returncode


@pytest.mark.parametrize("name", ["login", "injection"])
def test_works_passes_on_the_original(name):
    assert run_behavior(config.PROJECT_ROOT / "samples" / f"{name}.py", "works", name) == 0


@pytest.mark.parametrize("name, rule", [
    ("login", "sql_concat"),
    ("login", "shell_injection"),
    ("login", "hardcoded_secret"),
    ("injection", "shell_injection"),
])
def test_each_attack_fails_on_the_original(name, rule):
    # exit code 1 = tests ran and failed (5 would mean no test matched the rule)
    assert run_behavior(config.PROJECT_ROOT / "samples" / f"{name}.py", "attack", name, rule) == 1


def test_good_login_fix_passes_both_kinds(tmp_path):
    fixed = tmp_path / "login.py"
    fixed.write_text(LOGIN_FIXED, encoding="utf-8")

    assert run_behavior(fixed, "works", "login") == 0
    assert run_behavior(fixed, "attack", "login") == 0


@pytest.mark.parametrize("variant", INJECTION_FIXED)
def test_good_injection_fixes_pass_both_kinds(tmp_path, variant):
    fixed = tmp_path / "injection.py"
    fixed.write_text(INJECTION_FIXED[variant], encoding="utf-8")

    assert run_behavior(fixed, "works", "injection") == 0
    assert run_behavior(fixed, "attack", "injection") == 0
