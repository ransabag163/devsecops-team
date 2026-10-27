"""The attacks on samples/login.py. Each must FAIL on the original and PASS on a good fix.

Every test name holds the rule it checks, so the tester runs only the attack
for the finding it verifies (pytest -k <rule>).
"""

import sqlite3

from behavior_helpers import command_words, uses_shell

PAYLOAD = "backup.db; rm -rf ~"


def test_attack_sql_concat_login_bypass(sample):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (name TEXT, role TEXT)")
    conn.execute("INSERT INTO users VALUES ('ran', 'admin')")

    assert sample.find_user(conn, "' OR '1'='1") is None


def test_attack_shell_injection_target_is_not_run_by_a_shell(sample, commands):
    sample.backup_db(PAYLOAD)

    assert commands, "backup_db did not run any command"
    for call in commands:
        assert not uses_shell(call)
        assert PAYLOAD in command_words(call)  # one whole argument, not split into commands


def test_attack_hardcoded_secret_is_not_in_the_code(sample, sample_source):
    assert sample.DB_PASSWORD != "hunter2"
    assert "hunter2" not in sample_source
